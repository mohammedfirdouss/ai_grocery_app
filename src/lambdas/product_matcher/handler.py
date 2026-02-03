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
from aws_lambda_powertools.metrics import MetricUnit
import boto3
from botocore.exceptions import ClientError

from src.bedrock.client import (
    BedrockAgentClient,
    create_bedrock_client,
    BedrockClientError,
    RateLimitError,
    GuardrailBlockedError,
)
from src.bedrock.config import BedrockConfig
from src.bedrock.extractors import (
    GroceryItemExtractor,
    ConfidenceScorer,
    ExtractionResult,
    ExtractedGroceryItem,
)
from src.lambdas.product_matcher.matching import (
    ProductMatcher,
    MatchResult,
)
from src.lambdas.product_matcher.pricing import (
    PricingCalculator,
    TaxCalculator,
    InventoryChecker,
)

# Initialize AWS Lambda Powertools
logger = Logger()
tracer = Tracer()
metrics = Metrics()

# Initialize AWS clients
sqs_client = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")
secrets_client = boto3.client("secretsmanager")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
ORDERS_TABLE_NAME = os.environ.get("ORDERS_TABLE_NAME", "")
PRODUCTS_TABLE_NAME = os.environ.get("PRODUCTS_TABLE_NAME", "")
PAYMENT_PROCESSOR_QUEUE_URL = os.environ.get("PAYMENT_PROCESSOR_QUEUE_URL", "")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "4096"))
BEDROCK_TEMPERATURE = float(os.environ.get("BEDROCK_TEMPERATURE", "0.1"))
UNCERTAINTY_THRESHOLD = float(os.environ.get("BEDROCK_UNCERTAINTY_THRESHOLD", "0.7"))

# Initialize batch processor
processor = BatchProcessor(event_type=EventType.SQS)

# Initialize Bedrock client (lazy initialization)
_bedrock_client: Optional[BedrockAgentClient] = None
_bedrock_runtime_client: Optional[Any] = None
_extractor: Optional[GroceryItemExtractor] = None
_confidence_scorer: Optional[ConfidenceScorer] = None
_product_matcher: Optional[ProductMatcher] = None
_pricing_calculator: Optional[PricingCalculator] = None


def get_bedrock_client() -> BedrockAgentClient:
    """Get or create Bedrock client instance."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = create_bedrock_client(environment=ENVIRONMENT)
        logger.info(
            "Initialized Bedrock client",
            extra={"model_id": _bedrock_client.config.model_config.model_id}
        )
    return _bedrock_client


def get_extractor() -> GroceryItemExtractor:
    """Get or create extractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = GroceryItemExtractor(
            uncertainty_threshold=UNCERTAINTY_THRESHOLD,
            log_uncertain_items=True,
            emit_metrics=True,
        )
    return _extractor


def get_confidence_scorer() -> ConfidenceScorer:
    """Get or create confidence scorer instance."""
    global _confidence_scorer
    if _confidence_scorer is None:
        _confidence_scorer = ConfidenceScorer(base_threshold=UNCERTAINTY_THRESHOLD)
    return _confidence_scorer


def get_bedrock_runtime_client():
    """Get or create Bedrock Runtime client for embeddings."""
    global _bedrock_runtime_client
    if _bedrock_runtime_client is None:
        _bedrock_runtime_client = boto3.client("bedrock-runtime")
    return _bedrock_runtime_client


def get_product_matcher() -> ProductMatcher:
    """Get or create product matcher instance."""
    global _product_matcher
    if _product_matcher is None:
        bedrock_runtime = get_bedrock_runtime_client()
        _product_matcher = ProductMatcher(
            levenshtein_threshold=0.75,
            embedding_threshold=0.8,
            bedrock_client=bedrock_runtime
        )
    return _product_matcher


def get_pricing_calculator() -> PricingCalculator:
    """Get or create pricing calculator instance."""
    global _pricing_calculator
    if _pricing_calculator is None:
        _pricing_calculator = PricingCalculator(
            tax_calculator=TaxCalculator(),
            inventory_checker=InventoryChecker(),
            currency="NGN"
        )
    return _pricing_calculator


