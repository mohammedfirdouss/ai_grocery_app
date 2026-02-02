"""
Pytest configuration and fixtures for AI Grocery App tests.
"""

import pytest
import os
import boto3
from moto import mock_aws
from decimal import Decimal
from datetime import datetime

# Add src to path for imports
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from models.core import Product, Order, ExtractedItem, MatchedItem


@pytest.fixture(scope="session")
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def sample_product():
    """Sample product for testing."""
    return Product(
        id="test-product-001",
        name="Test Bananas",
        description="Test organic bananas",
        category="Fruits",
        unit_price=Decimal("2.99"),
        unit_of_measure="bunch",
        tags=["test", "fruit", "banana"]
    )


@pytest.fixture
def sample_extracted_item():
    """Sample extracted item for testing."""
    return ExtractedItem(
        name="bananas",
        quantity=2.0,
        unit="bunch",
        specifications=["organic"],
        confidence_score=0.95,
        raw_text_segment="2 bunches of organic bananas"
    )


@pytest.fixture
def sample_matched_item(sample_extracted_item, sample_product):
    """Sample matched item for testing."""
    return MatchedItem(
        extracted_item=sample_extracted_item,
        product_id=sample_product.id,
        product_name=sample_product.name,
        unit_price=sample_product.unit_price,
        total_price=sample_product.unit_price * Decimal(str(sample_extracted_item.quantity)),
        match_confidence=0.90
    )


@pytest.fixture
def sample_order():
    """Sample order for testing."""
    return Order(
        customer_email="test@example.com",
        customer_name="Test Customer",
        raw_text="I need 2 bunches of organic bananas and 1 gallon of milk"
    )


@pytest.fixture
def mock_aws_services(aws_credentials):
    """Mock AWS services for testing."""
    with mock_aws():
        yield


@pytest.fixture
def dynamodb_client(mock_aws_services):
    """DynamoDB client for testing."""
    return boto3.client("dynamodb", region_name="us-east-1")


@pytest.fixture
def sqs_client(mock_aws_services):
    """SQS client for testing."""
    return boto3.client("sqs", region_name="us-east-1")


@pytest.fixture
def create_test_tables(dynamodb_client):
    """Create test DynamoDB tables."""
    # Orders table
    dynamodb_client.create_table(
        TableName="ai-grocery-orders-test",
        KeySchema=[
            {"AttributeName": "order_id", "KeyType": "HASH"},
            {"AttributeName": "created_at", "KeyType": "RANGE"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "order_id", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
            {"AttributeName": "customer_email", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"}
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "customer-email-index",
                "KeySchema": [
                    {"AttributeName": "customer_email", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"}
                ],
                "Projection": {"ProjectionType": "ALL"}
            },
            {
                "IndexName": "status-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"}
                ],
                "Projection": {"ProjectionType": "ALL"}
            }
        ]
    )
    
    # Products table
    dynamodb_client.create_table(
        TableName="ai-grocery-products-test",
        KeySchema=[
            {"AttributeName": "product_id", "KeyType": "HASH"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "product_id", "AttributeType": "S"},
            {"AttributeName": "category", "AttributeType": "S"},
            {"AttributeName": "name", "AttributeType": "S"}
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "category-index",
                "KeySchema": [
                    {"AttributeName": "category", "KeyType": "HASH"},
                    {"AttributeName": "name", "KeyType": "RANGE"}
                ],
                "Projection": {"ProjectionType": "ALL"}
            },
            {
                "IndexName": "name-index",
                "KeySchema": [
                    {"AttributeName": "name", "KeyType": "HASH"}
                ],
                "Projection": {"ProjectionType": "ALL"}
            }
        ]
    )
    
    # Payment links table
    dynamodb_client.create_table(
        TableName="ai-grocery-payment-links-test",
        KeySchema=[
            {"AttributeName": "order_id", "KeyType": "HASH"}
        ],
        AttributeDefinitions=[
            {"AttributeName": "order_id", "AttributeType": "S"}
        ],
        BillingMode="PAY_PER_REQUEST"
    )
    
    return dynamodb_client