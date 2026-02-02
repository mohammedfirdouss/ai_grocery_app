"""
Text Parser Lambda Handler.

This Lambda function processes incoming grocery list text from SQS,
validates and normalizes the input, and forwards it to the Product Matcher queue.
"""

import json
import os
from typing import Any, Dict
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, batch_processor
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
import boto3

# Initialize AWS Lambda Powertools
logger = Logger()
tracer = Tracer()
metrics = Metrics()

# Initialize AWS clients
sqs_client = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
ORDERS_TABLE_NAME = os.environ.get("ORDERS_TABLE_NAME", "")
PRODUCT_MATCHER_QUEUE_URL = os.environ.get("PRODUCT_MATCHER_QUEUE_URL", "")

# Initialize batch processor
processor = BatchProcessor(event_type=EventType.SQS)


@tracer.capture_method
def process_text(text: str, order_id: str) -> Dict[str, Any]:
    """
    Process and validate grocery list text.
    
    Args:
        text: Raw grocery list text from user
        order_id: Unique order identifier
        
    Returns:
        Processed text data with metadata
    """
    # Basic text normalization
    processed_text = text.strip()
    
    # Validate input
    if not processed_text:
        raise ValueError("Empty grocery list text provided")
    
    if len(processed_text) > 10000:
        raise ValueError("Grocery list text exceeds maximum length")
    
    # Create processed output
    return {
        "order_id": order_id,
        "processed_text": processed_text,
        "text_length": len(processed_text),
        "line_count": len(processed_text.split("\n")),
    }


@tracer.capture_method
def update_order_status(order_id: str, status: str, created_at: str) -> None:
    """Update order status in DynamoDB."""
    table = dynamodb.Table(ORDERS_TABLE_NAME)
    table.update_item(
        Key={"order_id": order_id, "created_at": created_at},
        UpdateExpression="SET #status = :status",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": status}
    )


@tracer.capture_method
def send_to_product_matcher(payload: Dict[str, Any]) -> None:
    """Send processed text to Product Matcher queue."""
    sqs_client.send_message(
        QueueUrl=PRODUCT_MATCHER_QUEUE_URL,
        MessageBody=json.dumps(payload),
        MessageAttributes={
            "CorrelationId": {
                "DataType": "String",
                "StringValue": payload.get("correlation_id", "unknown")
            }
        }
    )


def record_handler(record: SQSRecord) -> Dict[str, Any]:
    """Process individual SQS record."""
    logger.info("Processing SQS record", extra={"message_id": record.message_id})
    
    # Parse message body
    body = json.loads(record.body)
    order_id = body.get("order_id")
    raw_text = body.get("raw_text")
    correlation_id = body.get("correlation_id", record.message_id)
    created_at = body.get("created_at")
    
    logger.append_keys(
        order_id=order_id,
        correlation_id=correlation_id
    )
    
    try:
        # Process the text
        processed_data = process_text(raw_text, order_id)
        processed_data["correlation_id"] = correlation_id
        processed_data["customer_email"] = body.get("customer_email")
        processed_data["customer_name"] = body.get("customer_name")
        processed_data["created_at"] = created_at
        
        # Update order status
        if ORDERS_TABLE_NAME and created_at:
            update_order_status(order_id, "PARSING_COMPLETE", created_at)
        
        # Send to Product Matcher
        if PRODUCT_MATCHER_QUEUE_URL:
            send_to_product_matcher(processed_data)
        
        metrics.add_metric(name="TextParsingSuccess", unit="Count", value=1)
        logger.info("Successfully processed text", extra={"order_id": order_id})
        
        return {"status": "success", "order_id": order_id}
        
    except Exception as e:
        metrics.add_metric(name="TextParsingError", unit="Count", value=1)
        logger.exception("Error processing text", extra={"order_id": order_id, "error": str(e)})
        raise


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
@batch_processor(record_handler=record_handler, processor=processor)
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Main Lambda handler for text parsing.
    
    Processes SQS messages containing grocery list text,
    validates and normalizes the input, and forwards to Product Matcher.
    """
    return processor.response()
