"""
Tests for security controls module.
"""

import pytest
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

from models.security import (
    InputValidationError,
    SanitizationConfig,
    sanitize_string,
    sanitize_dict,
    sanitize_list,
    validate_email,
    validate_uuid,
    detect_injection_patterns,
    RateLimitConfig,
    RateLimiter,
    RateLimitExceeded,
    rate_limit,
    SecurityEventType,
    SecurityEvent,
    AuditLogger,
    get_audit_logger,
    validate_input,
    audit_log,
    require_encryption_validation,
)


class TestInputSanitization:
    """Tests for input sanitization functions."""
    
    def test_sanitize_string_basic(self):
        """Test basic string sanitization."""
        result = sanitize_string("  hello world  ")
        assert result == "hello world"
    
    def test_sanitize_string_html_escape(self):
        """Test HTML escaping in strings."""
        result = sanitize_string("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result
    
    def test_sanitize_string_allows_html_when_configured(self):
        """Test that HTML is allowed when configured."""
        config = SanitizationConfig(allow_html=True)
        result = sanitize_string("<b>bold</b>", config)
        assert result == "<b>bold</b>"
    
    def test_sanitize_string_removes_null_bytes(self):
        """Test removal of null bytes."""
        result = sanitize_string("hello\x00world")
        assert "\x00" not in result
        assert result == "helloworld"
    
    def test_sanitize_string_max_length(self):
        """Test maximum length enforcement."""
        config = SanitizationConfig(max_string_length=10)
        with pytest.raises(InputValidationError, match="exceeds maximum length"):
            sanitize_string("a" * 20, config)
    
    def test_sanitize_string_non_string_raises_error(self):
        """Test that non-string values raise error."""
        with pytest.raises(InputValidationError, match="must be a string"):
            sanitize_string(123)  # type: ignore
    
    def test_sanitize_dict_basic(self):
        """Test basic dictionary sanitization."""
        data = {"key": "  value  ", "nested": {"inner": "test"}}
        result = sanitize_dict(data)
        assert result["key"] == "value"
        assert result["nested"]["inner"] == "test"
    
    def test_sanitize_dict_preserves_types(self):
        """Test that primitive types are preserved."""
        data = {"string": "test", "int": 42, "float": 3.14, "bool": True, "null": None}
        result = sanitize_dict(data)
        assert result["string"] == "test"
        assert result["int"] == 42
        assert result["float"] == 3.14
        assert result["bool"] is True
        assert result["null"] is None
    
    def test_sanitize_dict_max_depth(self):
        """Test maximum recursion depth."""
        config = SanitizationConfig(max_recursion_depth=2)
        deep_dict = {"a": {"b": {"c": {"d": "too deep"}}}}
        with pytest.raises(InputValidationError, match="maximum recursion depth"):
            sanitize_dict(deep_dict, config)
    
    def test_sanitize_list_basic(self):
        """Test basic list sanitization."""
        data = ["  item1  ", "item2", 123, True]
        result = sanitize_list(data)
        assert result[0] == "item1"
        assert result[1] == "item2"
        assert result[2] == 123
        assert result[3] is True
    
    def test_sanitize_list_max_length(self):
        """Test maximum list length enforcement."""
        config = SanitizationConfig(max_list_length=3)
        data = [1, 2, 3, 4, 5]
        with pytest.raises(InputValidationError, match="maximum length"):
            sanitize_list(data, config)


class TestInputValidation:
    """Tests for input validation functions."""
    
    def test_validate_email_valid(self):
        """Test validation of valid emails."""
        assert validate_email("test@example.com") is True
        assert validate_email("user.name@domain.co.uk") is True
        assert validate_email("user+tag@example.org") is True
    
    def test_validate_email_invalid(self):
        """Test validation of invalid emails."""
        assert validate_email("not-an-email") is False
        assert validate_email("@example.com") is False
        assert validate_email("test@") is False
        assert validate_email("") is False
        assert validate_email(None) is False  # type: ignore
    
    def test_validate_uuid_valid(self):
        """Test validation of valid UUIDs."""
        assert validate_uuid("123e4567-e89b-12d3-a456-426614174000") is True
        assert validate_uuid("AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE") is True
    
    def test_validate_uuid_invalid(self):
        """Test validation of invalid UUIDs."""
        assert validate_uuid("not-a-uuid") is False
        assert validate_uuid("123e4567-e89b-12d3-a456") is False  # Too short
        assert validate_uuid("") is False
        assert validate_uuid(None) is False  # type: ignore
    
    def test_detect_injection_sql(self):
        """Test detection of SQL injection patterns."""
        # Test SQL injection with UNION SELECT
        patterns = detect_injection_patterns("1 UNION SELECT * FROM users --")
        assert len(patterns) > 0
        
        # Test SQL injection with OR condition
        patterns = detect_injection_patterns("' OR '1'='1")
        assert len(patterns) > 0
        
        # Test SQL injection with DROP
        patterns = detect_injection_patterns("; DROP TABLE users;")
        assert len(patterns) > 0
    
    def test_detect_injection_nosql(self):
        """Test detection of NoSQL injection patterns."""
        patterns = detect_injection_patterns('{"$where": "this.password == 1"}')
        assert len(patterns) > 0
        
        # Test $or injection
        patterns = detect_injection_patterns('{"$or": [{"a": 1}, {"b": 2}]}')
        assert len(patterns) > 0
    
    def test_detect_injection_xss(self):
        """Test detection of XSS patterns."""
        patterns = detect_injection_patterns("<script>alert('xss')</script>")
        assert len(patterns) > 0
        
        # Test event handler XSS
        patterns = detect_injection_patterns('<img src="x" onerror="alert(1)">')
        assert len(patterns) > 0
    
    def test_detect_injection_clean(self):
        """Test that clean strings don't trigger detection."""
        patterns = detect_injection_patterns("Hello, this is a normal string!")
        assert len(patterns) == 0
    
    def test_detect_injection_no_false_positives(self):
        """Test that normal strings with apostrophes don't trigger false positives."""
        # Names with apostrophes should be allowed
        patterns = detect_injection_patterns("O'Brien")
        assert len(patterns) == 0
        
        # Contractions should be allowed
        patterns = detect_injection_patterns("It's a beautiful day!")
        assert len(patterns) == 0
        
        # Grocery list with common characters should be allowed
        patterns = detect_injection_patterns("I need 2 bunches of bananas; please add milk too.")
        assert len(patterns) == 0


class TestRateLimiting:
    """Tests for rate limiting functionality."""
    
    def test_rate_limiter_allows_initial_requests(self):
        """Test that initial requests are allowed."""
        limiter = RateLimiter(RateLimitConfig(requests_per_second=10, burst_size=5))
        for _ in range(5):
            assert limiter.acquire() is True
    
    def test_rate_limiter_blocks_after_burst(self):
        """Test that requests are blocked after burst exhausted."""
        limiter = RateLimiter(RateLimitConfig(requests_per_second=10, burst_size=3))
        for _ in range(3):
            limiter.acquire()
        assert limiter.acquire() is False
    
    def test_rate_limiter_refills_tokens(self):
        """Test that tokens are refilled over time."""
        limiter = RateLimiter(RateLimitConfig(requests_per_second=100, burst_size=1))
        limiter.acquire()  # Exhaust the token
        assert limiter.acquire() is False  # Should be blocked
        
        # Wait for refill
        time.sleep(0.02)  # 20ms should give us at least 2 tokens
        assert limiter.acquire() is True
    
    def test_rate_limiter_reset(self):
        """Test reset functionality."""
        config = RateLimitConfig(requests_per_second=10, burst_size=5)
        limiter = RateLimiter(config)
        for _ in range(5):
            limiter.acquire()
        
        limiter.reset()
        assert limiter.get_remaining_tokens() == 5
    
    def test_rate_limit_decorator(self):
        """Test rate limit decorator."""
        call_count = 0
        
        @rate_limit(requests_per_second=100, burst_size=3)
        def limited_function():
            nonlocal call_count
            call_count += 1
            return call_count
        
        # First 3 calls should succeed
        for _ in range(3):
            limited_function()
        
        # 4th call should raise
        with pytest.raises(RateLimitExceeded):
            limited_function()


class TestAuditLogging:
    """Tests for audit logging functionality."""
    
    def test_security_event_creation(self):
        """Test creating a security event."""
        event = SecurityEvent(
            event_id="TEST-001",
            event_type=SecurityEventType.AUTH_SUCCESS,
            action="login",
            outcome="success",
            user_id="user123"
        )
        assert event.event_id == "TEST-001"
        assert event.event_type == SecurityEventType.AUTH_SUCCESS
        assert event.user_id == "user123"
    
    def test_security_event_sanitizes_details(self):
        """Test that security events sanitize sensitive data in details."""
        event = SecurityEvent(
            event_id="TEST-001",
            event_type=SecurityEventType.AUTH_SUCCESS,
            action="login",
            outcome="success",
            details={"password": "secret123", "username": "user123"}
        )
        assert event.details["password"] == "[REDACTED]"
        assert event.details["username"] == "user123"
    
    def test_audit_logger_log_event(self):
        """Test basic event logging."""
        logger = AuditLogger()
        event = logger.log_event(
            event_type=SecurityEventType.DATA_READ,
            action="read:order",
            outcome="success",
            user_id="user123",
            resource_type="Order",
            resource_id="order-001"
        )
        assert event.event_type == SecurityEventType.DATA_READ
        assert event.action == "read:order"
        assert event.outcome == "success"
    
    def test_audit_logger_log_auth_success(self):
        """Test logging successful authentication."""
        logger = AuditLogger()
        event = logger.log_auth_success(
            user_id="user123",
            auth_method="cognito",
            ip_address="192.168.1.1"
        )
        assert event.event_type == SecurityEventType.AUTH_SUCCESS
        assert event.user_id == "user123"
        assert event.ip_address == "192.168.1.1"
    
    def test_audit_logger_log_auth_failure(self):
        """Test logging failed authentication."""
        logger = AuditLogger()
        event = logger.log_auth_failure(
            user_id="user123",
            auth_method="cognito",
            reason="invalid_password",
            ip_address="192.168.1.1"
        )
        assert event.event_type == SecurityEventType.AUTH_FAILURE
        assert event.outcome == "failure"
        assert "invalid_password" in event.details["reason"]
    
    def test_audit_logger_log_rate_limit(self):
        """Test logging rate limit exceeded."""
        logger = AuditLogger()
        event = logger.log_rate_limit_exceeded(
            user_id="user123",
            endpoint="/api/orders",
            ip_address="192.168.1.1"
        )
        assert event.event_type == SecurityEventType.RATE_LIMIT_EXCEEDED
        assert event.outcome == "blocked"
    
    def test_audit_logger_log_injection_attempt(self):
        """Test logging injection attempt."""
        logger = AuditLogger()
        event = logger.log_injection_attempt(
            user_id="user123",
            field="raw_text",
            patterns_detected=["sql_injection"],
            ip_address="192.168.1.1"
        )
        assert event.event_type == SecurityEventType.INJECTION_ATTEMPT
        assert event.outcome == "blocked"
    
    def test_get_audit_logger_singleton(self):
        """Test that get_audit_logger returns the same instance."""
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()
        assert logger1 is logger2


class TestSecurityDecorators:
    """Tests for security decorators."""
    
    def test_validate_input_decorator(self):
        """Test input validation decorator."""
        @validate_input()
        def process_data(text: str) -> str:
            return text
        
        result = process_data(text="  hello world  ")
        assert result == "hello world"
    
    def test_validate_input_blocks_injection(self):
        """Test that input validation blocks injection attempts."""
        @validate_input(check_injection=True)
        def process_data(text: str) -> str:
            return text
        
        with pytest.raises(InputValidationError, match="injection"):
            process_data(text="'; DROP TABLE users; --")
    
    def test_audit_log_decorator(self):
        """Test audit logging decorator."""
        @audit_log(
            event_type=SecurityEventType.DATA_READ,
            action="read:order",
            resource_type="Order"
        )
        def get_order(order_id: str, user_id: str, correlation_id: str = None):
            return {"order_id": order_id}
        
        result = get_order(
            order_id="order-001",
            user_id="user123",
            correlation_id="corr-001"
        )
        assert result["order_id"] == "order-001"
    
    def test_require_encryption_validation_with_env_var(self):
        """Test require_encryption_validation with environment variable."""
        import os
        
        os.environ["KMS_KEY_ID"] = "test-key-id"
        try:
            @require_encryption_validation
            def encrypt_data(data: str) -> str:
                return data
            
            result = encrypt_data("test")
            assert result == "test"
        finally:
            del os.environ["KMS_KEY_ID"]
    
    def test_require_encryption_validation_without_key(self):
        """Test require_encryption_validation fails without key."""
        import os
        
        # Ensure env var is not set
        original = os.environ.pop("KMS_KEY_ID", None)
        try:
            @require_encryption_validation
            def encrypt_data(data: str) -> str:
                return data
            
            with pytest.raises(ValueError, match="Encryption not configured"):
                encrypt_data("test")
        finally:
            if original:
                os.environ["KMS_KEY_ID"] = original


class TestSecurityEventTypes:
    """Tests for security event type enumeration."""
    
    def test_all_event_types_exist(self):
        """Test that all expected event types exist."""
        expected_types = [
            "AUTH_SUCCESS",
            "AUTH_FAILURE",
            "ACCESS_GRANTED",
            "ACCESS_DENIED",
            "DATA_READ",
            "DATA_WRITE",
            "DATA_DELETE",
            "RATE_LIMIT_EXCEEDED",
            "INVALID_INPUT",
            "INJECTION_ATTEMPT",
            "ENCRYPTION_OPERATION",
            "DECRYPTION_OPERATION",
        ]
        
        for event_type in expected_types:
            assert hasattr(SecurityEventType, event_type)
    
    def test_event_type_values(self):
        """Test event type string values."""
        assert SecurityEventType.AUTH_SUCCESS.value == "auth_success"
        assert SecurityEventType.DATA_READ.value == "data_read"
