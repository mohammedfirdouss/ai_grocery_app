"""
Unit tests for core data models.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from pydantic import ValidationError

from models.core import (
    Order, Product, ExtractedItem, MatchedItem, PaymentLink,
    ProcessingStatus, PaymentStatus
)


class TestExtractedItem:
    """Test ExtractedItem model validation and behavior."""
    
    def test_valid_extracted_item(self):
        """Test creating a valid extracted item."""
        item = ExtractedItem(
            name="bananas",
            quantity=2.0,
            unit="bunch",
            specifications=["organic", "ripe"],
            confidence_score=0.95,
            raw_text_segment="2 bunches of organic ripe bananas"
        )
        
        assert item.name == "bananas"
        assert item.quantity == 2.0
        assert item.unit == "bunch"
        assert item.specifications == ["organic", "ripe"]
        assert item.confidence_score == 0.95
    
    def test_invalid_quantity(self):
        """Test that negative quantity raises validation error."""
        with pytest.raises(ValidationError):
            ExtractedItem(
                name="bananas",
                quantity=-1.0,
                unit="bunch",
                confidence_score=0.95,
                raw_text_segment="test"
            )
    
    def test_invalid_confidence_score(self):
        """Test that confidence score outside 0-1 range raises error."""
        with pytest.raises(ValidationError):
            ExtractedItem(
                name="bananas",
                quantity=2.0,
                unit="bunch",
                confidence_score=1.5,
                raw_text_segment="test"
            )
    
    def test_empty_specifications_filtered(self):
        """Test that empty specifications are filtered out."""
        item = ExtractedItem(
            name="bananas",
            quantity=2.0,
            unit="bunch",
            specifications=["organic", "", "  ", "ripe"],
            confidence_score=0.95,
            raw_text_segment="test"
        )
        
        assert item.specifications == ["organic", "ripe"]


class TestProduct:
    """Test Product model validation and behavior."""
    
    def test_valid_product(self):
        """Test creating a valid product."""
        product = Product(
            id="prod-001",
            name="Organic Bananas",
            description="Fresh organic bananas",
            category="Fruits",
            unit_price=Decimal("2.99"),
            unit_of_measure="bunch"
        )
        
        assert product.id == "prod-001"
        assert product.name == "Organic Bananas"
        assert product.unit_price == Decimal("2.99")
        assert product.currency == "NGN"  # Default value
    
    def test_tags_normalized(self):
        """Test that tags are normalized to lowercase and stripped."""
        product = Product(
            id="prod-001",
            name="Test Product",
            description="Test description",
            category="Test",
            unit_price=Decimal("1.00"),
            unit_of_measure="unit",
            tags=["  ORGANIC  ", "Fresh", "", "FRUIT"]
        )
        
        assert product.tags == ["organic", "fresh", "fruit"]


class TestMatchedItem:
    """Test MatchedItem model validation and behavior."""
    
    def test_valid_matched_item(self, sample_extracted_item, sample_product):
        """Test creating a valid matched item."""
        matched_item = MatchedItem(
            extracted_item=sample_extracted_item,
            product_id=sample_product.id,
            product_name=sample_product.name,
            unit_price=sample_product.unit_price,
            total_price=sample_product.unit_price * Decimal(str(sample_extracted_item.quantity)),
            match_confidence=0.90
        )
        
        assert matched_item.product_id == sample_product.id
        assert matched_item.total_price == Decimal("5.98")  # 2.99 * 2
    
    def test_total_price_validation_error(self, sample_extracted_item, sample_product):
        """Test that incorrect total price raises validation error."""
        with pytest.raises(ValidationError, match="Total price.*doesn't match"):
            MatchedItem(
                extracted_item=sample_extracted_item,
                product_id=sample_product.id,
                product_name=sample_product.name,
                unit_price=sample_product.unit_price,
                total_price=Decimal("10.00"),  # Incorrect total
                match_confidence=0.90
            )


class TestOrder:
    """Test Order model validation and behavior."""
    
    def test_valid_order(self):
        """Test creating a valid order."""
        order = Order(
            customer_email="test@example.com",
            customer_name="Test Customer",
            raw_text="I need bananas and milk"
        )
        
        assert order.customer_email == "test@example.com"
        assert order.status == ProcessingStatus.SUBMITTED
        assert order.id is not None
        assert order.correlation_id is not None
    
    def test_invalid_email(self):
        """Test that invalid email raises validation error."""
        with pytest.raises(ValidationError):
            Order(
                customer_email="invalid-email",
                raw_text="test"
            )
    
    def test_calculate_total(self, sample_matched_item):
        """Test total calculation from matched items."""
        order = Order(
            customer_email="test@example.com",
            raw_text="test",
            matched_items=[sample_matched_item]
        )
        
        total = order.calculate_total()
        assert total == sample_matched_item.total_price
    
    def test_get_average_confidence(self, sample_extracted_item):
        """Test average confidence calculation."""
        item2 = ExtractedItem(
            name="milk",
            quantity=1.0,
            unit="gallon",
            confidence_score=0.85,
            raw_text_segment="1 gallon of milk"
        )
        
        order = Order(
            customer_email="test@example.com",
            raw_text="test",
            extracted_items=[sample_extracted_item, item2]
        )
        
        avg_confidence = order.get_average_confidence()
        assert avg_confidence == pytest.approx(0.90)  # (0.95 + 0.85) / 2


class TestPaymentLink:
    """Test PaymentLink model validation and behavior."""
    
    def test_valid_payment_link(self):
        """Test creating a valid payment link."""
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(hours=24)
        
        payment_link = PaymentLink(
            order_id="test-order-001",
            paystack_link_id="pl_test123",
            payment_url="https://checkout.paystack.com/pl_test123",
            amount=Decimal("10.00"),
            created_at=created_at,
            expires_at=expires_at
        )
        
        assert payment_link.order_id == "test-order-001"
        assert payment_link.amount == Decimal("10.00")
        assert payment_link.status == PaymentStatus.PENDING
    
    def test_expiration_validation(self):
        """Test that expiration must be after creation."""
        created_at = datetime.utcnow()
        expires_at = created_at - timedelta(hours=1)  # In the past
        
        with pytest.raises(ValidationError, match="Expiration time must be after creation time"):
            PaymentLink(
                order_id="test-order-001",
                paystack_link_id="pl_test123",
                payment_url="https://checkout.paystack.com/pl_test123",
                amount=Decimal("10.00"),
                created_at=created_at,
                expires_at=expires_at
            )