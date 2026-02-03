"""
Tests for pricing and inventory logic.

Tests price calculation, tax computation, inventory checks,
and itemized breakdown generation.
"""

import pytest
from decimal import Decimal
from src.lambdas.product_matcher.pricing import (
    TaxCalculator,
    InventoryChecker,
    PricingCalculator,
    PriceBreakdown,
    OrderSummary,
)


class TestTaxCalculator:
    """Tests for tax calculation."""
    
    def test_default_tax_rate(self):
        """Test default tax rate application."""
        calculator = TaxCalculator()
        product = {"product_id": "1", "name": "test", "category": "general"}
        rate = calculator.get_tax_rate(product)
        assert rate == Decimal("0.075")  # 7.5% VAT
    
    def test_exempt_category_tax(self):
        """Test tax-exempt categories."""
        calculator = TaxCalculator()
        product = {"product_id": "1", "name": "rice", "category": "basic_foods"}
        rate = calculator.get_tax_rate(product)
        assert rate == Decimal("0")
    
    def test_calculate_tax_amount(self):
        """Test tax amount calculation."""
        calculator = TaxCalculator()
        tax = calculator.calculate_tax(Decimal("100"), Decimal("0.075"))
        assert tax == Decimal("7.50")
    
    def test_tax_rounding(self):
        """Test tax calculation rounding."""
        calculator = TaxCalculator()
        tax = calculator.calculate_tax(Decimal("100.55"), Decimal("0.075"))
        assert tax == Decimal("7.54")
    
    def test_calculate_item_tax(self):
        """Test complete item tax calculation."""
        calculator = TaxCalculator()
        product = {
            "product_id": "1",
            "name": "test",
            "category": "general",
            "unit_price": 10.0
        }
        subtotal, tax = calculator.calculate_item_tax(product, 5)
        
        assert subtotal == Decimal("50.00")
        assert tax == Decimal("3.75")
    
    def test_exempt_item_tax(self):
        """Test tax calculation for exempt items."""
        calculator = TaxCalculator()
        product = {
            "product_id": "1",
            "name": "rice",
            "category": "basic_foods",
            "unit_price": 10.0
        }
        subtotal, tax = calculator.calculate_item_tax(product, 5)
        
        assert subtotal == Decimal("50.00")
        assert tax == Decimal("0")


class TestInventoryChecker:
    """Tests for inventory checking."""
    
    def test_check_availability_true(self):
        """Test product availability check - available."""
        checker = InventoryChecker()
        product = {"product_id": "1", "availability": True, "stock_quantity": 10}
        assert checker.check_availability(product) is True
    
    def test_check_availability_false(self):
        """Test product availability check - unavailable."""
        checker = InventoryChecker()
        product = {"product_id": "1", "availability": False}
        assert checker.check_availability(product) is False
    
    def test_check_availability_no_stock(self):
        """Test availability with zero stock."""
        checker = InventoryChecker()
        product = {"product_id": "1", "availability": True, "stock_quantity": 0}
        assert checker.check_availability(product) is False
    
    def test_check_availability_default(self):
        """Test availability defaults to True."""
        checker = InventoryChecker()
        product = {"product_id": "1"}
        assert checker.check_availability(product) is True
    
    def test_check_sufficient_stock_enough(self):
        """Test sufficient stock check - enough stock."""
        checker = InventoryChecker()
        product = {"product_id": "1", "stock_quantity": 10}
        is_sufficient, available = checker.check_sufficient_stock(product, 5)
        
        assert is_sufficient is True
        assert available == 10.0
    
    def test_check_sufficient_stock_insufficient(self):
        """Test sufficient stock check - insufficient stock."""
        checker = InventoryChecker()
        product = {"product_id": "1", "stock_quantity": 3}
        is_sufficient, available = checker.check_sufficient_stock(product, 5)
        
        assert is_sufficient is False
        assert available == 3.0
    
    def test_check_sufficient_stock_no_tracking(self):
        """Test sufficient stock when no tracking."""
        checker = InventoryChecker()
        product = {"product_id": "1"}
        is_sufficient, available = checker.check_sufficient_stock(product, 5)
        
        assert is_sufficient is True
        assert available is None
    
    def test_get_available_quantity_full(self):
        """Test getting available quantity - full amount."""
        checker = InventoryChecker()
        product = {"product_id": "1", "stock_quantity": 10}
        quantity = checker.get_available_quantity(product, 5)
        
        assert quantity == 5
    
    def test_get_available_quantity_partial(self):
        """Test getting available quantity - partial amount."""
        checker = InventoryChecker()
        product = {"product_id": "1", "stock_quantity": 3}
        quantity = checker.get_available_quantity(product, 5)
        
        assert quantity == 3.0


