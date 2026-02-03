"""
Pricing and inventory logic for AI Grocery App.

This module handles:
- Price calculation and aggregation
- Tax computation
- Inventory availability checks
- Itemized breakdown generation
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from aws_lambda_powertools import Logger

logger = Logger(child=True)


@dataclass
class TaxRate:
    """Tax rate configuration."""
    name: str
    rate: Decimal
    applies_to_categories: Optional[List[str]] = None


@dataclass
class PriceBreakdown:
    """Detailed price breakdown for an item."""
    product_id: str
    product_name: str
    quantity: float
    unit_price: Decimal
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    tax_rate: Decimal
    currency: str = "NGN"


@dataclass
class OrderSummary:
    """Summary of order pricing."""
    subtotal: Decimal
    total_tax: Decimal
    total_amount: Decimal
    items: List[PriceBreakdown]
    currency: str = "NGN"
    item_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "subtotal": float(self.subtotal),
            "total_tax": float(self.total_tax),
            "total_amount": float(self.total_amount),
            "currency": self.currency,
            "item_count": self.item_count,
            "items": [
                {
                    "product_id": item.product_id,
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "subtotal": float(item.subtotal),
                    "tax_amount": float(item.tax_amount),
                    "tax_rate": float(item.tax_rate),
                    "total": float(item.total),
                    "currency": item.currency,
                }
                for item in self.items
            ]
        }


class TaxCalculator:
    """Calculator for tax computation."""
    
    # Default tax rates (can be configured)
    DEFAULT_TAX_RATE = Decimal("0.075")  # 7.5% VAT in Nigeria
    EXEMPT_CATEGORIES = ["basic_foods", "medicines"]  # Tax-exempt categories
    
    def __init__(self, tax_rates: Optional[Dict[str, TaxRate]] = None):
        """
        Initialize tax calculator.
        
        Args:
            tax_rates: Optional dictionary of category-specific tax rates
        """
        self.tax_rates = tax_rates or {}
    
    def get_tax_rate(self, product: Dict[str, Any]) -> Decimal:
        """
        Get applicable tax rate for a product.
        
        Args:
            product: Product dictionary
            
        Returns:
            Tax rate as decimal (e.g., 0.075 for 7.5%)
        """
        category = product.get("category", "").lower()
        
        # Check for tax-exempt categories
        if category in self.EXEMPT_CATEGORIES:
            return Decimal("0")
        
        # Check for category-specific rates
        if category in self.tax_rates:
            return self.tax_rates[category].rate
        
        # Return default rate
        return self.DEFAULT_TAX_RATE
    
    def calculate_tax(
        self,
        amount: Decimal,
        tax_rate: Decimal
    ) -> Decimal:
        """
        Calculate tax amount.
        
        Args:
            amount: Pre-tax amount
            tax_rate: Tax rate as decimal
            
        Returns:
            Tax amount
        """
        tax = (amount * tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return tax
    
    def calculate_item_tax(
        self,
        product: Dict[str, Any],
        quantity: float
    ) -> Tuple[Decimal, Decimal]:
        """
        Calculate tax for an item.
        
        Args:
            product: Product dictionary
            quantity: Item quantity
            
        Returns:
            Tuple of (subtotal, tax_amount)
        """
        unit_price = Decimal(str(product.get("unit_price", 0)))
        subtotal = (unit_price * Decimal(str(quantity))).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
        
        tax_rate = self.get_tax_rate(product)
        tax_amount = self.calculate_tax(subtotal, tax_rate)
        
        return subtotal, tax_amount


class InventoryChecker:
    """Check product availability and inventory."""
    
    def __init__(self, dynamodb_table=None):
        """
        Initialize inventory checker.
        
        Args:
            dynamodb_table: Optional DynamoDB table for inventory queries
        """
        self.dynamodb_table = dynamodb_table
    
    def check_availability(self, product: Dict[str, Any]) -> bool:
        """
        Check if product is available.
        
        Args:
            product: Product dictionary
            
        Returns:
            True if available, False otherwise
        """
        # Check availability flag
        if not product.get("availability", True):
            return False
        
        # Check stock quantity if available
        stock_quantity = product.get("stock_quantity")
        if stock_quantity is not None:
            return stock_quantity > 0
        
        # Default to available if no stock info
        return True
    
    def check_sufficient_stock(
        self,
        product: Dict[str, Any],
        requested_quantity: float
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if sufficient stock is available.
        
        Args:
            product: Product dictionary
            requested_quantity: Requested quantity
            
        Returns:
            Tuple of (is_sufficient, available_quantity)
        """
        stock_quantity = product.get("stock_quantity")
        
        # If no stock tracking, assume sufficient
        if stock_quantity is None:
            return True, None
        
        is_sufficient = stock_quantity >= requested_quantity
        return is_sufficient, float(stock_quantity)
    
    def get_available_quantity(
        self,
        product: Dict[str, Any],
        requested_quantity: float
    ) -> float:
        """
        Get available quantity (may be less than requested).
        
        Args:
            product: Product dictionary
            requested_quantity: Requested quantity
            
        Returns:
            Available quantity
        """
        is_sufficient, stock_quantity = self.check_sufficient_stock(
            product,
            requested_quantity
        )
        
        if is_sufficient or stock_quantity is None:
            return requested_quantity
        
        return stock_quantity


