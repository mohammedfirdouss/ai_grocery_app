"""
PayStack data models for payment integration.

This module defines the data structures used for PayStack payment operations,
including payment requests, responses, and webhook events.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class PayStackTransactionStatus(str, Enum):
    """PayStack transaction status enumeration."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    ABANDONED = "abandoned"
    REVERSED = "reversed"


class PayStackLineItem(BaseModel):
    """Individual line item in a payment request."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    name: str = Field(..., min_length=1, max_length=200, description="Item name")
    quantity: int = Field(..., ge=1, description="Item quantity")
    amount: int = Field(..., ge=0, description="Item amount in kobo (NGN smallest unit)")


class PayStackCustomField(BaseModel):
    """Custom field for PayStack payment metadata."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )
    
    display_name: str = Field(..., description="Display name for the field")
    variable_name: str = Field(..., description="Variable name for the field")
    value: str = Field(..., description="Field value")


class PayStackPaymentRequest(BaseModel):
    """PayStack payment initialization request."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    email: str = Field(..., description="Customer email address")
    amount: int = Field(..., ge=0, description="Amount in kobo (NGN smallest unit)")
    currency: str = Field(default="NGN", description="Currency code")
    reference: str = Field(..., description="Unique transaction reference")
    callback_url: Optional[str] = Field(None, description="URL to redirect after payment")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    line_items: Optional[List[PayStackLineItem]] = Field(default_factory=list, description="Itemized breakdown")
    custom_fields: Optional[List[PayStackCustomField]] = Field(default_factory=list, description="Custom display fields")
    
    @classmethod
    def from_order(
        cls,
        order_id: str,
        customer_email: str,
        customer_name: Optional[str],
        matched_items: List[Dict[str, Any]],
        total_amount: float,
        callback_url: Optional[str] = None
    ) -> "PayStackPaymentRequest":
        """Create a payment request from an order.
        
        Args:
            order_id: Unique order identifier
            customer_email: Customer's email address
            customer_name: Customer's name (optional)
            matched_items: List of matched items with pricing
            total_amount: Total order amount in Naira
            callback_url: Optional callback URL after payment
            
        Returns:
            PayStackPaymentRequest instance
        """
        # Convert to kobo (smallest unit)
        amount_kobo = int(total_amount * 100)
        
        # Create line items from matched items
        line_items = []
        for item in matched_items:
            item_name = item.get("product_name", item.get("name", "Unknown Item"))
            quantity = int(item.get("quantity", 1))
            unit_price = float(item.get("unit_price", 0))
            item_amount = int(unit_price * 100)  # Convert to kobo
            
            line_items.append(PayStackLineItem(
                name=item_name[:200],  # Truncate to max length
                quantity=quantity,
                amount=item_amount
            ))
        
        # Create custom fields for display
        custom_fields = [
            PayStackCustomField(
                display_name="Order ID",
                variable_name="order_id",
                value=order_id
            )
        ]
        
        if customer_name:
            custom_fields.append(PayStackCustomField(
                display_name="Customer Name",
                variable_name="customer_name",
                value=customer_name[:200]
            ))
        
        custom_fields.append(PayStackCustomField(
            display_name="Items Count",
            variable_name="items_count",
            value=str(len(matched_items))
        ))
        
        # Build metadata
        metadata = {
            "order_id": order_id,
            "customer_name": customer_name or "",
            "item_count": len(matched_items),
            "line_items": [item.model_dump() for item in line_items],
            "custom_fields": [field.model_dump() for field in custom_fields]
        }
        
        return cls(
            email=customer_email,
            amount=amount_kobo,
            currency="NGN",
            reference=f"order-{order_id}",
            callback_url=callback_url,
            metadata=metadata,
            line_items=line_items,
            custom_fields=custom_fields
        )


class PayStackPaymentResponse(BaseModel):
    """PayStack payment initialization response."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    success: bool = Field(..., description="Whether the request was successful")
    authorization_url: Optional[str] = Field(None, description="URL to redirect for payment")
    access_code: Optional[str] = Field(None, description="Access code for the payment")
    reference: Optional[str] = Field(None, description="Transaction reference")
    expires_at: Optional[datetime] = Field(None, description="Payment link expiration time")
    message: Optional[str] = Field(None, description="Response message")
    error_code: Optional[str] = Field(None, description="Error code if failed")


class PayStackWebhookEvent(BaseModel):
    """PayStack webhook event payload."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    event: str = Field(..., description="Event type (e.g., charge.success)")
    data: Dict[str, Any] = Field(..., description="Event data payload")
    
    @property
    def event_type(self) -> str:
        """Get the event type."""
        return self.event
    
    @property
    def reference(self) -> Optional[str]:
        """Get transaction reference."""
        return self.data.get("reference")
    
    @property
    def status(self) -> Optional[str]:
        """Get transaction status."""
        return self.data.get("status")
    
    @property
    def amount(self) -> Optional[int]:
        """Get transaction amount in kobo."""
        return self.data.get("amount")
    
    @property
    def order_id(self) -> Optional[str]:
        """Extract order ID from reference or metadata."""
        reference = self.reference
        if reference and reference.startswith("order-"):
            return reference[6:]  # Remove "order-" prefix
        
        # Try to get from metadata
        metadata = self.data.get("metadata", {})
        return metadata.get("order_id")
    
    @property
    def customer_email(self) -> Optional[str]:
        """Get customer email."""
        customer = self.data.get("customer", {})
        return customer.get("email")
    
    @property
    def paid_at(self) -> Optional[datetime]:
        """Get payment timestamp."""
        paid_at_str = self.data.get("paid_at")
        if paid_at_str:
            try:
                return datetime.fromisoformat(paid_at_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        return None
    
    def is_successful_payment(self) -> bool:
        """Check if this is a successful payment event."""
        return (
            self.event == "charge.success" and 
            self.status == "success"
        )
    
    def is_failed_payment(self) -> bool:
        """Check if this is a failed payment event."""
        return self.event in ("charge.failed", "transfer.failed")


class PayStackVerifyResponse(BaseModel):
    """PayStack transaction verification response."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True
    )
    
    success: bool = Field(..., description="Whether the verification was successful")
    status: Optional[PayStackTransactionStatus] = Field(None, description="Transaction status")
    amount: Optional[int] = Field(None, description="Amount in kobo")
    reference: Optional[str] = Field(None, description="Transaction reference")
    paid_at: Optional[datetime] = Field(None, description="Payment timestamp")
    message: Optional[str] = Field(None, description="Response message")
    error_code: Optional[str] = Field(None, description="Error code if failed")
