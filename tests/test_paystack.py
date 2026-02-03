"""
Unit tests for PayStack payment integration.

This module tests the PayStack client, models, and webhook handling functionality.
"""

import hashlib
import hmac
import json
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import urllib.error

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from paystack.client import (
    PayStackClient,
    PayStackError,
    PayStackAuthenticationError,
    PayStackRateLimitError,
    PayStackValidationError,
)
from paystack.models import (
    PayStackPaymentRequest,
    PayStackPaymentResponse,
    PayStackWebhookEvent,
    PayStackTransactionStatus,
    PayStackLineItem,
    PayStackCustomField,
    PayStackVerifyResponse,
)


class TestPayStackModels:
    """Test PayStack data models."""
    
    def test_line_item_creation(self):
        """Test creating a valid line item."""
        item = PayStackLineItem(
            name="Organic Bananas",
            quantity=2,
            amount=15000  # 150 NGN in kobo
        )
        
        assert item.name == "Organic Bananas"
        assert item.quantity == 2
        assert item.amount == 15000
    
    def test_line_item_invalid_quantity(self):
        """Test that line item rejects invalid quantity."""
        with pytest.raises(ValueError):
            PayStackLineItem(
                name="Test Item",
                quantity=0,  # Invalid: must be >= 1
                amount=1000
            )
    
    def test_custom_field_creation(self):
        """Test creating a custom field."""
        field = PayStackCustomField(
            display_name="Order ID",
            variable_name="order_id",
            value="test-order-123"
        )
        
        assert field.display_name == "Order ID"
        assert field.variable_name == "order_id"
        assert field.value == "test-order-123"
    
    def test_payment_request_from_order(self):
        """Test creating payment request from order data."""
        matched_items = [
            {
                "product_name": "Bananas",
                "quantity": 2,
                "unit_price": 150.00
            },
            {
                "product_name": "Milk",
                "quantity": 1,
                "unit_price": 500.00
            }
        ]
        
        request = PayStackPaymentRequest.from_order(
            order_id="test-order-123",
            customer_email="customer@example.com",
            customer_name="John Doe",
            matched_items=matched_items,
            total_amount=800.00,
            callback_url="https://example.com/callback"
        )
        
        assert request.email == "customer@example.com"
        assert request.amount == 80000  # 800 NGN in kobo
        assert request.currency == "NGN"
        assert request.reference == "order-test-order-123"
        assert request.callback_url == "https://example.com/callback"
        assert len(request.line_items) == 2
        assert request.metadata["order_id"] == "test-order-123"
        assert request.metadata["customer_name"] == "John Doe"
        assert request.metadata["item_count"] == 2
    
    def test_payment_request_without_customer_name(self):
        """Test creating payment request without customer name."""
        request = PayStackPaymentRequest.from_order(
            order_id="test-order-456",
            customer_email="test@example.com",
            customer_name=None,
            matched_items=[{"product_name": "Item", "quantity": 1, "unit_price": 100.0}],
            total_amount=100.0
        )
        
        assert request.metadata["customer_name"] == ""
    
    def test_payment_response_success(self):
        """Test successful payment response."""
        response = PayStackPaymentResponse(
            success=True,
            authorization_url="https://checkout.paystack.com/abc123",
            access_code="abc123",
            reference="order-123",
            expires_at=datetime.utcnow() + timedelta(hours=24),
            message="Authorization URL created"
        )
        
        assert response.success is True
        assert response.authorization_url == "https://checkout.paystack.com/abc123"
        assert response.access_code == "abc123"
    
    def test_payment_response_failure(self):
        """Test failed payment response."""
        response = PayStackPaymentResponse(
            success=False,
            message="Invalid API key",
            error_code="AUTHENTICATION_ERROR"
        )
        
        assert response.success is False
        assert response.error_code == "AUTHENTICATION_ERROR"
    
    def test_webhook_event_charge_success(self):
        """Test parsing successful charge webhook event."""
        event = PayStackWebhookEvent(
            event="charge.success",
            data={
                "reference": "order-test-123",
                "status": "success",
                "amount": 150000,
                "customer": {"email": "test@example.com"},
                "paid_at": "2024-01-15T10:30:00Z"
            }
        )
        
        assert event.event_type == "charge.success"
        assert event.reference == "order-test-123"
        assert event.status == "success"
        assert event.amount == 150000
        assert event.order_id == "test-123"
        assert event.customer_email == "test@example.com"
        assert event.is_successful_payment() is True
        assert event.is_failed_payment() is False
    
    def test_webhook_event_charge_failed(self):
        """Test parsing failed charge webhook event."""
        event = PayStackWebhookEvent(
            event="charge.failed",
            data={
                "reference": "order-test-456",
                "status": "failed",
                "amount": 50000
            }
        )
        
        assert event.is_successful_payment() is False
        assert event.is_failed_payment() is True
    
    def test_webhook_event_order_id_from_metadata(self):
        """Test extracting order ID from metadata when reference doesn't have prefix."""
        event = PayStackWebhookEvent(
            event="charge.success",
            data={
                "reference": "custom-ref-123",
                "status": "success",
                "metadata": {"order_id": "extracted-order-id"}
            }
        )
        
        assert event.order_id == "extracted-order-id"
    
    def test_verify_response_success(self):
        """Test successful verification response."""
        response = PayStackVerifyResponse(
            success=True,
            status=PayStackTransactionStatus.SUCCESS,
            amount=150000,
            reference="order-123",
            paid_at=datetime.utcnow(),
            message="Verification successful"
        )
        
        assert response.success is True
        assert response.status == PayStackTransactionStatus.SUCCESS


