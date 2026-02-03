"""
PayStack API client for payment integration.

This module provides a client class for interacting with the PayStack API,
including payment initialization, verification, and webhook signature validation.
"""

import hashlib
import hmac
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from aws_lambda_powertools import Logger

from src.paystack.models import (
    PayStackPaymentRequest,
    PayStackPaymentResponse,
    PayStackVerifyResponse,
    PayStackWebhookEvent,
    PayStackTransactionStatus,
)


logger = Logger(child=True)


class PayStackError(Exception):
    """Base exception for PayStack errors."""
    
    def __init__(self, message: str, error_code: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class PayStackAuthenticationError(PayStackError):
    """Exception for authentication failures."""
    pass


class PayStackRateLimitError(PayStackError):
    """Exception for rate limit errors."""
    pass


class PayStackValidationError(PayStackError):
    """Exception for validation errors."""
    pass


class PayStackClient:
    """
    PayStack API client for payment operations.
    
    This client provides methods for initializing payments, verifying transactions,
    and validating webhook signatures with built-in retry logic using exponential backoff.
    
    Example:
        client = PayStackClient(api_key="sk_live_xxx", base_url="https://api.paystack.co")
        
        # Create a payment link
        request = PayStackPaymentRequest.from_order(
            order_id="order-123",
            customer_email="customer@example.com",
            customer_name="John Doe",
            matched_items=items,
            total_amount=1500.00
        )
        response = client.initialize_payment(request)
        
        # Verify a transaction
        verify_response = client.verify_transaction("order-123")
    
    Attributes:
        api_key: PayStack API secret key
        base_url: PayStack API base URL
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts for failed requests
        expiration_hours: Hours until payment link expires (default: 24)
    """
    
    DEFAULT_BASE_URL = "https://api.paystack.co"
    DEFAULT_TIMEOUT = 30
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_EXPIRATION_HOURS = 24
    
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        expiration_hours: int = DEFAULT_EXPIRATION_HOURS
    ):
        """
        Initialize PayStack client.
        
        Args:
            api_key: PayStack API secret key
            base_url: PayStack API base URL
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            expiration_hours: Hours until payment link expires
        """
        if not api_key:
            raise ValueError("PayStack API key must not be empty")
        
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.expiration_hours = expiration_hours
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        retry_count: int = 0
    ) -> Dict[str, Any]:
        """
        Make HTTP request to PayStack API with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: Request body data
            retry_count: Current retry attempt
            
        Returns:
            API response data
            
        Raises:
            PayStackError: For API errors
            PayStackAuthenticationError: For authentication failures
            PayStackRateLimitError: For rate limit errors
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8") if data else None,
                headers=headers,
                method=method
            )
            
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))
                return response_data
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            
            # Parse error response
            try:
                error_data = json.loads(error_body)
                error_message = error_data.get("message", str(e))
            except json.JSONDecodeError:
                error_message = error_body or str(e)
            
            # Handle specific error codes
            if e.code == 401:
                raise PayStackAuthenticationError(
                    f"Authentication failed: {error_message}",
                    error_code="AUTHENTICATION_ERROR",
                    status_code=e.code
                )
            
            if e.code == 429:
                # Rate limited - retry with exponential backoff
                if retry_count < self.max_retries:
                    wait_time = (2 ** retry_count) + (retry_count * 0.5)
                    logger.warning(
                        "Rate limited, retrying",
                        extra={"attempt": retry_count + 1, "wait_time": wait_time}
                    )
                    time.sleep(wait_time)
                    return self._make_request(method, endpoint, data, retry_count + 1)
                
                raise PayStackRateLimitError(
                    f"Rate limit exceeded: {error_message}",
                    error_code="RATE_LIMIT_ERROR",
                    status_code=e.code
                )
            
            if e.code in (400, 422):
                raise PayStackValidationError(
                    f"Validation error: {error_message}",
                    error_code="VALIDATION_ERROR",
                    status_code=e.code
                )
            
            # Server error - retry with exponential backoff
            if e.code >= 500 and retry_count < self.max_retries:
                wait_time = 2 ** retry_count
                logger.warning(
                    "Server error, retrying",
                    extra={"attempt": retry_count + 1, "status": e.code, "wait_time": wait_time}
                )
                time.sleep(wait_time)
                return self._make_request(method, endpoint, data, retry_count + 1)
            
            raise PayStackError(
                f"API error: {error_message}",
                error_code="API_ERROR",
                status_code=e.code
            )
            
        except urllib.error.URLError as e:
            # Network error - retry with exponential backoff
            if retry_count < self.max_retries:
                wait_time = 2 ** retry_count
                logger.warning(
                    "Network error, retrying",
                    extra={"attempt": retry_count + 1, "error": str(e), "wait_time": wait_time}
                )
                time.sleep(wait_time)
                return self._make_request(method, endpoint, data, retry_count + 1)
            
            raise PayStackError(
                f"Network error: {str(e)}",
                error_code="NETWORK_ERROR"
            )
    
    def initialize_payment(
        self,
        request: PayStackPaymentRequest
    ) -> PayStackPaymentResponse:
        """
        Initialize a payment transaction.
        
        Creates a payment link with itemized breakdown that expires after
        the configured expiration period (default: 24 hours).
        
        Args:
            request: Payment initialization request
            
        Returns:
            PayStackPaymentResponse with authorization URL and access code
        """
        # Build PayStack API payload
        payload = {
            "email": request.email,
            "amount": request.amount,
            "currency": request.currency,
            "reference": request.reference,
        }
        
        if request.callback_url:
            payload["callback_url"] = request.callback_url
        
        # Add metadata with itemized breakdown
        if request.metadata:
            payload["metadata"] = request.metadata
        
        logger.info(
            "Initializing PayStack payment",
            extra={
                "reference": request.reference,
                "amount": request.amount,
                "email": request.email[:3] + "***"  # Mask email
            }
        )
        
        try:
            response_data = self._make_request("POST", "/transaction/initialize", payload)
            
            if response_data.get("status"):
                data = response_data.get("data", {})
                expires_at = datetime.now(timezone.utc) + timedelta(hours=self.expiration_hours)
                
                logger.info(
                    "Payment initialized successfully",
                    extra={
                        "reference": data.get("reference"),
                        "access_code": data.get("access_code", "")[:8] + "***"
                    }
                )
                
                return PayStackPaymentResponse(
                    success=True,
                    authorization_url=data.get("authorization_url"),
                    access_code=data.get("access_code"),
                    reference=data.get("reference"),
                    expires_at=expires_at,
                    message=response_data.get("message")
                )
            else:
                logger.error(
                    "Payment initialization failed",
                    extra={"error_message": response_data.get("message")}
                )
                return PayStackPaymentResponse(
                    success=False,
                    message=response_data.get("message"),
                    error_code="INITIALIZATION_FAILED"
                )
                
        except PayStackError as e:
            logger.error(
                "PayStack API error during initialization",
                extra={"error": str(e), "error_code": e.error_code}
            )
            return PayStackPaymentResponse(
                success=False,
                message=str(e),
                error_code=e.error_code
            )
    
    def verify_transaction(self, reference: str) -> PayStackVerifyResponse:
        """
        Verify a transaction status.
        
        Args:
            reference: Transaction reference to verify
            
        Returns:
            PayStackVerifyResponse with transaction status and details
        """
        logger.info("Verifying transaction", extra={"reference": reference})
        
        try:
            response_data = self._make_request("GET", f"/transaction/verify/{reference}")
            
            if response_data.get("status"):
                data = response_data.get("data", {})
                status_str = data.get("status", "").lower()
                
                # Map PayStack status to enum
                status_map = {
                    "success": PayStackTransactionStatus.SUCCESS,
                    "failed": PayStackTransactionStatus.FAILED,
                    "abandoned": PayStackTransactionStatus.ABANDONED,
                    "pending": PayStackTransactionStatus.PENDING,
                    "reversed": PayStackTransactionStatus.REVERSED,
                }
                status = status_map.get(status_str, PayStackTransactionStatus.PENDING)
                
                # Parse paid_at timestamp
                paid_at = None
                paid_at_str = data.get("paid_at")
                if paid_at_str:
                    try:
                        paid_at = datetime.fromisoformat(paid_at_str.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        pass
                
                logger.info(
                    "Transaction verified",
                    extra={
                        "reference": reference,
                        "status": status_str,
                        "amount": data.get("amount")
                    }
                )
                
                return PayStackVerifyResponse(
                    success=True,
                    status=status,
                    amount=data.get("amount"),
                    reference=reference,
                    paid_at=paid_at,
                    message=response_data.get("message")
                )
            else:
                return PayStackVerifyResponse(
                    success=False,
                    message=response_data.get("message"),
                    error_code="VERIFICATION_FAILED"
                )
                
        except PayStackError as e:
            logger.error(
                "PayStack API error during verification",
                extra={"error": str(e), "error_code": e.error_code}
            )
            return PayStackVerifyResponse(
                success=False,
                message=str(e),
                error_code=e.error_code
            )
    
    @staticmethod
    def validate_webhook_signature(
        payload: bytes,
        signature: str,
        secret_key: str
    ) -> bool:
        """
        Validate a PayStack webhook signature.
        
        PayStack signs webhook payloads using HMAC SHA-512 with your secret key.
        
        Args:
            payload: Raw webhook request body as bytes
            signature: Signature from x-paystack-signature header
            secret_key: PayStack secret key for signature verification
            
        Returns:
            True if signature is valid, False otherwise
        """
        if not payload or not signature or not secret_key:
            return False
        
        try:
            expected_signature = hmac.new(
                secret_key.encode("utf-8"),
                payload,
                hashlib.sha512
            ).hexdigest()
            
            return hmac.compare_digest(expected_signature.lower(), signature.lower())
        except (TypeError, ValueError):
            return False
    
    @staticmethod
    def parse_webhook_event(payload: bytes) -> PayStackWebhookEvent:
        """
        Parse a webhook event from raw payload.
        
        Args:
            payload: Raw webhook request body as bytes
            
        Returns:
            PayStackWebhookEvent instance
            
        Raises:
            PayStackValidationError: If payload is invalid
        """
        try:
            data = json.loads(payload.decode("utf-8"))
            return PayStackWebhookEvent(
                event=data.get("event", ""),
                data=data.get("data", {})
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise PayStackValidationError(
                f"Invalid webhook payload: {str(e)}",
                error_code="INVALID_PAYLOAD"
            )
