"""
Payment Processor Lambda Handler.

This Lambda function creates PayStack payment links for matched grocery orders.
"""

import json
import os
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, batch_processor
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
import boto3
from botocore.exceptions import ClientError
import urllib.request
import urllib.error

# Initialize AWS Lambda Powertools
logger = Logger()
tracer = Tracer()
metrics = Metrics()

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client("secretsmanager")
events_client = boto3.client("events")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
ORDERS_TABLE_NAME = os.environ.get("ORDERS_TABLE_NAME", "")
PAYMENT_LINKS_TABLE_NAME = os.environ.get("PAYMENT_LINKS_TABLE_NAME", "")
PAYSTACK_BASE_URL = os.environ.get("PAYSTACK_BASE_URL", "https://api.paystack.co")
PAYSTACK_SECRET_ARN = os.environ.get("PAYSTACK_SECRET_ARN", "")

# Initialize batch processor
processor = BatchProcessor(event_type=EventType.SQS)

# Cache for PayStack API key
_paystack_api_key: Optional[str] = None


@tracer.capture_method
def get_paystack_api_key() -> str:
    """Retrieve PayStack API key from Secrets Manager."""
    global _paystack_api_key
    
    if _paystack_api_key:
        return _paystack_api_key
    
    if not PAYSTACK_SECRET_ARN:
        raise ValueError("PAYSTACK_SECRET_ARN not configured")
    
    try:
        response = secrets_client.get_secret_value(SecretId=PAYSTACK_SECRET_ARN)
        secret_data = json.loads(response["SecretString"])
        _paystack_api_key = secret_data.get("api_key", "")
        return _paystack_api_key
    except ClientError as e:
        logger.error("Failed to retrieve PayStack API key", extra={"error": str(e)})
        raise


@tracer.capture_method
def create_payment_link_with_retry(
    order_id: str,
    customer_email: str,
    customer_name: Optional[str],
    items: list,
    total_amount: float,
    max_retries: int = 3
) -> Dict[str, Any]:
    """
    Create PayStack payment link with exponential backoff retry.
    
    Args:
        order_id: Unique order identifier
        customer_email: Customer's email address
        customer_name: Customer's name (optional)
        items: List of matched items
        total_amount: Total order amount
        max_retries: Maximum retry attempts
        
    Returns:
        PayStack payment link response
    """
    api_key = get_paystack_api_key()
    
    # Calculate expiration (24 hours from now)
    expires_at = datetime.utcnow() + timedelta(hours=24)
    
    # Prepare PayStack payload
    payload = {
        "amount": int(total_amount * 100),  # Convert to kobo
        "currency": "NGN",
        "email": customer_email,
        "reference": f"order-{order_id}",
        "metadata": {
            "order_id": order_id,
            "customer_name": customer_name or "",
            "item_count": len(items),
            "custom_fields": [
                {
                    "display_name": "Order ID",
                    "variable_name": "order_id",
                    "value": order_id
                }
            ]
        },
        "callback_url": f"https://api.example.com/payment/callback/{order_id}"
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    url = f"{PAYSTACK_BASE_URL}/transaction/initialize"
    
    for attempt in range(max_retries):
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            
            with urllib.request.urlopen(request, timeout=30) as response:
                response_data = json.loads(response.read().decode("utf-8"))
                
                if response_data.get("status"):
                    return {
                        "success": True,
                        "authorization_url": response_data["data"]["authorization_url"],
                        "access_code": response_data["data"]["access_code"],
                        "reference": response_data["data"]["reference"],
                        "expires_at": expires_at.isoformat()
                    }
                else:
                    raise ValueError(f"PayStack API error: {response_data.get('message')}")
                    
        except urllib.error.HTTPError as e:
            logger.warning(
                "PayStack API HTTP error",
                extra={"attempt": attempt + 1, "status": e.code, "error": str(e)}
            )
            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s
                time.sleep(2 ** attempt)
            else:
                raise
                
        except urllib.error.URLError as e:
            logger.warning(
                "PayStack API URL error",
                extra={"attempt": attempt + 1, "error": str(e)}
            )
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise
    
    raise RuntimeError("Failed to create payment link after all retries")


@tracer.capture_method
def store_payment_link(
    order_id: str,
    payment_data: Dict[str, Any],
    customer_email: str,
    total_amount: float
) -> None:
    """Store payment link in DynamoDB with TTL."""
    table = dynamodb.Table(PAYMENT_LINKS_TABLE_NAME)
    
    # Calculate TTL (24 hours from now)
    expires_at = int((datetime.utcnow() + timedelta(hours=24)).timestamp())
    
    table.put_item(
        Item={
            "order_id": order_id,
            "payment_link": payment_data["authorization_url"],
            "access_code": payment_data["access_code"],
            "reference": payment_data["reference"],
            "customer_email": customer_email,
            "amount": Decimal(str(total_amount)),
            "status": "PENDING",
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at
        }
    )


@tracer.capture_method
def update_order_with_payment(
    order_id: str,
    created_at: str,
    payment_link: str
) -> None:
    """Update order in DynamoDB with payment link."""
    table = dynamodb.Table(ORDERS_TABLE_NAME)
    
    table.update_item(
        Key={"order_id": order_id, "created_at": created_at},
        UpdateExpression="SET #status = :status, payment_link = :link, payment_status = :payment_status",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "PAYMENT_LINK_CREATED",
            ":link": payment_link,
            ":payment_status": "PENDING"
        }
    )


