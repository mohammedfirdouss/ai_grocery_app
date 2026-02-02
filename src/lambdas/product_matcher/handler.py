"""
Product Matcher Lambda Handler.

This Lambda function uses Amazon Bedrock to extract grocery items from text
and matches them against the product catalog.
"""

import json
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, batch_processor
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
import boto3
from botocore.exceptions import ClientError

# Initialize AWS Lambda Powertools
logger = Logger()
tracer = Tracer()
metrics = Metrics()

# Initialize AWS clients
sqs_client = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")
bedrock_runtime = boto3.client("bedrock-runtime")
secrets_client = boto3.client("secretsmanager")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
ORDERS_TABLE_NAME = os.environ.get("ORDERS_TABLE_NAME", "")
PRODUCTS_TABLE_NAME = os.environ.get("PRODUCTS_TABLE_NAME", "")
PAYMENT_PROCESSOR_QUEUE_URL = os.environ.get("PAYMENT_PROCESSOR_QUEUE_URL", "")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "4096"))
BEDROCK_TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.1"))

# Initialize batch processor
processor = BatchProcessor(event_type=EventType.SQS)


EXTRACTION_PROMPT = """You are a grocery list processing assistant. Extract items from the following text and return structured data.

Input text: {grocery_text}

Return a JSON array of items with this structure:
{{
  "items": [
    {{
      "name": "item name",
      "quantity": number,
      "unit": "unit of measurement",
      "specifications": ["any specific requirements"],
      "confidence": 0.0-1.0
    }}
  ]
}}

Rules:
1. Only include actual grocery items
2. Normalize quantities to standard units
3. Include confidence scores for matching
4. Handle ambiguous items with best guess
5. Return valid JSON only, no additional text"""


@tracer.capture_method
def invoke_bedrock(text: str) -> Dict[str, Any]:
    """
    Invoke Amazon Bedrock to extract grocery items from text.
    
    Args:
        text: Processed grocery list text
        
    Returns:
        Extracted items from Bedrock response
    """
    prompt = EXTRACTION_PROMPT.format(grocery_text=text)
    
    try:
        response = bedrock_runtime.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": BEDROCK_MAX_TOKENS,
                "temperature": BEDROCK_TEMPERATURE,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            })
        )
        
        response_body = json.loads(response["body"].read())
        content = response_body.get("content", [{}])[0].get("text", "{}")
        
        # Parse the JSON response
        extracted_data = json.loads(content)
        return extracted_data
        
    except ClientError as e:
        logger.error("Bedrock API error", extra={"error": str(e)})
        raise
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Bedrock response", extra={"error": str(e)})
        raise


@tracer.capture_method
def match_products(extracted_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Match extracted items against the product catalog.
    
    Args:
        extracted_items: List of items extracted by Bedrock
        
    Returns:
        List of matched products with pricing
    """
    products_table = dynamodb.Table(PRODUCTS_TABLE_NAME)
    matched_items = []
    
    for item in extracted_items:
        item_name = item.get("name", "").lower()
        quantity = item.get("quantity", 1)
        
        # Try exact match first
        try:
            response = products_table.query(
                IndexName="name-index",
                KeyConditionExpression="name = :name",
                ExpressionAttributeValues={":name": item_name}
            )
            
            if response.get("Items"):
                product = response["Items"][0]
                unit_price = Decimal(str(product.get("unit_price", 0)))
                matched_items.append({
                    "extracted_item": item,
                    "product_id": product.get("product_id"),
                    "product_name": product.get("name"),
                    "unit_price": float(unit_price),
                    "total_price": float(unit_price * Decimal(str(quantity))),
                    "availability": product.get("availability", True),
                    "match_confidence": 1.0,
                    "match_type": "exact"
                })
            else:
                # No match found - add as unmatched
                matched_items.append({
                    "extracted_item": item,
                    "product_id": None,
                    "product_name": item_name,
                    "unit_price": 0,
                    "total_price": 0,
                    "availability": False,
                    "match_confidence": 0,
                    "match_type": "unmatched"
                })
                
        except ClientError as e:
            logger.warning("Product lookup failed", extra={"item": item_name, "error": str(e)})
            matched_items.append({
                "extracted_item": item,
                "product_id": None,
                "product_name": item_name,
                "unit_price": 0,
                "total_price": 0,
                "availability": False,
                "match_confidence": 0,
                "match_type": "error"
            })
    
    return matched_items


@tracer.capture_method
def update_order_with_matches(
    order_id: str,
    created_at: str,
    extracted_items: List[Dict[str, Any]],
    matched_items: List[Dict[str, Any]],
    total_amount: float
) -> None:
    """Update order in DynamoDB with extracted and matched items."""
    table = dynamodb.Table(ORDERS_TABLE_NAME)
    
    # Convert Decimal for DynamoDB
    table.update_item(
        Key={"order_id": order_id, "created_at": created_at},
        UpdateExpression="SET #status = :status, extracted_items = :extracted, matched_items = :matched, total_amount = :total",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "MATCHING_COMPLETE",
            ":extracted": extracted_items,
            ":matched": matched_items,
            ":total": Decimal(str(total_amount))
        }
    )


@tracer.capture_method
def send_to_payment_processor(payload: Dict[str, Any]) -> None:
    """Send matched items to Payment Processor queue."""
    sqs_client.send_message(
        QueueUrl=PAYMENT_PROCESSOR_QUEUE_URL,
        MessageBody=json.dumps(payload, default=str),
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
    processed_text = body.get("processed_text")
    correlation_id = body.get("correlation_id", record.message_id)
    created_at = body.get("created_at")
    
    logger.append_keys(
        order_id=order_id,
        correlation_id=correlation_id
    )
    
    try:
        # Extract items using Bedrock
        extraction_result = invoke_bedrock(processed_text)
        extracted_items = extraction_result.get("items", [])
        
        metrics.add_metric(name="ItemsExtracted", unit="Count", value=len(extracted_items))
        logger.info("Extracted items from text", extra={"item_count": len(extracted_items)})
        
        # Match against product catalog
        matched_items = match_products(extracted_items)
        
        # Calculate total
        total_amount = sum(item.get("total_price", 0) for item in matched_items)
        
        # Update order in DynamoDB
        if ORDERS_TABLE_NAME and created_at:
            update_order_with_matches(
                order_id, created_at, extracted_items, matched_items, total_amount
            )
        
        # Prepare payload for payment processor
        payment_payload = {
            "order_id": order_id,
            "correlation_id": correlation_id,
            "customer_email": body.get("customer_email"),
            "customer_name": body.get("customer_name"),
            "created_at": created_at,
            "matched_items": matched_items,
            "total_amount": total_amount
        }
        
        # Send to Payment Processor
        if PAYMENT_PROCESSOR_QUEUE_URL:
            send_to_payment_processor(payment_payload)
        
        metrics.add_metric(name="ProductMatchingSuccess", unit="Count", value=1)
        logger.info("Successfully matched products", extra={"order_id": order_id, "total": total_amount})
        
        return {"status": "success", "order_id": order_id, "items_matched": len(matched_items)}
        
    except Exception as e:
        metrics.add_metric(name="ProductMatchingError", unit="Count", value=1)
        logger.exception("Error matching products", extra={"order_id": order_id, "error": str(e)})
        raise


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
@batch_processor(record_handler=record_handler, processor=processor)
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Main Lambda handler for product matching.
    
    Processes SQS messages containing processed grocery text,
    uses Bedrock to extract items, and matches against product catalog.
    """
    return processor.response()