@tracer.capture_method
def invoke_bedrock(text: str) -> ExtractionResult:
    """
    Invoke Amazon Bedrock to extract grocery items from text.
    
    Uses the new Bedrock client with retry logic, guardrails,
    and structured data extraction.
    
    Args:
        text: Processed grocery list text
        
    Returns:
        ExtractionResult with extracted items
    """
    client = get_bedrock_client()
    extractor = get_extractor()
    
    try:
        # Invoke Bedrock with grocery extraction prompt
        result = client.extract_grocery_items(
            grocery_text=text,
            include_examples=True,
        )
        
        # Log invocation metrics
        logger.info(
            "Bedrock invocation completed",
            extra={
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "retry_count": result.retry_count,
            }
        )
        
        # Extract structured data from response
        extraction_result = extractor.extract(result.content)
        
        # Log extraction statistics
        logger.info(
            "Extraction completed",
            extra={
                "total_items": extraction_result.total_items,
                "average_confidence": extraction_result.average_confidence,
                "low_confidence_count": extraction_result.low_confidence_count,
            }
        )
        
        return extraction_result
        
    except GuardrailBlockedError as e:
        logger.error(
            "Request blocked by guardrails",
            extra={"error": str(e)}
        )
        metrics.add_metric(
            name="GuardrailBlockedRequests",
            unit=MetricUnit.Count,
            value=1
        )
        raise
        
    except RateLimitError as e:
        logger.error(
            "Rate limit exceeded after retries",
            extra={"error": str(e)}
        )
        metrics.add_metric(
            name="RateLimitErrors",
            unit=MetricUnit.Count,
            value=1
        )
        raise
        
    except BedrockClientError as e:
        logger.error(
            "Bedrock client error",
            extra={"error": str(e), "error_code": e.error_code}
        )
        metrics.add_metric(
            name="BedrockClientErrors",
            unit=MetricUnit.Count,
            value=1
        )
        raise


