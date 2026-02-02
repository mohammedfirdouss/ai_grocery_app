"""
Text Parser Lambda Handler.

This Lambda function processes incoming grocery list text from SQS,
validates and normalizes the input, and forwards it to the Product Matcher queue.
"""

import json
import os
import re
import unicodedata
from typing import Any, Dict, Optional
from uuid import uuid4
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, batch_processor
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from botocore.exceptions import ClientError
import boto3

# Initialize AWS Lambda Powertools
logger = Logger(service="text-parser")
tracer = Tracer(service="text-parser")
metrics = Metrics(namespace="AIGroceryApp", service="text-parser")

# Initialize AWS clients
sqs_client = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
ORDERS_TABLE_NAME = os.environ.get("ORDERS_TABLE_NAME", "")
PRODUCT_MATCHER_QUEUE_URL = os.environ.get("PRODUCT_MATCHER_QUEUE_URL", "")

# Configuration constants
MAX_TEXT_LENGTH = 10000
MIN_TEXT_LENGTH = 1
MAX_LINE_COUNT = 500

# Initialize batch processor
processor = BatchProcessor(event_type=EventType.SQS)


class TextValidationError(Exception):
    """Custom exception for text validation errors."""
    pass


class ProcessingError(Exception):
    """Custom exception for processing errors."""
    pass


def generate_correlation_id() -> str:
    """
    Generate a unique correlation ID for request tracing.
    
    Returns:
        UUID string for correlation tracking
    """
    return str(uuid4())


@tracer.capture_method
def sanitize_text(text: str) -> str:
    """
    Sanitize and normalize input text.
    
    Performs the following operations:
    - Normalizes Unicode characters to NFKC form
    - Removes control characters except newlines and tabs
    - Normalizes whitespace
    - Removes null bytes
    - Normalizes line endings to \n
    
    Args:
        text: Raw input text
        
    Returns:
        Sanitized text
    """
    if not isinstance(text, str):
        raise TextValidationError(f"Text must be a string, got {type(text).__name__}")
    
    # Normalize Unicode to NFKC form (compatibility composition)
    text = unicodedata.normalize('NFKC', text)
    
    # Remove null bytes
    text = text.replace('\x00', '')
    
    # Normalize line endings to \n
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # Remove control characters except newline and tab
    text = ''.join(char for char in text if char in '\n\t' or not unicodedata.category(char).startswith('C'))
    
    # Normalize excessive whitespace
    # Replace multiple spaces with single space, but preserve newlines
    lines = text.split('\n')
    normalized_lines = [' '.join(line.split()) for line in lines]
    text = '\n'.join(normalized_lines)
    
    # Remove excessive consecutive newlines (max 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    return text


@tracer.capture_method
def validate_text(text: str, correlation_id: str) -> None:
    """
    Validate grocery list text against business rules.
    
    Args:
        text: Sanitized text to validate
        correlation_id: Correlation ID for logging
        
    Raises:
        TextValidationError: If validation fails
    """
    # Check if text is empty
    if not text:
        logger.warning(
            "Empty text after sanitization",
            extra={"correlation_id": correlation_id}
        )
        raise TextValidationError("Empty grocery list text provided")
    
    # Check minimum length
    if len(text) < MIN_TEXT_LENGTH:
        logger.warning(
            "Text too short",
            extra={
                "correlation_id": correlation_id,
                "text_length": len(text),
                "min_length": MIN_TEXT_LENGTH
            }
        )
        raise TextValidationError(f"Grocery list text must be at least {MIN_TEXT_LENGTH} character(s)")
    
    # Check maximum length
    if len(text) > MAX_TEXT_LENGTH:
        logger.warning(
            "Text exceeds maximum length",
            extra={
                "correlation_id": correlation_id,
                "text_length": len(text),
                "max_length": MAX_TEXT_LENGTH
            }
        )
        raise TextValidationError(f"Grocery list text exceeds maximum length of {MAX_TEXT_LENGTH} characters")
    
    # Count lines
    line_count = len(text.split('\n'))
    if line_count > MAX_LINE_COUNT:
        logger.warning(
            "Text exceeds maximum line count",
            extra={
                "correlation_id": correlation_id,
                "line_count": line_count,
                "max_lines": MAX_LINE_COUNT
            }
        )
        raise TextValidationError(f"Grocery list exceeds maximum of {MAX_LINE_COUNT} lines")
    
    # Check for suspicious patterns (e.g., potential injection attempts)
    suspicious_patterns = [
        r'<script[^>]*>',  # Script tags
        r'javascript:',     # JavaScript protocol
        r'on\w+\s*=',      # Event handlers
        r'data:text/html', # Data URIs
    ]
    
    for pattern in suspicious_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(
                "Suspicious pattern detected in text",
                extra={
                    "correlation_id": correlation_id,
                    "pattern": pattern
                }
            )
            raise TextValidationError("Invalid characters or patterns detected in grocery list")
    
    logger.info(
        "Text validation successful",
        extra={
            "correlation_id": correlation_id,
            "text_length": len(text),
            "line_count": line_count
        }
    )


