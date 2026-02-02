"""
Event Handler Lambda.

This Lambda function handles events from EventBridge for real-time notifications
and event processing throughout the AI Grocery App.
"""

import json
import os
from datetime import datetime
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
events_client = boto3.client("events")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
ORDERS_TABLE_NAME = os.environ.get("ORDERS_TABLE_NAME", "")


@tracer.capture_method
def handle_order_update(detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle order update events from DynamoDB Streams.
    
    Args:
        detail: Event detail from EventBridge
        
    Returns:
        Processing result
    """
    order_id = detail.get("orderId")
    event_type = detail.get("eventType")
    new_image = detail.get("newImage", {})
    old_image = detail.get("oldImage", {})
    
    logger.info(
        "Processing order update",
        extra={
            "order_id": order_id,
            "event_type": event_type
        }
    )
    
    # Determine the status change
    new_status = new_image.get("status", {}).get("S") if new_image else None
    old_status = old_image.get("status", {}).get("S") if old_image else None
    
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
    
    # Here we would typically:
    # 1. Send notifications via AppSync subscriptions
    # 2. Trigger additional workflows
    # 3. Update analytics/reporting
    
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
def handle_processing_error(detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle processing error events.
    
    Args:
        detail: Event detail from EventBridge
        
    Returns:
        Processing result
    """
    order_id = detail.get("order_id")
    error_message = detail.get("error_message")
    error_stage = detail.get("stage")
    correlation_id = detail.get("correlation_id")
    
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
    
    # Here we would typically:
    # 1. Send error notifications to customers
    # 2. Alert operations team
    # 3. Update order status
    
    return {
        "status": "error_handled",
        "order_id": order_id,
        "error_stage": error_stage
    }


@tracer.capture_method
def handle_payment_event(detail: Dict[str, Any], detail_type: str) -> Dict[str, Any]:
    """
    Handle payment-related events.
    
    Args:
        detail: Event detail from EventBridge
        detail_type: Type of payment event
        
    Returns:
        Processing result
    """
    order_id = detail.get("order_id")
    customer_email = detail.get("customer_email")
    
    logger.info(
        "Payment event received",
        extra={
            "order_id": order_id,
            "event_type": detail_type,
            "customer_email": customer_email
        }
    )
    
    if detail_type == "PaymentLinkCreated":
        metrics.add_metric(name="PaymentLinkNotification", unit="Count", value=1)
        # Send notification about payment link
        # In a real implementation, this would trigger email/SMS
        
    elif detail_type == "PaymentReceived":
        metrics.add_metric(name="PaymentReceived", unit="Count", value=1)
        # Update order status and trigger fulfillment
        
    elif detail_type == "PaymentFailed":
        metrics.add_metric(name="PaymentFailed", unit="Count", value=1)
        # Send failure notification and update order
    
    return {
        "status": "processed",
        "order_id": order_id,
        "event_type": detail_type
    }


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