@tracer.capture_method
def match_products(
    extracted_items: List[ExtractedGroceryItem]
) -> List[Dict[str, Any]]:
    """
    Match extracted items against the product catalog.
    
    Uses comprehensive matching strategies including:
    - Exact name matching
    - Fuzzy matching with Levenshtein distance
    - Category-based matching with ML embeddings
    - Alternative product suggestions
    
    Args:
        extracted_items: List of items extracted by Bedrock
        
    Returns:
        List of matched products with pricing and alternatives
    """
    products_table = dynamodb.Table(PRODUCTS_TABLE_NAME)
    product_matcher = get_product_matcher()
    matched_items = []
    
    # Scan products table to get catalog (in production, use better caching/indexing)
    try:
        response = products_table.scan(Limit=1000)
        all_products = response.get("Items", [])
        
        logger.info(
            "Loaded product catalog",
            extra={"product_count": len(all_products)}
        )
    except ClientError as e:
        logger.error(
            "Failed to load product catalog",
            extra={"error": str(e)}
        )
        all_products = []
    
    for item in extracted_items:
        item_name = item.name.lower()
        quantity = item.quantity
        category = item.category if hasattr(item, 'category') else None
        
        # Try comprehensive matching
        match_result = product_matcher.match_product(
            item_name=item_name,
            products=all_products,
            category=category,
            name_field="name"
        )
        
        if match_result:
            product = match_result.product
            unit_price = Decimal(str(product.get("unit_price", 0)))
            
            # Calculate comprehensive match confidence
            match_confidence = min(
                item.confidence,  # AI extraction confidence
                match_result.confidence,  # Matching confidence
            )
            
            # Find alternative products
            alternatives = product_matcher.find_alternatives(
                item_name=item_name,
                products=all_products,
                category=category,
                max_alternatives=3,
                name_field="name"
            )
            
            # Filter out the matched product and format alternatives
            alternative_ids = [
                alt[0].get("product_id")
                for alt in alternatives
                if alt[0].get("product_id") != product.get("product_id") and alt[1] > 0.6
            ][:3]
            
            matched_items.append({
                "extracted_item": item.to_dict(),
                "product_id": product.get("product_id"),
                "product_name": product.get("name"),
                "category": product.get("category", ""),
                "unit_price": float(unit_price),
                "total_price": float(unit_price * Decimal(str(quantity))),
                "availability": product.get("availability", True),
                "stock_quantity": product.get("stock_quantity"),
                "match_confidence": match_confidence,
                "match_type": match_result.match_type,
                "similarity_score": match_result.similarity_score,
                "extraction_confidence": item.confidence,
                "uncertainty_reasons": [r.value for r in item.uncertainty_reasons],
                "alternative_products": alternative_ids,
            })
            
            logger.debug(
                "Product matched",
                extra={
                    "item_name": item_name,
                    "product_id": product.get("product_id"),
                    "match_type": match_result.match_type,
                    "match_confidence": match_confidence,
                    "alternatives_count": len(alternative_ids),
                }
            )
        else:
            # No match found - try to find alternatives anyway
            alternatives = product_matcher.find_alternatives(
                item_name=item_name,
                products=all_products,
                category=category,
                max_alternatives=3,
                name_field="name"
            )
            
            suggested_products = [
                {
                    "product_id": alt[0].get("product_id"),
                    "product_name": alt[0].get("name"),
                    "similarity_score": alt[1],
                }
                for alt in alternatives if alt[1] > 0.5
            ][:3]
            
            matched_items.append({
                "extracted_item": item.to_dict(),
                "product_id": None,
                "product_name": item_name,
                "category": category or "",
                "unit_price": 0,
                "total_price": 0,
                "availability": False,
                "match_confidence": 0,
                "match_type": "unmatched",
                "similarity_score": 0.0,
                "extraction_confidence": item.confidence,
                "uncertainty_reasons": [r.value for r in item.uncertainty_reasons],
                "alternative_products": [],
                "suggested_products": suggested_products,
            })
            
            logger.warning(
                "No product match found",
                extra={
                    "item_name": item_name,
                    "extraction_confidence": item.confidence,
                    "suggestions_count": len(suggested_products),
                }
            )
    
    # Emit matching metrics
    matched_count = sum(1 for item in matched_items if item["match_type"] != "unmatched")
    unmatched_count = len(matched_items) - matched_count
    
    # Count by match type
    exact_matches = sum(1 for item in matched_items if item["match_type"] == "exact")
    fuzzy_matches = sum(1 for item in matched_items if "fuzzy" in item["match_type"] or "levenshtein" in item["match_type"])
    embedding_matches = sum(1 for item in matched_items if "embedding" in item["match_type"])
    
    metrics.add_metric(
        name="ProductsMatched",
        unit=MetricUnit.Count,
        value=matched_count
    )
    metrics.add_metric(
        name="ProductsUnmatched",
        unit=MetricUnit.Count,
        value=unmatched_count
    )
    metrics.add_metric(
        name="ExactMatches",
        unit=MetricUnit.Count,
        value=exact_matches
    )
    metrics.add_metric(
        name="FuzzyMatches",
        unit=MetricUnit.Count,
        value=fuzzy_matches
    )
    metrics.add_metric(
        name="EmbeddingMatches",
        unit=MetricUnit.Count,
        value=embedding_matches
    )
    
    logger.info(
        "Product matching completed",
        extra={
            "total_items": len(matched_items),
            "matched": matched_count,
            "unmatched": unmatched_count,
            "exact": exact_matches,
            "fuzzy": fuzzy_matches,
            "embedding": embedding_matches,
        }
    )
    
    return matched_items


