"""
Event Handler Lambda.

This Lambda function handles events from EventBridge for real-time notifications
and event processing throughout the AI Grocery App. It provides:

- Real-time notification publishing via AppSync subscriptions
- Event transformation and filtering for DynamoDB Stream events
- Connection state management for subscription clients
- Error notification broadcasting for processing failures
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional, List
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
import boto3
from botocore.exceptions import ClientError

from appsync_client import get_appsync_client, AppSyncClient

# Initialize AWS Lambda Powertools
logger = Logger()
tracer = Tracer()
metrics = Metrics()

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")
events_client = boto3.client("events")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
ORDERS_TABLE_NAME = os.environ.get("ORDERS_TABLE_NAME", "")
APPSYNC_API_URL = os.environ.get("APPSYNC_API_URL", "")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", f"ai-grocery-events-{ENVIRONMENT}")

# Connection state tracking (in-memory for Lambda execution context)
# In production, this would be stored in DynamoDB or ElastiCache
_connection_states: Dict[str, Dict[str, Any]] = {}


@tracer.capture_method
def extract_dynamodb_value(item: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Extract a value from a DynamoDB item image.
    
    Args:
        item: DynamoDB item (new or old image)
        key: Attribute key to extract
        default: Default value if key not found
        
    Returns:
        Extracted value or default
    """
    if not item or key not in item:
        return default
    
    attr = item[key]
    if "S" in attr:
        return attr["S"]
    elif "N" in attr:
        return float(attr["N"]) if "." in attr["N"] else int(attr["N"])
    elif "BOOL" in attr:
        return attr["BOOL"]
    elif "NULL" in attr:
        return None
    elif "L" in attr:
        return [extract_dynamodb_value({"v": v}, "v") for v in attr["L"]]
    elif "M" in attr:
        return {k: extract_dynamodb_value(v, k) for k, v in attr["M"].items()}
    
    return default


