"""
Payment Processor Lambda Handler.

This Lambda function creates PayStack payment links for matched grocery orders.
It uses the PayStack client for API integration with itemized breakdown support.
"""

import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, batch_processor
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
import boto3
from botocore.exceptions import ClientError

from src.paystack.client import PayStackClient, PayStackError
from src.paystack.models import PayStackPaymentRequest

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
PAYMENT_CALLBACK_BASE_URL = os.environ.get("PAYMENT_CALLBACK_BASE_URL", "https://api.example.com/payment/callback")
PAYMENT_EXPIRATION_HOURS = int(os.environ.get("PAYMENT_EXPIRATION_HOURS", "24"))

# Initialize batch processor
processor = BatchProcessor(event_type=EventType.SQS)

# Cache for PayStack client
_paystack_client: Optional[PayStackClient] = None


@tracer.capture_method
def get_paystack_client() -> PayStackClient:
    """
    Get or create PayStack client with API key from Secrets Manager.
    
    Returns:
        Configured PayStackClient instance
    """
    global _paystack_client
    
    if _paystack_client:
        return _paystack_client
    
    if not PAYSTACK_SECRET_ARN:
        raise ValueError("PAYSTACK_SECRET_ARN not configured")
    
    try:
        response = secrets_client.get_secret_value(SecretId=PAYSTACK_SECRET_ARN)
        secret_data = json.loads(response["SecretString"])
        api_key = secret_data.get("api_key", "")
        
        if not api_key:
            raise ValueError("PayStack API key not found in secret")
        
        _paystack_client = PayStackClient(
            api_key=api_key,
            base_url=PAYSTACK_BASE_URL,
            expiration_hours=PAYMENT_EXPIRATION_HOURS
        )
        return _paystack_client
        
    except ClientError as e:
        logger.error("Failed to retrieve PayStack API key", extra={"error": str(e)})
        raise


@tracer.capture_method
def create_payment_link_with_retry(
    order_id: str,
    customer_email: str,
    customer_name: Optional[str],
    items: List[Dict[str, Any]],
    total_amount: float,
    max_retries: int = 3
) -> Dict[str, Any]:
    """
    Create PayStack payment link with itemized breakdown and exponential backoff retry.
    
    Args:
        order_id: Unique order identifier
        customer_email: Customer's email address
        customer_name: Customer's name (optional)
        items: List of matched items with product details
        total_amount: Total order amount in Naira
        max_retries: Maximum retry attempts
        
    Returns:
        PayStack payment link response with authorization URL, access code, etc.
        
    Raises:
        PayStackError: If payment initialization fails after all retries
    """
    client = get_paystack_client()
    
    # Build callback URL
    callback_url = f"{PAYMENT_CALLBACK_BASE_URL}/{order_id}"
    
    # Create payment request with itemized breakdown
    payment_request = PayStackPaymentRequest.from_order(
        order_id=order_id,
        customer_email=customer_email,
        customer_name=customer_name,
        matched_items=items,
        total_amount=total_amount,
        callback_url=callback_url
    )
    
    logger.info(
        "Creating payment link with itemized breakdown",
        extra={
            "order_id": order_id,
            "item_count": len(items),
            "total_amount": total_amount
        }
    )
    
    # Initialize payment using PayStack client (has built-in retry)
    response = client.initialize_payment(payment_request)
    
    if response.success:
        return {
            "success": True,
            "authorization_url": response.authorization_url,
            "access_code": response.access_code,
            "reference": response.reference,
            "expires_at": response.expires_at.isoformat() if response.expires_at else None
        }
    else:
        raise PayStackError(
            message=response.message or "Payment initialization failed",
            error_code=response.error_code
        )


@tracer.capture_method
def store_payment_link(
    order_id: str,
    payment_data: Dict[str, Any],
    customer_email: str,
    total_amount: float,
    order_created_at: Optional[str] = None,
    matched_items: Optional[List[Dict[str, Any]]] = None
) -> None:
    """
    Store payment link in DynamoDB with TTL and itemized breakdown.
    
    Args:
        order_id: Order identifier
        payment_data: PayStack payment response data
        customer_email: Customer's email address
        total_amount: Total amount in Naira
        order_created_at: Original order creation timestamp
        matched_items: List of matched items for itemized storage
    """
    table = dynamodb.Table(PAYMENT_LINKS_TABLE_NAME)
    
    # Calculate TTL based on configured expiration hours
    expires_at = int((datetime.utcnow() + timedelta(hours=PAYMENT_EXPIRATION_HOURS)).timestamp())
    
    item = {
        "order_id": order_id,
        "payment_link": payment_data["authorization_url"],
        "access_code": payment_data["access_code"],
        "reference": payment_data["reference"],
        "customer_email": customer_email,
        "amount": Decimal(str(total_amount)),
        "currency": "NGN",
        "status": "PENDING",
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": expires_at,
        "expiration_hours": PAYMENT_EXPIRATION_HOURS
    }
    
    # Store order creation timestamp for later reference
    if order_created_at:
        item["order_created_at"] = order_created_at
    
    # Store itemized breakdown for reference
    if matched_items:
        item["item_count"] = len(matched_items)
        # Store a summary of items (not the full details to save space)
        item["items_summary"] = [
            {
                "name": i.get("product_name", i.get("name", "Unknown"))[:100],
                "quantity": i.get("quantity", 1),
                "unit_price": str(i.get("unit_price", 0))
            }
            for i in matched_items[:20]  # Limit to first 20 items
        ]
    
    table.put_item(Item=item)
    
    logger.info(
        "Stored payment link in DynamoDB",
        extra={
            "order_id": order_id,
            "expires_at": expires_at,
            "item_count": len(matched_items) if matched_items else 0
        }
    )