@tracer.capture_method
def update_order_with_matches(
    order_id: str,
    created_at: str,
    extraction_result: ExtractionResult,
    matched_items: List[Dict[str, Any]],
    total_amount: float
) -> None:
    """Update order in DynamoDB with extracted and matched items."""
    table = dynamodb.Table(ORDERS_TABLE_NAME)
    
    # Prepare confidence statistics
    scorer = get_confidence_scorer()
    confidence_stats = scorer.calculate_batch_confidence(extraction_result.items)
    
    # Convert data for DynamoDB
    table.update_item(
        Key={"order_id": order_id, "created_at": created_at},
        UpdateExpression="""
            SET #status = :status, 
                extracted_items = :extracted, 
                matched_items = :matched, 
                total_amount = :total,
                ai_confidence_score = :confidence,
                extraction_statistics = :stats,
                unrecognized_text = :unrecognized,
                parsing_notes = :notes
        """,
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "MATCHING_COMPLETE",
            ":extracted": [item.to_dict() for item in extraction_result.items],
            ":matched": matched_items,
            ":total": Decimal(str(total_amount)),
            ":confidence": Decimal(str(round(extraction_result.average_confidence, 3))),
            ":stats": confidence_stats,
            ":unrecognized": extraction_result.unrecognized_text,
            ":notes": extraction_result.parsing_notes,
        }
    )
    
    logger.info(
        "Order updated with extraction results",
        extra={
            "order_id": order_id,
            "items_extracted": extraction_result.total_items,
            "average_confidence": extraction_result.average_confidence,
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
        
        metrics.add_metric(
            name="ItemsExtracted",
            unit=MetricUnit.Count,
            value=extraction_result.total_items
        )
        
        logger.info(
            "Extracted items from text",
            extra={
                "item_count": extraction_result.total_items,
                "average_confidence": extraction_result.average_confidence,
                "uncertain_items": len(extraction_result.uncertain_items),
            }
        )
        
        # Match against product catalog
        matched_items = match_products(extraction_result.items)
        
        # Calculate pricing with tax and create itemized breakdown
        pricing_calculator = get_pricing_calculator()
        
        # Add detailed pricing to matched items
        matched_items_with_pricing = pricing_calculator.add_pricing_to_matched_items(
            matched_items
        )
        
        # Calculate order summary
        order_summary = pricing_calculator.calculate_order_summary(
            matched_items_with_pricing,
            check_inventory=True
        )
        
        # Get total amount
        total_amount = float(order_summary.total_amount)
        
        logger.info(
            "Pricing calculated",
            extra={
                "subtotal": float(order_summary.subtotal),
                "total_tax": float(order_summary.total_tax),
                "total_amount": total_amount,
                "item_count": order_summary.item_count,
            }
        )
        
        # Update order in DynamoDB
        if ORDERS_TABLE_NAME and created_at:
            update_order_with_matches(
                order_id,
                created_at,
                extraction_result,
                matched_items_with_pricing,
                total_amount
            )
        
        # Prepare payload for payment processor with itemized breakdown
        payment_payload = {
            "order_id": order_id,
            "correlation_id": correlation_id,
            "customer_email": body.get("customer_email"),
            "customer_name": body.get("customer_name"),
            "created_at": created_at,
            "matched_items": matched_items_with_pricing,
            "total_amount": total_amount,
            "subtotal": float(order_summary.subtotal),
            "total_tax": float(order_summary.total_tax),
            "currency": order_summary.currency,
            "itemized_breakdown": order_summary.to_dict(),
            "extraction_confidence": extraction_result.average_confidence,
            "has_uncertain_items": extraction_result.has_uncertain_items,
        }
        
        # Send to Payment Processor
        if PAYMENT_PROCESSOR_QUEUE_URL:
            send_to_payment_processor(payment_payload)
        
        metrics.add_metric(
            name="ProductMatchingSuccess",
            unit=MetricUnit.Count,
            value=1
        )
        
        logger.info(
            "Successfully matched products",
            extra={
                "order_id": order_id,
                "subtotal": float(order_summary.subtotal),
                "total_tax": float(order_summary.total_tax),
                "total": total_amount,
                "items_matched": len([i for i in matched_items_with_pricing if i["match_type"] != "unmatched"]),
            }
        )
        
        return {
            "status": "success",
            "order_id": order_id,
            "items_extracted": extraction_result.total_items,
            "items_matched": len(matched_items_with_pricing),
            "average_confidence": extraction_result.average_confidence,
        }
        
    except GuardrailBlockedError as e:
        # Log specific guardrail error
        metrics.add_metric(
            name="ProductMatchingGuardrailBlocked",
            unit=MetricUnit.Count,
            value=1
        )
        logger.error(
            "Order blocked by guardrails",
            extra={"order_id": order_id, "error": str(e)}
        )
        raise
        
    except Exception as e:
        metrics.add_metric(
            name="ProductMatchingError",
            unit=MetricUnit.Count,
            value=1
        )
        logger.exception(
            "Error matching products",
            extra={"order_id": order_id, "error": str(e)}
        )
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