@tracer.capture_method
def process_text(text: str, order_id: str, correlation_id: str) -> Dict[str, Any]:
    """
    Process and validate grocery list text.
    
    Args:
        text: Raw grocery list text from user
        order_id: Unique order identifier
        correlation_id: Correlation ID for tracing
        
    Returns:
        Processed text data with metadata
        
    Raises:
        TextValidationError: If text validation fails
    """
    logger.info(
        "Starting text processing",
        extra={
            "order_id": order_id,
            "correlation_id": correlation_id,
            "raw_text_length": len(text) if isinstance(text, str) else 0
        }
    )
    
    # Sanitize input
    try:
        sanitized_text = sanitize_text(text)
        logger.debug(
            "Text sanitization complete",
            extra={
                "order_id": order_id,
                "correlation_id": correlation_id,
                "sanitized_length": len(sanitized_text)
            }
        )
    except TextValidationError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        logger.error(
            "Text sanitization failed",
            extra={
                "order_id": order_id,
                "correlation_id": correlation_id,
                "error": str(e)
            }
        )
        raise TextValidationError(f"Failed to sanitize text: {str(e)}")
    
    # Validate sanitized text
    validate_text(sanitized_text, correlation_id)
    
    # Extract text metadata
    lines = sanitized_text.split('\n')
    line_count = len(lines)
    non_empty_lines = [line for line in lines if line.strip()]
    
    # Create processed output
    processed_data = {
        "order_id": order_id,
        "processed_text": sanitized_text,
        "text_length": len(sanitized_text),
        "line_count": line_count,
        "non_empty_line_count": len(non_empty_lines),
        "average_line_length": sum(len(line) for line in non_empty_lines) / len(non_empty_lines) if non_empty_lines else 0
    }
    
    logger.info(
        "Text processing complete",
        extra={
            "order_id": order_id,
            "correlation_id": correlation_id,
            **processed_data
        }
    )
    
    metrics.add_metric(name="TextLength", unit="Count", value=len(sanitized_text))
    metrics.add_metric(name="LineCount", unit="Count", value=line_count)
    
    return processed_data