@tracer.capture_method
def publish_payment_event(order_id: str, payment_link: str, customer_email: str) -> None:
    """Publish payment link created event to EventBridge."""
    try:
        events_client.put_events(
            Entries=[
                {
                    "Source": "ai-grocery.payments",
                    "DetailType": "PaymentLinkCreated",
                    "Detail": json.dumps({
                        "order_id": order_id,
                        "payment_link": payment_link,
                        "customer_email": customer_email,
                        "timestamp": datetime.utcnow().isoformat()
                    }),
                    "EventBusName": f"ai-grocery-events-{ENVIRONMENT}"
                }
            ]
        )
    except ClientError as e:
        logger.warning("Failed to publish event", extra={"error": str(e)})


def record_handler(record: SQSRecord) -> Dict[str, Any]:
    """Process individual SQS record."""
    logger.info("Processing SQS record", extra={"message_id": record.message_id})
    
    # Parse message body
    body = json.loads(record.body)
    order_id = body.get("order_id")
    correlation_id = body.get("correlation_id", record.message_id)
    customer_email = body.get("customer_email")
    customer_name = body.get("customer_name")
    matched_items = body.get("matched_items", [])
    total_amount = body.get("total_amount", 0)
    created_at = body.get("created_at")
    
    logger.append_keys(
        order_id=order_id,
        correlation_id=correlation_id
    )
    
    try:
        # Validate total amount
        if total_amount <= 0:
            logger.warning("Order has zero total amount", extra={"order_id": order_id})
            # Still create a record but mark as no payment needed
            if ORDERS_TABLE_NAME and created_at:
                update_order_with_payment(order_id, created_at, "NO_PAYMENT_REQUIRED")
            return {"status": "skipped", "order_id": order_id, "reason": "zero_amount"}
        
        # Create PayStack payment link with retry
        payment_data = create_payment_link_with_retry(
            order_id=order_id,
            customer_email=customer_email,
            customer_name=customer_name,
            items=matched_items,
            total_amount=total_amount
        )
        
        # Store payment link
        if PAYMENT_LINKS_TABLE_NAME:
            store_payment_link(order_id, payment_data, customer_email, total_amount)
        
        # Update order
        if ORDERS_TABLE_NAME and created_at:
            update_order_with_payment(order_id, created_at, payment_data["authorization_url"])
        
        # Publish event
        publish_payment_event(order_id, payment_data["authorization_url"], customer_email)
        
        metrics.add_metric(name="PaymentLinkCreated", unit="Count", value=1)
        metrics.add_metric(name="PaymentAmount", unit="None", value=total_amount)
        
        logger.info(
            "Successfully created payment link",
            extra={"order_id": order_id, "amount": total_amount}
        )
        
        return {
            "status": "success",
            "order_id": order_id,
            "payment_link": payment_data["authorization_url"]
        }
        
    except Exception as e:
        metrics.add_metric(name="PaymentLinkError", unit="Count", value=1)
        logger.exception("Error creating payment link", extra={"order_id": order_id, "error": str(e)})
        raise


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
@batch_processor(record_handler=record_handler, processor=processor)
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Main Lambda handler for payment processing.
    
    Processes SQS messages containing matched order items,
    creates PayStack payment links, and stores results.
    """
    return processor.response()