@tracer.capture_method
def update_order_with_payment(
    order_id: str,
    created_at: str,
    payment_link: str,
    payment_reference: Optional[str] = None
) -> None:
    """
    Update order in DynamoDB with payment link and status.
    
    Args:
        order_id: Order identifier
        created_at: Order creation timestamp (sort key)
        payment_link: PayStack authorization URL
        payment_reference: PayStack transaction reference
    """
    table = dynamodb.Table(ORDERS_TABLE_NAME)
    
    update_expression = "SET #status = :status, payment_link = :link, payment_status = :payment_status, updated_at = :updated_at"
    expression_values = {
        ":status": "PAYMENT_LINK_CREATED",
        ":link": payment_link,
        ":payment_status": "PENDING",
        ":updated_at": datetime.utcnow().isoformat()
    }
    
    if payment_reference:
        update_expression += ", payment_reference = :payment_reference"
        expression_values[":payment_reference"] = payment_reference
    
    table.update_item(
        Key={"order_id": order_id, "created_at": created_at},
        UpdateExpression=update_expression,
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues=expression_values
    )
    
    logger.info(
        "Updated order with payment link",
        extra={"order_id": order_id, "payment_status": "PENDING"}
    )


@tracer.capture_method
def publish_payment_event(
    order_id: str,
    payment_link: str,
    customer_email: str,
    total_amount: Optional[float] = None,
    item_count: Optional[int] = None
) -> None:
    """
    Publish payment link created event to EventBridge.
    
    Args:
        order_id: Order identifier
        payment_link: PayStack authorization URL
        customer_email: Customer's email address
        total_amount: Total payment amount
        item_count: Number of items in order
    """
    detail = {
        "order_id": order_id,
        "payment_link": payment_link,
        "customer_email": customer_email,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if total_amount is not None:
        detail["amount"] = total_amount
    
    if item_count is not None:
        detail["item_count"] = item_count
    
    try:
        events_client.put_events(
            Entries=[
                {
                    "Source": "ai-grocery.payments",
                    "DetailType": "PaymentLinkCreated",
                    "Detail": json.dumps(detail),
                    "EventBusName": f"ai-grocery-events-{ENVIRONMENT}"
                }
            ]
        )
        logger.info("Published payment link created event", extra={"order_id": order_id})
    except ClientError as e:
        logger.warning("Failed to publish event", extra={"error": str(e)})


def record_handler(record: SQSRecord) -> Dict[str, Any]:
    """
    Process individual SQS record for payment link creation.
    
    Args:
        record: SQS record containing order data
        
    Returns:
        Processing result with status and payment link
    """
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
        # Validate required fields
        if not customer_email:
            raise ValueError("Customer email is required")
        
        # Validate total amount
        if total_amount <= 0:
            logger.warning("Order has zero total amount", extra={"order_id": order_id})
            # Still create a record but mark as no payment needed
            if ORDERS_TABLE_NAME and created_at:
                update_order_with_payment(order_id, created_at, "NO_PAYMENT_REQUIRED")
            return {"status": "skipped", "order_id": order_id, "reason": "zero_amount"}
        
        # Create PayStack payment link with itemized breakdown
        payment_data = create_payment_link_with_retry(
            order_id=order_id,
            customer_email=customer_email,
            customer_name=customer_name,
            items=matched_items,
            total_amount=total_amount
        )
        
        # Store payment link with itemized breakdown
        if PAYMENT_LINKS_TABLE_NAME:
            store_payment_link(
                order_id=order_id,
                payment_data=payment_data,
                customer_email=customer_email,
                total_amount=total_amount,
                order_created_at=created_at,
                matched_items=matched_items
            )
        
        # Update order with payment link and reference
        if ORDERS_TABLE_NAME and created_at:
            update_order_with_payment(
                order_id=order_id,
                created_at=created_at,
                payment_link=payment_data["authorization_url"],
                payment_reference=payment_data.get("reference")
            )
        
        # Publish event with additional details
        publish_payment_event(
            order_id=order_id,
            payment_link=payment_data["authorization_url"],
            customer_email=customer_email,
            total_amount=total_amount,
            item_count=len(matched_items)
        )
        
        metrics.add_metric(name="PaymentLinkCreated", unit="Count", value=1)
        metrics.add_metric(name="PaymentAmount", unit="None", value=total_amount)
        
        logger.info(
            "Successfully created payment link with itemized breakdown",
            extra={
                "order_id": order_id,
                "amount": total_amount,
                "item_count": len(matched_items),
                "expires_at": payment_data.get("expires_at")
            }
        )
        
        return {
            "status": "success",
            "order_id": order_id,
            "payment_link": payment_data["authorization_url"],
            "reference": payment_data.get("reference"),
            "expires_at": payment_data.get("expires_at")
        }
        
    except PayStackError as e:
        metrics.add_metric(name="PaymentLinkError", unit="Count", value=1)
        logger.error(
            "PayStack error creating payment link",
            extra={"order_id": order_id, "error": str(e), "error_code": e.error_code}
        )
        raise
        
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