@tracer.capture_method
def update_order_status(
    order_id: str,
    status: str,
    created_at: str,
    correlation_id: str,
    additional_attributes: Optional[Dict[str, Any]] = None
) -> None:
    """
    Update order status in DynamoDB with retry logic.
    
    Args:
        order_id: Order identifier
        status: New status value
        created_at: Order creation timestamp
        correlation_id: Correlation ID for tracing
        additional_attributes: Optional additional attributes to update
        
    Raises:
        ProcessingError: If DynamoDB update fails after retries
    """
    if not ORDERS_TABLE_NAME:
        logger.warning(
            "ORDERS_TABLE_NAME not configured, skipping status update",
            extra={
                "order_id": order_id,
                "correlation_id": correlation_id
            }
        )
        return
    
    table = dynamodb.Table(ORDERS_TABLE_NAME)
    
    # Build update expression
    update_parts = ["#status = :status", "updated_at = :updated_at"]
    attr_names = {"#status": "status"}
    attr_values = {
        ":status": status,
        ":updated_at": int(os.environ.get("_X_AMZN_TRACE_ID", "0").split("=")[-1].split("-")[0] or "0") or 0
    }
    
    # Add additional attributes if provided
    if additional_attributes:
        for key, value in additional_attributes.items():
            placeholder = f":attr_{key}"
            update_parts.append(f"{key} = {placeholder}")
            attr_values[placeholder] = value
    
    update_expression = "SET " + ", ".join(update_parts)
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.debug(
                "Updating order status",
                extra={
                    "order_id": order_id,
                    "correlation_id": correlation_id,
                    "status": status,
                    "attempt": attempt + 1
                }
            )
            
            table.update_item(
                Key={"order_id": order_id, "created_at": created_at},
                UpdateExpression=update_expression,
                ExpressionAttributeNames=attr_names,
                ExpressionAttributeValues=attr_values
            )
            
            logger.info(
                "Order status updated successfully",
                extra={
                    "order_id": order_id,
                    "correlation_id": correlation_id,
                    "status": status
                }
            )
            metrics.add_metric(name="OrderStatusUpdateSuccess", unit="Count", value=1)
            return
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.warning(
                "DynamoDB update attempt failed",
                extra={
                    "order_id": order_id,
                    "correlation_id": correlation_id,
                    "error_code": error_code,
                    "attempt": attempt + 1,
                    "max_retries": max_retries
                }
            )
            
            if attempt == max_retries - 1:
                logger.error(
                    "Failed to update order status after all retries",
                    extra={
                        "order_id": order_id,
                        "correlation_id": correlation_id,
                        "error": str(e)
                    }
                )
                metrics.add_metric(name="OrderStatusUpdateFailure", unit="Count", value=1)
                raise ProcessingError(f"Failed to update order status: {str(e)}")


@tracer.capture_method
def send_to_product_matcher(payload: Dict[str, Any], correlation_id: str) -> None:
    """
    Send processed text to Product Matcher queue with retry logic.
    
    Args:
        payload: Message payload to send
        correlation_id: Correlation ID for tracing
        
    Raises:
        ProcessingError: If SQS send fails after retries
    """
    if not PRODUCT_MATCHER_QUEUE_URL:
        logger.warning(
            "PRODUCT_MATCHER_QUEUE_URL not configured, skipping queue send",
            extra={"correlation_id": correlation_id}
        )
        return
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.debug(
                "Sending message to Product Matcher queue",
                extra={
                    "correlation_id": correlation_id,
                    "order_id": payload.get("order_id"),
                    "attempt": attempt + 1
                }
            )
            
            response = sqs_client.send_message(
                QueueUrl=PRODUCT_MATCHER_QUEUE_URL,
                MessageBody=json.dumps(payload),
                MessageAttributes={
                    "CorrelationId": {
                        "DataType": "String",
                        "StringValue": correlation_id
                    },
                    "OrderId": {
                        "DataType": "String",
                        "StringValue": payload.get("order_id", "unknown")
                    }
                }
            )
            
            logger.info(
                "Successfully sent message to Product Matcher queue",
                extra={
                    "correlation_id": correlation_id,
                    "order_id": payload.get("order_id"),
                    "message_id": response.get("MessageId")
                }
            )
            metrics.add_metric(name="ProductMatcherQueueSendSuccess", unit="Count", value=1)
            return
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.warning(
                "SQS send attempt failed",
                extra={
                    "correlation_id": correlation_id,
                    "error_code": error_code,
                    "attempt": attempt + 1,
                    "max_retries": max_retries
                }
            )
            
            if attempt == max_retries - 1:
                logger.error(
                    "Failed to send message after all retries",
                    extra={
                        "correlation_id": correlation_id,
                        "order_id": payload.get("order_id"),
                        "error": str(e)
                    }
                )
                metrics.add_metric(name="ProductMatcherQueueSendFailure", unit="Count", value=1)
                raise ProcessingError(f"Failed to send message to Product Matcher: {str(e)}")