@tracer.capture_method
def transform_order_event(detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform DynamoDB Stream event to a normalized order event.
    
    Args:
        detail: Raw event detail from EventBridge Pipe
        
    Returns:
        Transformed event data with extracted fields
    """
    new_image = detail.get("newImage", {})
    old_image = detail.get("oldImage", {})
    
    return {
        "orderId": detail.get("orderId"),
        "eventType": detail.get("eventType"),
        "newStatus": extract_dynamodb_value(new_image, "status"),
        "oldStatus": extract_dynamodb_value(old_image, "status"),
        "customerEmail": extract_dynamodb_value(new_image, "customer_email"),
        "customerName": extract_dynamodb_value(new_image, "customer_name"),
        "correlationId": extract_dynamodb_value(new_image, "correlation_id"),
        "totalAmount": extract_dynamodb_value(new_image, "total_amount"),
        "paymentStatus": extract_dynamodb_value(new_image, "payment_status"),
        "paymentLink": extract_dynamodb_value(new_image, "payment_link"),
        "processingDuration": extract_dynamodb_value(new_image, "processing_duration"),
        "errorDetails": extract_dynamodb_value(new_image, "error_details"),
        "createdAt": extract_dynamodb_value(new_image, "created_at"),
        "updatedAt": extract_dynamodb_value(new_image, "updated_at")
    }


@tracer.capture_method
def should_publish_notification(transformed: Dict[str, Any]) -> bool:
    """
    Determine if a notification should be published based on event filtering rules.
    
    Args:
        transformed: Transformed event data
        
    Returns:
        True if notification should be published, False otherwise
    """
    event_type = transformed.get("eventType")
    old_status = transformed.get("oldStatus")
    new_status = transformed.get("newStatus")
    
    # Always publish for INSERT events (new orders)
    if event_type == "INSERT":
        return True
    
    # For MODIFY events, only publish if status changed
    if event_type == "MODIFY":
        if old_status != new_status:
            return True
        # Also publish if payment status changed
        # (This would need additional tracking in a real implementation)
        return False
    
    # Publish for REMOVE events (order cancellations)
    if event_type == "REMOVE":
        return True
    
    return False


@tracer.capture_method
def handle_order_update(detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle order update events from DynamoDB Streams.
    
    Transforms events, applies filtering, and publishes real-time notifications
    via AppSync subscriptions.
    
    Args:
        detail: Event detail from EventBridge
        
    Returns:
        Processing result
    """
    order_id = detail.get("orderId")
    event_type = detail.get("eventType")
    
    logger.info(
        "Processing order update",
        extra={
            "order_id": order_id,
            "event_type": event_type
        }
    )
    
    # Transform the event for easier processing
    transformed = transform_order_event(detail)
    
    # Determine the status change
    new_status = transformed.get("newStatus")
    old_status = transformed.get("oldStatus")
    customer_email = transformed.get("customerEmail", "")
    correlation_id = transformed.get("correlationId", "")
    
    notification_published = False
    
    if new_status != old_status:
        logger.info(
            "Order status changed",
            extra={
                "order_id": order_id,
                "old_status": old_status,
                "new_status": new_status
            }
        )
        
        # Emit metrics for status transitions
        metrics.add_metric(
            name=f"OrderStatus_{new_status}",
            unit="Count",
            value=1
        )
        
        # Publish real-time notification via AppSync
        if should_publish_notification(transformed) and APPSYNC_API_URL:
            try:
                appsync_client = get_appsync_client()
                notification_published = appsync_client.publish_order_update(
                    order_id=order_id,
                    status=new_status,
                    customer_email=customer_email,
                    correlation_id=correlation_id,
                    additional_data={
                        "totalAmount": transformed.get("totalAmount"),
                        "paymentStatus": transformed.get("paymentStatus"),
                        "paymentLink": transformed.get("paymentLink")
                    }
                )
                
                # Also publish processing event for detailed tracking
                appsync_client.publish_processing_event(
                    order_id=order_id,
                    event_type=f"STATUS_CHANGED_{event_type}",
                    status=new_status,
                    message=f"Order status changed from {old_status} to {new_status}",
                    correlation_id=correlation_id,
                    data={
                        "oldStatus": old_status,
                        "processingDuration": transformed.get("processingDuration")
                    }
                )
                
                if notification_published:
                    metrics.add_metric(name="NotificationPublished", unit="Count", value=1)
                else:
                    metrics.add_metric(name="NotificationFailed", unit="Count", value=1)
                    
            except Exception as e:
                logger.exception(
                    "Failed to publish notification",
                    extra={"order_id": order_id, "error": str(e)}
                )
                metrics.add_metric(name="NotificationError", unit="Count", value=1)
        
        # Handle error notifications specifically
        if new_status == "FAILED" and transformed.get("errorDetails"):
            _handle_processing_failure(order_id, transformed, correlation_id)
    
    return {
        "status": "processed",
        "order_id": order_id,
        "event_type": event_type,
        "status_change": {
            "from": old_status,
            "to": new_status
        }
    }


@tracer.capture_method
def _handle_processing_failure(
    order_id: str,
    transformed: Dict[str, Any],
    correlation_id: str
) -> None:
    """
    Handle processing failure by broadcasting error notifications.
    
    Args:
        order_id: The order ID
        transformed: Transformed event data
        correlation_id: Correlation ID for tracing
    """
    error_details = transformed.get("errorDetails", "Unknown error")
    
    if APPSYNC_API_URL:
        try:
            appsync_client = get_appsync_client()
            appsync_client.broadcast_error_notification(
                order_id=order_id,
                error_type="PROCESSING_FAILED",
                error_message=error_details,
                error_stage="PROCESSING",
                correlation_id=correlation_id,
                is_retryable=False
            )
            metrics.add_metric(name="ErrorNotificationBroadcast", unit="Count", value=1)
        except Exception as e:
            logger.exception(
                "Failed to broadcast error notification",
                extra={"order_id": order_id, "error": str(e)}
            )


@tracer.capture_method
def handle_processing_error(detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle processing error events.
    
    Broadcasts error notifications to subscribed clients via AppSync.
    
    Args:
        detail: Event detail from EventBridge
        
    Returns:
        Processing result
    """
    order_id = detail.get("order_id")
    error_message = detail.get("error_message")
    error_stage = detail.get("stage")
    correlation_id = detail.get("correlation_id")
    is_retryable = detail.get("is_retryable", False)
    
    logger.error(
        "Processing error event received",
        extra={
            "order_id": order_id,
            "error_message": error_message,
            "stage": error_stage,
            "correlation_id": correlation_id
        }
    )
    
    # Record error metrics
    metrics.add_metric(name="ProcessingErrorReceived", unit="Count", value=1)
    metrics.add_metadata(key="error_stage", value=error_stage or "unknown")
    
    # Broadcast error notification via AppSync
    notification_sent = False
    if APPSYNC_API_URL and order_id:
        try:
            appsync_client = get_appsync_client()
            notification_sent = appsync_client.broadcast_error_notification(
                order_id=order_id,
                error_type="PROCESSING_ERROR",
                error_message=error_message or "An error occurred during processing",
                error_stage=error_stage or "UNKNOWN",
                correlation_id=correlation_id or "",
                is_retryable=is_retryable
            )
            
            if notification_sent:
                metrics.add_metric(name="ErrorNotificationSent", unit="Count", value=1)
            else:
                metrics.add_metric(name="ErrorNotificationFailed", unit="Count", value=1)
                
        except Exception as e:
            logger.exception(
                "Failed to send error notification",
                extra={"order_id": order_id, "error": str(e)}
            )
            metrics.add_metric(name="ErrorNotificationException", unit="Count", value=1)
    
    return {
        "status": "error_handled",
        "order_id": order_id,
        "error_stage": error_stage,
        "notification_sent": notification_sent
    }


@tracer.capture_method
def handle_payment_event(detail: Dict[str, Any], detail_type: str) -> Dict[str, Any]:
    """
    Handle payment-related events.
    
    Publishes payment status notifications via AppSync subscriptions.
    
    Args:
        detail: Event detail from EventBridge
        detail_type: Type of payment event
        
    Returns:
        Processing result
    """
    order_id = detail.get("order_id")
    customer_email = detail.get("customer_email")
    payment_url = detail.get("payment_url")
    amount = detail.get("amount")
    currency = detail.get("currency", "NGN")
    
    logger.info(
        "Payment event received",
        extra={
            "order_id": order_id,
            "event_type": detail_type,
            "customer_email": customer_email
        }
    )
    
    notification_sent = False
    payment_status = None
    
    if detail_type == "PaymentLinkCreated":
        metrics.add_metric(name="PaymentLinkNotification", unit="Count", value=1)
        payment_status = "PENDING"
        
    elif detail_type == "PaymentReceived":
        metrics.add_metric(name="PaymentReceived", unit="Count", value=1)
        payment_status = "PAID"
        
    elif detail_type == "PaymentFailed":
        metrics.add_metric(name="PaymentFailed", unit="Count", value=1)
        payment_status = "FAILED"
    
    # Publish payment status notification via AppSync
    if APPSYNC_API_URL and order_id and payment_status:
        try:
            appsync_client = get_appsync_client()
            notification_sent = appsync_client.publish_payment_status(
                order_id=order_id,
                status=payment_status,
                payment_url=payment_url,
                amount=amount,
                currency=currency
            )
            
            if notification_sent:
                metrics.add_metric(name="PaymentNotificationSent", unit="Count", value=1)
            else:
                metrics.add_metric(name="PaymentNotificationFailed", unit="Count", value=1)
                
        except Exception as e:
            logger.exception(
                "Failed to send payment notification",
                extra={"order_id": order_id, "error": str(e)}
            )
            metrics.add_metric(name="PaymentNotificationException", unit="Count", value=1)
    
    return {
        "status": "processed",
        "order_id": order_id,
        "event_type": detail_type,
        "notification_sent": notification_sent
    }


@tracer.capture_method
def track_connection_state(
    connection_id: str,
    order_id: str,
    state: str,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Track subscription connection state.
    
    Note: In production, this would be stored in DynamoDB or ElastiCache
    for persistence across Lambda invocations.
    
    Args:
        connection_id: WebSocket connection ID
        order_id: Associated order ID
        state: Connection state (CONNECTED, DISCONNECTED, SUBSCRIBED)
        metadata: Additional metadata
    """
    global _connection_states
    
    if state == "DISCONNECTED":
        if connection_id in _connection_states:
            del _connection_states[connection_id]
        logger.info(
            "Connection removed",
            extra={"connection_id": connection_id, "order_id": order_id}
        )
    else:
        _connection_states[connection_id] = {
            "order_id": order_id,
            "state": state,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        logger.info(
            "Connection state updated",
            extra={
                "connection_id": connection_id,
                "order_id": order_id,
                "state": state
            }
        )
        
    metrics.add_metric(name=f"ConnectionState_{state}", unit="Count", value=1)


@tracer.capture_method
def get_active_connections(order_id: str) -> List[str]:
    """
    Get active subscription connections for an order.
    
    Args:
        order_id: The order ID
        
    Returns:
        List of active connection IDs
    """
    global _connection_states
    
    return [
        conn_id for conn_id, state in _connection_states.items()
        if state.get("order_id") == order_id and state.get("state") == "SUBSCRIBED"
    ]


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Main Lambda handler for EventBridge events.
    
    Routes events to appropriate handlers based on source and detail type.
    """
    source = event.get("source", "")
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})
    
    logger.info(
        "Received EventBridge event",
        extra={
            "source": source,
            "detail_type": detail_type
        }
    )
    
    try:
        # Route based on source
        if source == "ai-grocery.orders":
            result = handle_order_update(detail)
            
        elif source == "ai-grocery.processing":
            result = handle_processing_error(detail)
            
        elif source == "ai-grocery.payments":
            result = handle_payment_event(detail, detail_type)
            
        else:
            logger.warning(
                "Unknown event source",
                extra={"source": source, "detail_type": detail_type}
            )
            result = {
                "status": "unhandled",
                "source": source,
                "detail_type": detail_type
            }
        
        return {
            "statusCode": 200,
            "body": json.dumps(result)
        }
        
    except Exception as e:
        logger.exception("Error processing event", extra={"error": str(e)})
        metrics.add_metric(name="EventHandlerError", unit="Count", value=1)
        
        return {
            "statusCode": 500,
            "body": json.dumps({
                "status": "error",
                "error": str(e)
            })
        }
