"""
Core data models for the AI Grocery App.

This module defines the primary data structures used throughout the application,
including orders, products, extracted items, and payment information.
All models use Pydantic for validation and serialization.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator, ConfigDict


class ProcessingStatus(str, Enum):
    """Order processing status enumeration."""
    SUBMITTED = "submitted"
    PARSING = "parsing"
    EXTRACTING = "extracting"
    MATCHING = "matching"
    PRICING = "pricing"
    PAYMENT_LINK_CREATING = "payment_link_creating"
    COMPLETED = "completed"
    FAILED = "failed"


class PaymentStatus(str, Enum):
    """Payment status enumeration."""
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ExtractedItem(BaseModel):
    """Item extracted from natural language grocery list."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    name: str = Field(..., min_length=1, max_length=200, description="Item name")
    quantity: float = Field(..., gt=0, description="Item quantity")
    unit: str = Field(..., min_length=1, max_length=50, description="Unit of measurement")
    specifications: List[str] = Field(default_factory=list, description="Additional specifications")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="AI confidence score")
    raw_text_segment: str = Field(..., description="Original text segment")
    
    @validator('specifications')
    def validate_specifications(cls, v):
        """Ensure specifications are not empty strings."""
        return [spec.strip() for spec in v if spec.strip()]


class MatchedItem(BaseModel):
    """Product-matched grocery item with pricing."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    extracted_item: ExtractedItem
    product_id: str = Field(..., min_length=1, description="Product catalog ID")
    product_name: str = Field(..., min_length=1, description="Matched product name")
    unit_price: Decimal = Field(..., ge=0, description="Price per unit")
    total_price: Decimal = Field(..., ge=0, description="Total price for quantity")
    availability: bool = Field(default=True, description="Product availability")
    match_confidence: float = Field(..., ge=0.0, le=1.0, description="Matching confidence")
    alternative_products: List[str] = Field(default_factory=list, description="Alternative product IDs")
    
    @validator('total_price')
    def validate_total_price(cls, v, values):
        """Ensure total price matches unit price * quantity."""
        if 'unit_price' in values and 'extracted_item' in values:
            expected = values['unit_price'] * Decimal(str(values['extracted_item'].quantity))
            if abs(v - expected) > Decimal('0.01'):  # Allow for rounding differences
                raise ValueError(f"Total price {v} doesn't match unit price * quantity {expected}")
        return v


class Product(BaseModel):
    """Product catalog item."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    id: str = Field(..., min_length=1, description="Unique product ID")
    name: str = Field(..., min_length=1, max_length=200, description="Product name")
    description: str = Field(..., max_length=1000, description="Product description")
    category: str = Field(..., min_length=1, max_length=100, description="Product category")
    unit_price: Decimal = Field(..., ge=0, description="Price per unit")
    currency: str = Field(default="NGN", description="Currency code")
    unit_of_measure: str = Field(..., min_length=1, description="Unit of measurement")
    availability: bool = Field(default=True, description="Product availability")
    tags: List[str] = Field(default_factory=list, description="Search tags")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    @validator('tags')
    def validate_tags(cls, v):
        """Ensure tags are not empty strings."""
        return [tag.strip().lower() for tag in v if tag.strip()]


class Order(BaseModel):
    """Grocery order with processing state."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique order ID")
    customer_email: str = Field(..., regex=r'^[^@]+@[^@]+\.[^@]+$', description="Customer email")
    customer_name: Optional[str] = Field(None, max_length=200, description="Customer name")
    raw_text: str = Field(..., min_length=1, max_length=5000, description="Original grocery list text")
    status: ProcessingStatus = Field(default=ProcessingStatus.SUBMITTED, description="Processing status")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: str = Field(default_factory=lambda: str(uuid4()), description="Correlation ID for tracing")
    
    # Processing results
    extracted_items: List[ExtractedItem] = Field(default_factory=list)
    matched_items: List[MatchedItem] = Field(default_factory=list)
    total_amount: Optional[Decimal] = Field(None, ge=0, description="Total order amount")
    payment_link: Optional[str] = Field(None, description="PayStack payment link")
    payment_status: Optional[PaymentStatus] = Field(None, description="Payment status")
    
    # Metadata
    processing_duration: Optional[int] = Field(None, ge=0, description="Processing time in milliseconds")
    ai_confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Overall AI confidence")
    error_details: Optional[str] = Field(None, description="Error information if processing failed")
    
    @validator('total_amount')
    def validate_total_amount(cls, v, values):
        """Ensure total amount matches sum of matched items."""
        if v is not None and 'matched_items' in values and values['matched_items']:
            expected = sum(item.total_price for item in values['matched_items'])
            if abs(v - expected) > Decimal('0.01'):  # Allow for rounding differences
                raise ValueError(f"Total amount {v} doesn't match sum of items {expected}")
        return v
    
    def calculate_total(self) -> Decimal:
        """Calculate total amount from matched items."""
        return sum(item.total_price for item in self.matched_items)
    
    def get_average_confidence(self) -> float:
        """Calculate average confidence score from extracted items."""
        if not self.extracted_items:
            return 0.0
        return sum(item.confidence_score for item in self.extracted_items) / len(self.extracted_items)


class PaymentLink(BaseModel):
    """PayStack payment link information."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    order_id: str = Field(..., description="Associated order ID")
    paystack_link_id: str = Field(..., description="PayStack payment link ID")
    payment_url: str = Field(..., description="PayStack payment URL")
    amount: Decimal = Field(..., ge=0, description="Payment amount")
    currency: str = Field(default="NGN", description="Currency code")
    status: PaymentStatus = Field(default=PaymentStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(..., description="Payment link expiration")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional PayStack metadata")
    
    @validator('expires_at')
    def validate_expiration(cls, v, values):
        """Ensure expiration is in the future."""
        if 'created_at' in values and v <= values['created_at']:
            raise ValueError("Expiration time must be after creation time")
        return v


class ProcessingEvent(BaseModel):
    """Event for real-time processing updates."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    order_id: str = Field(..., description="Order ID")
    event_type: str = Field(..., description="Event type")
    status: ProcessingStatus = Field(..., description="Current processing status")
    message: str = Field(..., description="Human-readable message")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: str = Field(..., description="Correlation ID for tracing")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional event data")


# Type aliases for common use cases
OrderDict = Dict[str, Any]
ProductDict = Dict[str, Any]
ExtractedItemDict = Dict[str, Any]
MatchedItemDict = Dict[str, Any]