def record_handler(record: SQSRecord) -> Dict[str, Any]:
    """
    Process individual SQS record with comprehensive error handling.
    
    Args:
        record: SQS record to process
        
    Returns:
        Processing result dictionary
        
    Raises:
        TextValidationError: If text validation fails (allows retry)
        ProcessingError: If processing fails (allows retry)
        ValueError: If input data is invalid (no retry)
    """
    start_time = logger.get_correlation_id()
    
    logger.info(
        "Processing SQS record",
        extra={
            "message_id": record.message_id,
            "receipt_handle": str(record.receipt_handle)[:20] + "..." if hasattr(record, 'receipt_handle') else "N/A"
        }
    )
    
    # Parse and validate message body
    try:
        body = json.loads(record.body)
    except json.JSONDecodeError as e:
        logger.error(
            "Invalid JSON in message body",
            extra={
                "message_id": record.message_id,
                "error": str(e)
            }
        )
        metrics.add_metric(name="InvalidMessageFormat", unit="Count", value=1)
        # Don't retry invalid JSON - it will never succeed
        raise ValueError(f"Invalid JSON in message body: {str(e)}")
    
    # Extract required fields
    order_id = body.get("order_id")
    raw_text = body.get("raw_text")
    created_at = body.get("created_at")
    
    # Validate required fields
    if not order_id:
        logger.error("Missing order_id in message", extra={"message_id": record.message_id})
        metrics.add_metric(name="MissingOrderId", unit="Count", value=1)
        raise ValueError("Missing required field: order_id")
    
    if not created_at:
        logger.error(
            "Missing created_at in message",
            extra={
                "message_id": record.message_id,
                "order_id": order_id
            }
        )
        metrics.add_metric(name="MissingCreatedAt", unit="Count", value=1)
        raise ValueError("Missing required field: created_at")
    
    if raw_text is None:  # Allow empty string but not None
        logger.error(
            "Missing raw_text in message",
            extra={
                "message_id": record.message_id,
                "order_id": order_id
            }
        )
        metrics.add_metric(name="MissingRawText", unit="Count", value=1)
        raise ValueError("Missing required field: raw_text")
    
    # Generate or use existing correlation ID
    correlation_id = body.get("correlation_id")
    if not correlation_id:
        correlation_id = generate_correlation_id()
        logger.info(
            "Generated new correlation ID",
            extra={
                "order_id": order_id,
                "correlation_id": correlation_id
            }
        )
    
    # Add correlation context to all subsequent logs
    logger.append_keys(
        order_id=order_id,
        correlation_id=correlation_id
    )
    
    logger.info(
        "Starting order processing",
        extra={
            "order_id": order_id,
            "correlation_id": correlation_id,
            "customer_email": body.get("customer_email"),
            "raw_text_length": len(raw_text) if raw_text else 0
        }
    )
    
    try:
        # Process the text
        processed_data = process_text(raw_text, order_id, correlation_id)
        
        # Enrich with metadata
        processed_data["correlation_id"] = correlation_id
        processed_data["customer_email"] = body.get("customer_email")
        processed_data["customer_name"] = body.get("customer_name")
        processed_data["created_at"] = created_at
        
        # Update order status to PARSING_COMPLETE
        if ORDERS_TABLE_NAME and created_at:
            try:
                update_order_status(
                    order_id=order_id,
                    status="PARSING_COMPLETE",
                    created_at=created_at,
                    correlation_id=correlation_id,
                    additional_attributes={
                        "processed_text": processed_data["processed_text"],
                        "text_length": processed_data["text_length"],
                        "line_count": processed_data["line_count"]
                    }
                )
            except ProcessingError as e:
                # Log but don't fail - we can still send to next stage
                logger.warning(
                    "Failed to update order status, continuing with processing",
                    extra={
                        "order_id": order_id,
                        "correlation_id": correlation_id,
                        "error": str(e)
                    }
                )
        
        # Send to Product Matcher queue
        if PRODUCT_MATCHER_QUEUE_URL:
            send_to_product_matcher(processed_data, correlation_id)
        
        # Record success metrics
        metrics.add_metric(name="TextParsingSuccess", unit="Count", value=1)
        metrics.add_metric(name="ProcessingDuration", unit="Milliseconds", value=1)  # Placeholder
        
        logger.info(
            "Successfully processed text",
            extra={
                "order_id": order_id,
                "correlation_id": correlation_id,
                "text_length": processed_data["text_length"],
                "line_count": processed_data["line_count"]
            }
        )
        
        return {
            "status": "success",
            "order_id": order_id,
            "correlation_id": correlation_id,
            "text_length": processed_data["text_length"]
        }
        
    except TextValidationError as e:
        # Validation errors - don't retry, update order with error
        metrics.add_metric(name="TextValidationError", unit="Count", value=1)
        logger.error(
            "Text validation failed",
            extra={
                "order_id": order_id,
                "correlation_id": correlation_id,
                "error": str(e),
                "error_type": "validation"
            }
        )
        
        # Try to update order status to FAILED
        if ORDERS_TABLE_NAME and created_at:
            try:
                update_order_status(
                    order_id=order_id,
                    status="FAILED",
                    created_at=created_at,
                    correlation_id=correlation_id,
                    additional_attributes={"error_details": str(e)}
                )
            except Exception as update_error:
                logger.error(
                    "Failed to update order status to FAILED",
                    extra={
                        "order_id": order_id,
                        "correlation_id": correlation_id,
                        "error": str(update_error)
                    }
                )
        
        # Don't retry validation errors
        raise ValueError(str(e))
        
    except ProcessingError as e:
        # Processing errors - can be retried
        metrics.add_metric(name="TextParsingError", unit="Count", value=1)
        logger.error(
            "Text processing failed",
            extra={
                "order_id": order_id,
                "correlation_id": correlation_id,
                "error": str(e),
                "error_type": "processing"
            }
        )
        # Re-raise to trigger SQS retry
        raise
        
    except Exception as e:
        # Unexpected errors - log and retry
        metrics.add_metric(name="TextParsingError", unit="Count", value=1)
        logger.exception(
            "Unexpected error processing text",
            extra={
                "order_id": order_id,
                "correlation_id": correlation_id,
                "error": str(e),
                "error_type": "unexpected"
            }
        )
        # Re-raise to trigger SQS retry
        raise


