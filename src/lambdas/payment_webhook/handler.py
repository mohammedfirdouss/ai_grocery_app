"""
Payment Webhook Handler Lambda.

This Lambda function handles PayStack webhook events for payment status updates.
It validates webhook signatures, processes payment events, and updates order status.
"""

import json
import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
import boto3
from botocore.exceptions import ClientError

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
PAYSTACK_SECRET_ARN = os.environ.get("PAYSTACK_SECRET_ARN", "")

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


def validate_webhook_signature(payload: bytes, signature: str, secret_key: str) -> bool:
    """
    Validate PayStack webhook signature using HMAC SHA-512.
    
    Args:
        payload: Raw webhook request body
        signature: Signature from x-paystack-signature header
        secret_key: PayStack secret key
        
    Returns:
        True if signature is valid
    """
    import hashlib
    import hmac
    
    if not payload or not signature or not secret_key:
        return False
    
    try:
        expected_signature = hmac.new(
            secret_key.encode("utf-8"),
            payload,
            hashlib.sha512
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature.lower(), signature.lower())
    except (TypeError, ValueError):
        return False


@tracer.capture_method
def update_payment_status(order_id: str, status: str, paid_at: Optional[str] = None) -> None:
    """
    Update payment status in the payment links table.
    
    Args:
        order_id: Order ID to update
        status: New payment status
        paid_at: Payment timestamp (optional)
    """
    if not PAYMENT_LINKS_TABLE_NAME:
        logger.warning("PAYMENT_LINKS_TABLE_NAME not configured")
        return
    
    table = dynamodb.Table(PAYMENT_LINKS_TABLE_NAME)
    
    update_expression = "SET #status = :status, updated_at = :updated_at"
    expression_values = {
        ":status": status.upper(),
        ":updated_at": datetime.utcnow().isoformat()
    }
    
    if paid_at:
        update_expression += ", paid_at = :paid_at"
        expression_values[":paid_at"] = paid_at
    
    try:
        table.update_item(
            Key={"order_id": order_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=expression_values
        )
        logger.info("Payment status updated in payment links table", extra={"order_id": order_id, "status": status})
    except ClientError as e:
        logger.error("Failed to update payment status", extra={"error": str(e), "order_id": order_id})
        raise


@tracer.capture_method
def get_order_key(order_id: str) -> Optional[Dict[str, str]]:
    """
    Retrieve order created_at key from payment links table.
    
    Args:
        order_id: Order ID
        
    Returns:
        Dictionary with order_id and created_at, or None if not found
    """
    if not PAYMENT_LINKS_TABLE_NAME:
        return None
    
    table = dynamodb.Table(PAYMENT_LINKS_TABLE_NAME)
    
    try:
        response = table.get_item(Key={"order_id": order_id})
        item = response.get("Item")
        
        if item:
            return {
                "order_id": order_id,
                "created_at": item.get("order_created_at", item.get("created_at", ""))
            }
    except ClientError as e:
        logger.warning("Failed to get order key", extra={"error": str(e), "order_id": order_id})
    
    return None


@tracer.capture_method
def update_order_payment_status(order_id: str, created_at: str, status: str) -> None:
    """
    Update payment status in the orders table.
    
    Args:
        order_id: Order ID
        created_at: Order creation timestamp (sort key)
        status: New payment status
    """
    if not ORDERS_TABLE_NAME:
        logger.warning("ORDERS_TABLE_NAME not configured")
        return
    
    table = dynamodb.Table(ORDERS_TABLE_NAME)
    
    try:
        # Map webhook status to order payment status
        payment_status_map = {
            "success": "PAID",
            "failed": "FAILED",
            "abandoned": "EXPIRED",
            "reversed": "CANCELLED"
        }
        mapped_status = payment_status_map.get(status.lower(), status.upper())
        
        # Update order status to COMPLETED if payment is successful
        order_status = "COMPLETED" if status.lower() == "success" else "PAYMENT_FAILED"
        
        table.update_item(
            Key={"order_id": order_id, "created_at": created_at},
            UpdateExpression="SET payment_status = :payment_status, #status = :order_status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":payment_status": mapped_status,
                ":order_status": order_status,
                ":updated_at": datetime.utcnow().isoformat()
            }
        )
        logger.info("Order payment status updated", extra={"order_id": order_id, "payment_status": mapped_status})
    except ClientError as e:
        logger.error("Failed to update order payment status", extra={"error": str(e), "order_id": order_id})
        raise