class TestPayStackClient:
    """Test PayStack API client."""
    
    def test_client_initialization(self):
        """Test client initialization with valid API key."""
        client = PayStackClient(
            api_key="sk_test_xxxxx",
            base_url="https://api.paystack.co",
            timeout=30,
            max_retries=3
        )
        
        assert client.api_key == "sk_test_xxxxx"
        assert client.base_url == "https://api.paystack.co"
        assert client.timeout == 30
        assert client.max_retries == 3
    
    def test_client_initialization_no_api_key(self):
        """Test client initialization fails without API key."""
        with pytest.raises(ValueError, match="API key is required"):
            PayStackClient(api_key="")
    
    def test_client_strips_trailing_slash(self):
        """Test that base URL trailing slash is stripped."""
        client = PayStackClient(
            api_key="sk_test_xxxxx",
            base_url="https://api.paystack.co/"
        )
        
        assert client.base_url == "https://api.paystack.co"
    
    @patch('urllib.request.urlopen')
    def test_initialize_payment_success(self, mock_urlopen):
        """Test successful payment initialization."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": True,
            "message": "Authorization URL created",
            "data": {
                "authorization_url": "https://checkout.paystack.com/test123",
                "access_code": "test123",
                "reference": "order-test-123"
            }
        }).encode("utf-8")
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        client = PayStackClient(api_key="sk_test_xxxxx")
        request = PayStackPaymentRequest(
            email="test@example.com",
            amount=150000,
            reference="order-test-123",
            currency="NGN"
        )
        
        response = client.initialize_payment(request)
        
        assert response.success is True
        assert response.authorization_url == "https://checkout.paystack.com/test123"
        assert response.access_code == "test123"
        assert response.reference == "order-test-123"
    
    @patch('urllib.request.urlopen')
    def test_initialize_payment_failure(self, mock_urlopen):
        """Test payment initialization failure."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": False,
            "message": "Duplicate Transaction Reference"
        }).encode("utf-8")
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        client = PayStackClient(api_key="sk_test_xxxxx")
        request = PayStackPaymentRequest(
            email="test@example.com",
            amount=150000,
            reference="order-duplicate",
            currency="NGN"
        )
        
        response = client.initialize_payment(request)
        
        assert response.success is False
        assert "Duplicate" in response.message
    
    @patch('urllib.request.urlopen')
    def test_verify_transaction_success(self, mock_urlopen):
        """Test successful transaction verification."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": True,
            "message": "Verification successful",
            "data": {
                "status": "success",
                "amount": 150000,
                "reference": "order-test-123",
                "paid_at": "2024-01-15T10:30:00Z"
            }
        }).encode("utf-8")
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        client = PayStackClient(api_key="sk_test_xxxxx")
        response = client.verify_transaction("order-test-123")
        
        assert response.success is True
        assert response.status == PayStackTransactionStatus.SUCCESS
        assert response.amount == 150000
    
    def test_validate_webhook_signature_valid(self):
        """Test webhook signature validation with valid signature."""
        secret_key = "sk_test_secret_key"
        payload = b'{"event": "charge.success", "data": {}}'
        
        expected_signature = hmac.new(
            secret_key.encode("utf-8"),
            payload,
            hashlib.sha512
        ).hexdigest()
        
        result = PayStackClient.validate_webhook_signature(
            payload=payload,
            signature=expected_signature,
            secret_key=secret_key
        )
        
        assert result is True
    
    def test_validate_webhook_signature_invalid(self):
        """Test webhook signature validation with invalid signature."""
        result = PayStackClient.validate_webhook_signature(
            payload=b'{"event": "charge.success"}',
            signature="invalid_signature",
            secret_key="sk_test_secret"
        )
        
        assert result is False
    
    def test_validate_webhook_signature_empty_payload(self):
        """Test webhook signature validation with empty payload."""
        result = PayStackClient.validate_webhook_signature(
            payload=b'',
            signature="some_signature",
            secret_key="sk_test_secret"
        )
        
        assert result is False
    
    def test_parse_webhook_event(self):
        """Test parsing webhook event from bytes."""
        payload = b'{"event": "charge.success", "data": {"reference": "order-123", "status": "success"}}'
        
        event = PayStackClient.parse_webhook_event(payload)
        
        assert event.event == "charge.success"
        assert event.reference == "order-123"
        assert event.status == "success"
    
    def test_parse_webhook_event_invalid_json(self):
        """Test parsing webhook event with invalid JSON."""
        payload = b'invalid json'
        
        with pytest.raises(PayStackValidationError, match="Invalid webhook payload"):
            PayStackClient.parse_webhook_event(payload)


class TestPayStackErrors:
    """Test PayStack error classes."""
    
    def test_paystack_error(self):
        """Test base PayStack error."""
        error = PayStackError(
            message="Something went wrong",
            error_code="GENERIC_ERROR",
            status_code=500
        )
        
        assert str(error) == "Something went wrong"
        assert error.error_code == "GENERIC_ERROR"
        assert error.status_code == 500
    
    def test_authentication_error(self):
        """Test authentication error."""
        error = PayStackAuthenticationError(
            message="Invalid API key",
            error_code="AUTHENTICATION_ERROR",
            status_code=401
        )
        
        assert isinstance(error, PayStackError)
        assert error.status_code == 401
    
    def test_rate_limit_error(self):
        """Test rate limit error."""
        error = PayStackRateLimitError(
            message="Rate limit exceeded",
            error_code="RATE_LIMIT_ERROR",
            status_code=429
        )
        
        assert isinstance(error, PayStackError)
        assert error.status_code == 429
    
    def test_validation_error(self):
        """Test validation error."""
        error = PayStackValidationError(
            message="Invalid email address",
            error_code="VALIDATION_ERROR",
            status_code=400
        )
        
        assert isinstance(error, PayStackError)
        assert error.status_code == 400


class TestPayStackClientRetry:
    """Test PayStack client retry logic."""
    
    @patch('time.sleep')
    @patch('urllib.request.urlopen')
    def test_retry_on_server_error(self, mock_urlopen, mock_sleep):
        """Test that client retries on server error."""
        # First call fails with 500, second succeeds
        error_response = MagicMock()
        error_response.code = 500
        error_response.read.return_value = b'{"message": "Internal Server Error"}'
        error_response.fp = error_response
        
        success_response = MagicMock()
        success_response.read.return_value = json.dumps({
            "status": True,
            "message": "Success",
            "data": {
                "authorization_url": "https://checkout.paystack.com/test",
                "access_code": "test",
                "reference": "order-123"
            }
        }).encode("utf-8")
        success_response.__enter__ = Mock(return_value=success_response)
        success_response.__exit__ = Mock(return_value=False)
        
        mock_urlopen.side_effect = [
            urllib.error.HTTPError(
                url="https://api.paystack.co/transaction/initialize",
                code=500,
                msg="Internal Server Error",
                hdrs={},
                fp=error_response
            ),
            success_response
        ]
        
        client = PayStackClient(api_key="sk_test_xxxxx", max_retries=3)
        request = PayStackPaymentRequest(
            email="test@example.com",
            amount=150000,
            reference="order-123",
            currency="NGN"
        )
        
        response = client.initialize_payment(request)
        
        assert response.success is True
        assert mock_urlopen.call_count == 2
        mock_sleep.assert_called_once()