@logger.inject_lambda_context(correlation_id_path="Records[0].messageId")
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
@batch_processor(record_handler=record_handler, processor=processor)
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Main Lambda handler for text parsing.
    
    Processes SQS messages containing grocery list text from the submission queue,
    validates and normalizes the input, and forwards to Product Matcher queue.
    
    Features:
    - Input sanitization and normalization
    - Correlation ID generation and propagation
    - Structured logging with CloudWatch
    - Error handling and retry mechanisms
    - Batch processing with automatic retries
    
    Args:
        event: Lambda event containing SQS records
        context: Lambda context object
        
    Returns:
        Batch processing response with success/failure counts
    """
    logger.info(
        "Text Parser Lambda invoked",
        extra={
            "record_count": len(event.get("Records", [])),
            "environment": ENVIRONMENT,
            "function_name": context.function_name,
            "memory_limit_mb": context.memory_limit_in_mb,
            "request_id": context.request_id
        }
    )
    
    # Add environment context
    logger.append_keys(environment=ENVIRONMENT)
    
    # Process batch
    result = processor.response()
    
    logger.info(
        "Batch processing complete",
        extra={
            "total_records": len(event.get("Records", [])),
            "batch_item_failures": len(result.get("batchItemFailures", []))
        }
    )
    
    return result