class PricingCalculator:
    """
    Comprehensive pricing calculator.
    
    Handles price calculation, tax computation, and itemized breakdown generation.
    """
    
    def __init__(
        self,
        tax_calculator: Optional[TaxCalculator] = None,
        inventory_checker: Optional[InventoryChecker] = None,
        currency: str = "NGN"
    ):
        """
        Initialize pricing calculator.
        
        Args:
            tax_calculator: Optional tax calculator instance
            inventory_checker: Optional inventory checker instance
            currency: Currency code
        """
        self.tax_calculator = tax_calculator or TaxCalculator()
        self.inventory_checker = inventory_checker or InventoryChecker()
        self.currency = currency
    
    def calculate_item_price(
        self,
        product: Dict[str, Any],
        quantity: float,
        check_inventory: bool = True
    ) -> PriceBreakdown:
        """
        Calculate complete price breakdown for an item.
        
        Args:
            product: Product dictionary
            quantity: Item quantity
            check_inventory: Whether to check inventory availability
            
        Returns:
            PriceBreakdown with all pricing details
        """
        product_id = product.get("product_id", product.get("id", "unknown"))
        product_name = product.get("name", "Unknown Product")
        unit_price = Decimal(str(product.get("unit_price", 0)))
        
        # Adjust quantity based on inventory if needed
        final_quantity = quantity
        if check_inventory:
            final_quantity = self.inventory_checker.get_available_quantity(
                product,
                quantity
            )
            
            if final_quantity < quantity:
                logger.warning(
                    "Insufficient inventory",
                    extra={
                        "product_id": product_id,
                        "requested": quantity,
                        "available": final_quantity
                    }
                )
        
        # Calculate subtotal
        subtotal = (unit_price * Decimal(str(final_quantity))).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
        
        # Calculate tax
        tax_rate = self.tax_calculator.get_tax_rate(product)
        tax_amount = self.tax_calculator.calculate_tax(subtotal, tax_rate)
        
        # Calculate total
        total = subtotal + tax_amount
        
        return PriceBreakdown(
            product_id=product_id,
            product_name=product_name,
            quantity=final_quantity,
            unit_price=unit_price,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total=total,
            tax_rate=tax_rate,
            currency=self.currency
        )
    
    def calculate_order_summary(
        self,
        matched_items: List[Dict[str, Any]],
        check_inventory: bool = True
    ) -> OrderSummary:
        """
        Calculate complete order summary with itemized breakdown.
        
        Args:
            matched_items: List of matched items with products and quantities
            check_inventory: Whether to check inventory availability
            
        Returns:
            OrderSummary with complete pricing breakdown
        """
        item_breakdowns = []
        subtotal = Decimal("0")
        total_tax = Decimal("0")
        
        for matched_item in matched_items:
            # Skip unmatched items
            if not matched_item.get("product_id"):
                continue
            
            # Extract product info
            product = {
                "product_id": matched_item["product_id"],
                "name": matched_item["product_name"],
                "unit_price": matched_item["unit_price"],
                "category": matched_item.get("category", ""),
                "availability": matched_item.get("availability", True),
                "stock_quantity": matched_item.get("stock_quantity"),
            }
            
            quantity = matched_item.get("extracted_item", {}).get("quantity", 1)
            
            # Calculate item pricing
            breakdown = self.calculate_item_price(
                product,
                quantity,
                check_inventory=check_inventory
            )
            
            item_breakdowns.append(breakdown)
            subtotal += breakdown.subtotal
            total_tax += breakdown.tax_amount
        
        total_amount = subtotal + total_tax
        
        return OrderSummary(
            subtotal=subtotal,
            total_tax=total_tax,
            total_amount=total_amount,
            items=item_breakdowns,
            currency=self.currency,
            item_count=len(item_breakdowns)
        )
    
    def add_pricing_to_matched_items(
        self,
        matched_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Add detailed pricing information to matched items.
        
        Args:
            matched_items: List of matched items
            
        Returns:
            Updated matched items with pricing details
        """
        updated_items = []
        
        for item in matched_items:
            # Skip unmatched items
            if not item.get("product_id"):
                updated_items.append(item)
                continue
            
            product = {
                "product_id": item["product_id"],
                "name": item["product_name"],
                "unit_price": item["unit_price"],
                "category": item.get("category", ""),
                "availability": item.get("availability", True),
                "stock_quantity": item.get("stock_quantity"),
            }
            
            quantity = item.get("extracted_item", {}).get("quantity", 1)
            
            breakdown = self.calculate_item_price(product, quantity)
            
            # Add pricing details to item
            updated_item = {**item}
            updated_item.update({
                "subtotal": float(breakdown.subtotal),
                "tax_amount": float(breakdown.tax_amount),
                "tax_rate": float(breakdown.tax_rate),
                "total_with_tax": float(breakdown.total),
            })
            
            updated_items.append(updated_item)
        
        return updated_items