@tracer.capture_method
def publish_payment_status_event(
    order_id: str,
    event_type: str,
    status: str,
    amount: Optional[int] = None,
    customer_email: Optional[str] = None
) -> None:
    """
    Publish payment status update event to EventBridge.
    
    Args:
        order_id: Order ID
        event_type: Event type (PaymentReceived, PaymentFailed, etc.)
        status: Payment status
        amount: Payment amount in kobo
        customer_email: Customer email
    """
    detail = {
        "order_id": order_id,
        "status": status,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if amount is not None:
        detail["amount"] = amount / 100  # Convert from kobo to Naira
    
    if customer_email:
        detail["customer_email"] = customer_email
    
    try:
        events_client.put_events(
            Entries=[
                {
                    "Source": "ai-grocery.payments",
                    "DetailType": event_type,
                    "Detail": json.dumps(detail),
                    "EventBusName": f"ai-grocery-events-{ENVIRONMENT}"
                }
            ]
        )
        logger.info("Payment event published", extra={"order_id": order_id, "event_type": event_type})
    except ClientError as e:
        logger.warning("Failed to publish payment event", extra={"error": str(e)})


@tracer.capture_method
def process_charge_success(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a successful charge event.
    
    Args:
        data: Event data from PayStack
        
    Returns:
        Processing result
    """
    reference = data.get("reference", "")
    amount = data.get("amount", 0)
    paid_at = data.get("paid_at")
    customer = data.get("customer", {})
    customer_email = customer.get("email")
    metadata = data.get("metadata", {})
    
    # Extract order ID from reference (format: "order-{order_id}")
    order_id = reference[6:] if reference.startswith("order-") else metadata.get("order_id", reference)
    
    logger.info(
        "Processing successful charge",
        extra={
            "order_id": order_id,
            "reference": reference,
            "amount": amount
        }
    )
    
    # Update payment link status
    update_payment_status(order_id, "SUCCESS", paid_at)
    
    # Get order key and update order status
    order_key = get_order_key(order_id)
    if order_key and order_key.get("created_at"):
        update_order_payment_status(order_id, order_key["created_at"], "success")
    
    # Publish success event
    publish_payment_status_event(
        order_id=order_id,
        event_type="PaymentReceived",
        status="success",
        amount=amount,
        customer_email=customer_email
    )
    
    metrics.add_metric(name="PaymentSuccess", unit="Count", value=1)
    metrics.add_metric(name="PaymentAmount", unit="None", value=amount / 100)
    
    return {
        "status": "processed",
        "order_id": order_id,
        "payment_status": "success"
    }


@tracer.capture_method
def process_charge_failed(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a failed charge event.
    
    Args:
        data: Event data from PayStack
        
    Returns:
        Processing result
    """
    reference = data.get("reference", "")
    amount = data.get("amount", 0)
    customer = data.get("customer", {})
    customer_email = customer.get("email")
    gateway_response = data.get("gateway_response", "Unknown error")
    metadata = data.get("metadata", {})
    
    # Extract order ID
    order_id = reference[6:] if reference.startswith("order-") else metadata.get("order_id", reference)
    
    logger.info(
        "Processing failed charge",
        extra={
            "order_id": order_id,
            "reference": reference,
            "gateway_response": gateway_response
        }
    )
    
    # Update payment link status
    update_payment_status(order_id, "FAILED")
    
    # Get order key and update order status
    order_key = get_order_key(order_id)
    if order_key and order_key.get("created_at"):
        update_order_payment_status(order_id, order_key["created_at"], "failed")
    
    # Publish failure event
    publish_payment_status_event(
        order_id=order_id,
        event_type="PaymentFailed",
        status="failed",
        amount=amount,
        customer_email=customer_email
    )
    
    metrics.add_metric(name="PaymentFailed", unit="Count", value=1)
    
    return {
        "status": "processed",
        "order_id": order_id,
        "payment_status": "failed",
        "failure_reason": gateway_response
    }


@tracer.capture_method
def process_transfer_success(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a successful transfer event (refunds, etc).
    
    Args:
        data: Event data from PayStack
        
    Returns:
        Processing result
    """
    reference = data.get("reference", "")
    amount = data.get("amount", 0)
    
    logger.info(
        "Processing successful transfer",
        extra={
            "reference": reference,
            "amount": amount
        }
    )
    
    metrics.add_metric(name="TransferSuccess", unit="Count", value=1)
    
    return {
        "status": "processed",
        "reference": reference,
        "transfer_status": "success"
    }


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Main Lambda handler for PayStack webhooks.
    
    Validates webhook signatures, processes payment events, and updates
    order and payment status accordingly.
    
    Args:
        event: API Gateway event with PayStack webhook payload
        context: Lambda context
        
    Returns:
        HTTP response with processing result
    """
    logger.info("Received webhook event")
    
    # Extract request data
    headers = event.get("headers", {})
    body = event.get("body", "")
    
    # Handle base64 encoded body (from API Gateway)
    if event.get("isBase64Encoded", False):
        import base64
        body_bytes = base64.b64decode(body)
    else:
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    
    # Get signature from headers (case-insensitive)
    signature = None
    for key, value in headers.items():
        if key.lower() == "x-paystack-signature":
            signature = value
            break
    
    if not signature:
        logger.warning("Missing PayStack signature header")
        metrics.add_metric(name="WebhookInvalidSignature", unit="Count", value=1)
        return {
            "statusCode": 401,
            "body": json.dumps({"error": "Missing signature"})
        }
    
    # Validate webhook signature
    try:
        api_key = get_paystack_api_key()
        if not validate_webhook_signature(body_bytes, signature, api_key):
            logger.warning("Invalid PayStack webhook signature")
            metrics.add_metric(name="WebhookInvalidSignature", unit="Count", value=1)
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "Invalid signature"})
            }
    except Exception as e:
        logger.error("Failed to validate webhook signature", extra={"error": str(e)})
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Signature validation failed"})
        }
    
    # Parse webhook payload
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
        event_type = payload.get("event", "")
        data = payload.get("data", {})
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error("Failed to parse webhook payload", extra={"error": str(e)})
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid payload"})
        }
    
    logger.info("Processing webhook event", extra={"event_type": event_type})
    metrics.add_metric(name="WebhookReceived", unit="Count", value=1)
    
    # Route event to appropriate handler
    try:
        if event_type == "charge.success":
            result = process_charge_success(data)
        elif event_type == "charge.failed":
            result = process_charge_failed(data)
        elif event_type == "transfer.success":
            result = process_transfer_success(data)
        elif event_type == "transfer.failed":
            logger.info("Transfer failed event received", extra={"data": data})
            result = {"status": "acknowledged", "event_type": event_type}
        else:
            logger.info("Unhandled webhook event type", extra={"event_type": event_type})
            result = {"status": "acknowledged", "event_type": event_type}
        
        return {
            "statusCode": 200,
            "body": json.dumps(result)
        }
        
    except Exception as e:
        logger.exception("Error processing webhook", extra={"error": str(e)})
        metrics.add_metric(name="WebhookProcessingError", unit="Count", value=1)
        
        # Still return 200 to acknowledge receipt (PayStack will retry otherwise)
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "error",
                "message": "Processing error - will be retried"
            })
        }