class TestPricingCalculator:
    """Tests for comprehensive pricing calculation."""
    
    @pytest.fixture
    def calculator(self):
        """Create pricing calculator instance."""
        return PricingCalculator(currency="NGN")
    
    @pytest.fixture
    def sample_product(self):
        """Sample product for testing."""
        return {
            "product_id": "1",
            "name": "test product",
            "unit_price": 10.0,
            "category": "general",
            "availability": True,
            "stock_quantity": 100,
        }
    
    def test_calculate_item_price(self, calculator, sample_product):
        """Test item price calculation."""
        breakdown = calculator.calculate_item_price(sample_product, 5)
        
        assert breakdown.product_id == "1"
        assert breakdown.quantity == 5
        assert breakdown.unit_price == Decimal("10.0")
        assert breakdown.subtotal == Decimal("50.00")
        assert breakdown.tax_amount == Decimal("3.75")  # 7.5% tax
        assert breakdown.total == Decimal("53.75")
    
    def test_calculate_item_price_with_inventory_check(self, calculator):
        """Test price calculation with inventory check."""
        product = {
            "product_id": "1",
            "name": "test",
            "unit_price": 10.0,
            "category": "general",
            "availability": True,
            "stock_quantity": 3,
        }
        
        breakdown = calculator.calculate_item_price(product, 5, check_inventory=True)
        
        # Should adjust to available quantity
        assert breakdown.quantity == 3.0
        assert breakdown.subtotal == Decimal("30.00")
    
    def test_calculate_item_price_tax_exempt(self, calculator):
        """Test price calculation for tax-exempt item."""
        product = {
            "product_id": "1",
            "name": "rice",
            "unit_price": 10.0,
            "category": "basic_foods",
            "availability": True,
        }
        
        breakdown = calculator.calculate_item_price(product, 5)
        
        assert breakdown.subtotal == Decimal("50.00")
        assert breakdown.tax_amount == Decimal("0")
        assert breakdown.total == Decimal("50.00")
    
    def test_calculate_order_summary(self, calculator):
        """Test order summary calculation."""
        matched_items = [
            {
                "product_id": "1",
                "product_name": "product 1",
                "unit_price": 10.0,
                "category": "general",
                "availability": True,
                "extracted_item": {"quantity": 2},
            },
            {
                "product_id": "2",
                "product_name": "product 2",
                "unit_price": 20.0,
                "category": "general",
                "availability": True,
                "extracted_item": {"quantity": 3},
            },
        ]
        
        summary = calculator.calculate_order_summary(matched_items)
        
        assert summary.item_count == 2
        assert summary.subtotal == Decimal("80.00")  # (10*2) + (20*3)
        assert summary.total_tax == Decimal("6.00")  # 7.5% of 80
        assert summary.total_amount == Decimal("86.00")
    
    def test_calculate_order_summary_mixed_tax(self, calculator):
        """Test order summary with mixed tax rates."""
        matched_items = [
            {
                "product_id": "1",
                "product_name": "rice",
                "unit_price": 10.0,
                "category": "basic_foods",  # Tax exempt
                "availability": True,
                "extracted_item": {"quantity": 2},
            },
            {
                "product_id": "2",
                "product_name": "snack",
                "unit_price": 20.0,
                "category": "general",  # Taxable
                "availability": True,
                "extracted_item": {"quantity": 1},
            },
        ]
        
        summary = calculator.calculate_order_summary(matched_items)
        
        assert summary.subtotal == Decimal("40.00")  # 20 + 20
        assert summary.total_tax == Decimal("1.50")  # Only 7.5% on the 20
        assert summary.total_amount == Decimal("41.50")
    
    def test_calculate_order_summary_skip_unmatched(self, calculator):
        """Test order summary skips unmatched items."""
        matched_items = [
            {
                "product_id": "1",
                "product_name": "product 1",
                "unit_price": 10.0,
                "category": "general",
                "availability": True,
                "extracted_item": {"quantity": 2},
            },
            {
                "product_id": None,  # Unmatched
                "product_name": "unknown",
                "unit_price": 0,
                "category": "",
                "availability": False,
                "extracted_item": {"quantity": 1},
            },
        ]
        
        summary = calculator.calculate_order_summary(matched_items)
        
        assert summary.item_count == 1
        assert summary.subtotal == Decimal("20.00")
    
    def test_add_pricing_to_matched_items(self, calculator):
        """Test adding pricing details to matched items."""
        matched_items = [
            {
                "product_id": "1",
                "product_name": "test",
                "unit_price": 10.0,
                "category": "general",
                "availability": True,
                "extracted_item": {"quantity": 2},
            },
        ]
        
        updated = calculator.add_pricing_to_matched_items(matched_items)
        
        assert len(updated) == 1
        assert "subtotal" in updated[0]
        assert "tax_amount" in updated[0]
        assert "tax_rate" in updated[0]
        assert "total_with_tax" in updated[0]
        assert updated[0]["subtotal"] == 20.0
        assert updated[0]["tax_amount"] == 1.5
    
    def test_order_summary_to_dict(self, calculator):
        """Test order summary serialization."""
        matched_items = [
            {
                "product_id": "1",
                "product_name": "test",
                "unit_price": 10.0,
                "category": "general",
                "availability": True,
                "extracted_item": {"quantity": 2},
            },
        ]
        
        summary = calculator.calculate_order_summary(matched_items)
        data = summary.to_dict()
        
        assert isinstance(data, dict)
        assert "subtotal" in data
        assert "total_tax" in data
        assert "total_amount" in data
        assert "currency" in data
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) == 1
