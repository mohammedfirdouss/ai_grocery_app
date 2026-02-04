"""
Security controls and utilities for the AI Grocery App.

This module provides:
- Input validation and sanitization helpers
- Rate limiting utilities
- Audit logging for security events
- Security decorators for data operations
"""

import functools
import hashlib
import html
import json
import logging
import re
import time
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, TypeVar, Union

from pydantic import BaseModel, Field, validator


# Type variable for generic function decorators
F = TypeVar('F', bound=Callable[..., Any])


# ==============================================================================
# Input Validation and Sanitization
# ==============================================================================


class InputValidationError(Exception):
    """Exception raised when input validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        self.message = message
        self.field = field
        self.value = value
        super().__init__(self.message)


class SanitizationConfig(BaseModel):
    """Configuration for input sanitization."""
    
    max_string_length: int = Field(default=10000, ge=1)
    allow_html: bool = Field(default=False)
    strip_whitespace: bool = Field(default=True)
    normalize_unicode: bool = Field(default=True)
    remove_null_bytes: bool = Field(default=True)
    max_list_length: int = Field(default=1000, ge=1)
    max_recursion_depth: int = Field(default=10, ge=1)


# Patterns for common validation
EMAIL_PATTERN: Pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
UUID_PATTERN: Pattern = re.compile(r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$')
PHONE_PATTERN: Pattern = re.compile(r'^\+?[1-9]\d{1,14}$')

# SQL/NoSQL injection patterns to detect
INJECTION_PATTERNS: List[Pattern] = [
    re.compile(r'[\'";\-\-]', re.IGNORECASE),  # Basic SQL injection
    re.compile(r'\$where|\$regex|\$ne|\$gt|\$lt', re.IGNORECASE),  # MongoDB injection
    re.compile(r'<script|javascript:|data:', re.IGNORECASE),  # XSS patterns
]

# Characters that are potentially dangerous in various contexts
DANGEROUS_CHARS: Set[str] = {'\x00', '\x0b', '\x0c', '\x1b'}


def sanitize_string(
    value: str,
    config: Optional[SanitizationConfig] = None
) -> str:
    """
    Sanitize a string value by removing or escaping dangerous content.
    
    Args:
        value: The string to sanitize.
        config: Optional sanitization configuration.
        
    Returns:
        Sanitized string.
        
    Raises:
        InputValidationError: If the input cannot be safely sanitized.
    """
    if config is None:
        config = SanitizationConfig()
    
    if not isinstance(value, str):
        raise InputValidationError("Value must be a string", value=value)
    
    # Remove null bytes and other dangerous characters
    if config.remove_null_bytes:
        for char in DANGEROUS_CHARS:
            value = value.replace(char, '')
    
    # Strip whitespace
    if config.strip_whitespace:
        value = value.strip()
    
    # Enforce maximum length
    if len(value) > config.max_string_length:
        raise InputValidationError(
            f"String exceeds maximum length of {config.max_string_length}",
            value=f"{value[:50]}..."
        )
    
    # HTML escape if HTML is not allowed
    if not config.allow_html:
        value = html.escape(value)
    
    return value


def sanitize_dict(
    data: Dict[str, Any],
    config: Optional[SanitizationConfig] = None,
    _depth: int = 0
) -> Dict[str, Any]:
    """
    Recursively sanitize a dictionary.
    
    Args:
        data: The dictionary to sanitize.
        config: Optional sanitization configuration.
        _depth: Current recursion depth (internal use).
        
    Returns:
        Sanitized dictionary.
        
    Raises:
        InputValidationError: If the input cannot be safely sanitized.
    """
    if config is None:
        config = SanitizationConfig()
    
    if _depth > config.max_recursion_depth:
        raise InputValidationError(
            f"Dictionary exceeds maximum recursion depth of {config.max_recursion_depth}"
        )
    
    result: Dict[str, Any] = {}
    
    for key, value in data.items():
        # Sanitize the key
        sanitized_key = sanitize_string(str(key), config)
        
        # Sanitize the value based on its type
        if isinstance(value, str):
            result[sanitized_key] = sanitize_string(value, config)
        elif isinstance(value, dict):
            result[sanitized_key] = sanitize_dict(value, config, _depth + 1)
        elif isinstance(value, list):
            result[sanitized_key] = sanitize_list(value, config, _depth + 1)
        elif isinstance(value, (int, float, bool, type(None))):
            result[sanitized_key] = value
        else:
            # Convert other types to string and sanitize
            result[sanitized_key] = sanitize_string(str(value), config)
    
    return result


def sanitize_list(
    data: List[Any],
    config: Optional[SanitizationConfig] = None,
    _depth: int = 0
) -> List[Any]:
    """
    Recursively sanitize a list.
    
    Args:
        data: The list to sanitize.
        config: Optional sanitization configuration.
        _depth: Current recursion depth (internal use).
        
    Returns:
        Sanitized list.
        
    Raises:
        InputValidationError: If the input cannot be safely sanitized.
    """
    if config is None:
        config = SanitizationConfig()
    
    if _depth > config.max_recursion_depth:
        raise InputValidationError(
            f"List exceeds maximum recursion depth of {config.max_recursion_depth}"
        )
    
    if len(data) > config.max_list_length:
        raise InputValidationError(
            f"List exceeds maximum length of {config.max_list_length}"
        )
    
    result: List[Any] = []
    
    for value in data:
        if isinstance(value, str):
            result.append(sanitize_string(value, config))
        elif isinstance(value, dict):
            result.append(sanitize_dict(value, config, _depth + 1))
        elif isinstance(value, list):
            result.append(sanitize_list(value, config, _depth + 1))
        elif isinstance(value, (int, float, bool, type(None))):
            result.append(value)
        else:
            result.append(sanitize_string(str(value), config))
    
    return result


def validate_email(email: str) -> bool:
    """
    Validate email format.
    
    Args:
        email: Email address to validate.
        
    Returns:
        True if valid, False otherwise.
    """
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_PATTERN.match(email.strip()))


def validate_uuid(uuid_str: str) -> bool:
    """
    Validate UUID format.
    
    Args:
        uuid_str: UUID string to validate.
        
    Returns:
        True if valid, False otherwise.
    """
    if not uuid_str or not isinstance(uuid_str, str):
        return False
    return bool(UUID_PATTERN.match(uuid_str.strip()))


def detect_injection_patterns(value: str) -> List[str]:
    """
    Detect potential injection patterns in a string.
    
    Args:
        value: String to check for injection patterns.
        
    Returns:
        List of detected pattern descriptions.
    """
    detected: List[str] = []
    
    if not isinstance(value, str):
        return detected
    
    for pattern in INJECTION_PATTERNS:
        if pattern.search(value):
            detected.append(pattern.pattern)
    
    return detected


# ==============================================================================
# Rate Limiting
# ==============================================================================


class RateLimitConfig(BaseModel):
    """Configuration for rate limiting."""
    
    requests_per_second: float = Field(default=10.0, gt=0)
    burst_size: int = Field(default=20, ge=1)
    window_seconds: int = Field(default=60, ge=1)


class RateLimiter:
    """
    Token bucket rate limiter for API operations.
    
    This implementation uses the token bucket algorithm to control
    the rate of operations with support for bursting.
    """
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        """
        Initialize the rate limiter.
        
        Args:
            config: Optional rate limit configuration.
        """
        self.config = config or RateLimitConfig()
        self._tokens: float = float(self.config.burst_size)
        self._last_update: float = time.time()
        self._request_counts: Dict[str, List[float]] = {}
    
    def _refill_tokens(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_update
        self._tokens = min(
            float(self.config.burst_size),
            self._tokens + elapsed * self.config.requests_per_second
        )
        self._last_update = now
    
    def acquire(self, key: Optional[str] = None) -> bool:
        """
        Attempt to acquire a rate limit token.
        
        Args:
            key: Optional key for per-client rate limiting.
            
        Returns:
            True if the request is allowed, False if rate limited.
        """
        self._refill_tokens()
        
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        
        return False
    
    def get_remaining_tokens(self) -> int:
        """Get the current number of available tokens."""
        self._refill_tokens()
        return int(self._tokens)
    
    def reset(self) -> None:
        """Reset the rate limiter to initial state."""
        self._tokens = float(self.config.burst_size)
        self._last_update = time.time()
        self._request_counts.clear()


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[float] = None
    ):
        self.message = message
        self.retry_after = retry_after
        super().__init__(self.message)


def rate_limit(
    requests_per_second: float = 10.0,
    burst_size: int = 20
) -> Callable[[F], F]:
    """
    Decorator to apply rate limiting to a function.
    
    Args:
        requests_per_second: Maximum sustained request rate.
        burst_size: Maximum burst size allowed.
        
    Returns:
        Decorated function with rate limiting.
    """
    config = RateLimitConfig(
        requests_per_second=requests_per_second,
        burst_size=burst_size
    )
    limiter = RateLimiter(config)
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not limiter.acquire():
                raise RateLimitExceeded(
                    f"Rate limit exceeded for {func.__name__}",
                    retry_after=1.0 / requests_per_second
                )
            return func(*args, **kwargs)
        return wrapper  # type: ignore
    return decorator


# ==============================================================================
# Audit Logging
# ==============================================================================


class SecurityEventType(str, Enum):
    """Types of security events for audit logging."""
    
    # Authentication events
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    AUTH_LOGOUT = "auth_logout"
    TOKEN_REFRESH = "token_refresh"
    
    # Authorization events
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    PERMISSION_CHANGE = "permission_change"
    
    # Data access events
    DATA_READ = "data_read"
    DATA_WRITE = "data_write"
    DATA_DELETE = "data_delete"
    DATA_EXPORT = "data_export"
    
    # Security events
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INVALID_INPUT = "invalid_input"
    INJECTION_ATTEMPT = "injection_attempt"
    ENCRYPTION_OPERATION = "encryption_operation"
    DECRYPTION_OPERATION = "decryption_operation"
    KEY_ACCESS = "key_access"
    
    # System events
    CONFIG_CHANGE = "config_change"
    ADMIN_ACTION = "admin_action"
    SYSTEM_ERROR = "system_error"


class SecurityEvent(BaseModel):
    """Model for security audit events."""
    
    event_id: str = Field(..., description="Unique event identifier")
    event_type: SecurityEventType = Field(..., description="Type of security event")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user_id: Optional[str] = Field(None, description="User identifier if applicable")
    resource_type: Optional[str] = Field(None, description="Type of resource accessed")
    resource_id: Optional[str] = Field(None, description="Identifier of resource accessed")
    action: str = Field(..., description="Action performed")
    outcome: str = Field(..., description="Outcome of the action (success/failure)")
    ip_address: Optional[str] = Field(None, description="Client IP address")
    user_agent: Optional[str] = Field(None, description="Client user agent")
    correlation_id: Optional[str] = Field(None, description="Request correlation ID")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional event details")
    
    @validator('details')
    def sanitize_details(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure no sensitive data in details field."""
        sensitive_keys = {'password', 'secret', 'token', 'key', 'credential', 'api_key'}
        sanitized = {}
        for key, value in v.items():
            if any(s in key.lower() for s in sensitive_keys):
                sanitized[key] = '[REDACTED]'
            else:
                sanitized[key] = value
        return sanitized


class AuditLogger:
    """
    Security audit logger for compliance and monitoring.
    
    Logs security-relevant events in a structured format suitable
    for compliance auditing and security monitoring.
    """
    
    def __init__(
        self,
        logger_name: str = "security.audit",
        log_level: int = logging.INFO,
        include_sensitive: bool = False
    ):
        """
        Initialize the audit logger.
        
        Args:
            logger_name: Name for the logger instance.
            log_level: Logging level for audit events.
            include_sensitive: Whether to include sensitive data in logs.
        """
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(log_level)
        self.include_sensitive = include_sensitive
        self._event_counter: int = 0
    
    def _generate_event_id(self) -> str:
        """Generate a unique event ID."""
        self._event_counter += 1
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        return f"SEC-{timestamp}-{self._event_counter:06d}"
    
    def log_event(
        self,
        event_type: SecurityEventType,
        action: str,
        outcome: str,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        correlation_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> SecurityEvent:
        """
        Log a security event.
        
        Args:
            event_type: Type of security event.
            action: Action that was performed.
            outcome: Outcome of the action.
            user_id: Optional user identifier.
            resource_type: Optional resource type.
            resource_id: Optional resource identifier.
            ip_address: Optional client IP address.
            user_agent: Optional client user agent.
            correlation_id: Optional correlation ID for request tracing.
            details: Optional additional details.
            
        Returns:
            The created SecurityEvent.
        """
        event = SecurityEvent(
            event_id=self._generate_event_id(),
            event_type=event_type,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            outcome=outcome,
            ip_address=ip_address,
            user_agent=user_agent,
            correlation_id=correlation_id,
            details=details or {}
        )
        
        # Log the event
        log_data = event.model_dump()
        log_data['timestamp'] = event.timestamp.isoformat()
        
        self.logger.info(
            f"SECURITY_EVENT: {json.dumps(log_data, default=str)}"
        )
        
        return event
    
    def log_auth_success(
        self,
        user_id: str,
        auth_method: str,
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> SecurityEvent:
        """Log successful authentication."""
        return self.log_event(
            event_type=SecurityEventType.AUTH_SUCCESS,
            action=f"authenticate:{auth_method}",
            outcome="success",
            user_id=user_id,
            ip_address=ip_address,
            correlation_id=correlation_id,
            details={"auth_method": auth_method}
        )
    
    def log_auth_failure(
        self,
        user_id: Optional[str],
        auth_method: str,
        reason: str,
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> SecurityEvent:
        """Log failed authentication attempt."""
        return self.log_event(
            event_type=SecurityEventType.AUTH_FAILURE,
            action=f"authenticate:{auth_method}",
            outcome="failure",
            user_id=user_id,
            ip_address=ip_address,
            correlation_id=correlation_id,
            details={"auth_method": auth_method, "reason": reason}
        )
    
    def log_access_denied(
        self,
        user_id: str,
        resource_type: str,
        resource_id: str,
        action: str,
        reason: str,
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> SecurityEvent:
        """Log access denied event."""
        return self.log_event(
            event_type=SecurityEventType.ACCESS_DENIED,
            action=action,
            outcome="denied",
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            correlation_id=correlation_id,
            details={"reason": reason}
        )
    
    def log_data_access(
        self,
        user_id: str,
        resource_type: str,
        resource_id: str,
        operation: str,
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> SecurityEvent:
        """Log data access event."""
        event_type_map = {
            "read": SecurityEventType.DATA_READ,
            "write": SecurityEventType.DATA_WRITE,
            "delete": SecurityEventType.DATA_DELETE,
            "export": SecurityEventType.DATA_EXPORT,
        }
        event_type = event_type_map.get(operation, SecurityEventType.DATA_READ)
        
        return self.log_event(
            event_type=event_type,
            action=f"data:{operation}",
            outcome="success",
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            correlation_id=correlation_id
        )
    
    def log_rate_limit_exceeded(
        self,
        user_id: Optional[str],
        endpoint: str,
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> SecurityEvent:
        """Log rate limit exceeded event."""
        return self.log_event(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
            action=f"access:{endpoint}",
            outcome="blocked",
            user_id=user_id,
            ip_address=ip_address,
            correlation_id=correlation_id,
            details={"endpoint": endpoint}
        )
    
    def log_invalid_input(
        self,
        user_id: Optional[str],
        field: str,
        reason: str,
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> SecurityEvent:
        """Log invalid input event."""
        return self.log_event(
            event_type=SecurityEventType.INVALID_INPUT,
            action="validate:input",
            outcome="invalid",
            user_id=user_id,
            ip_address=ip_address,
            correlation_id=correlation_id,
            details={"field": field, "reason": reason}
        )
    
    def log_injection_attempt(
        self,
        user_id: Optional[str],
        field: str,
        patterns_detected: List[str],
        ip_address: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> SecurityEvent:
        """Log potential injection attempt."""
        return self.log_event(
            event_type=SecurityEventType.INJECTION_ATTEMPT,
            action="validate:injection_check",
            outcome="blocked",
            user_id=user_id,
            ip_address=ip_address,
            correlation_id=correlation_id,
            details={"field": field, "patterns": patterns_detected}
        )
    
    def log_encryption_operation(
        self,
        user_id: Optional[str],
        operation: str,
        key_id: str,
        resource_type: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> SecurityEvent:
        """Log encryption/decryption operation."""
        event_type = (
            SecurityEventType.ENCRYPTION_OPERATION
            if operation == "encrypt"
            else SecurityEventType.DECRYPTION_OPERATION
        )
        
        return self.log_event(
            event_type=event_type,
            action=f"crypto:{operation}",
            outcome="success",
            user_id=user_id,
            resource_type=resource_type,
            correlation_id=correlation_id,
            details={"key_id": mask_key_id(key_id)}
        )


def mask_key_id(key_id: str) -> str:
    """Mask a KMS key ID for logging purposes."""
    if not key_id:
        return "[NONE]"
    if len(key_id) <= 8:
        return "*" * len(key_id)
    return key_id[:4] + "*" * (len(key_id) - 8) + key_id[-4:]


# ==============================================================================
# Security Decorators
# ==============================================================================


def validate_input(
    sanitization_config: Optional[SanitizationConfig] = None,
    check_injection: bool = True
) -> Callable[[F], F]:
    """
    Decorator to validate and sanitize function inputs.
    
    Args:
        sanitization_config: Optional sanitization configuration.
        check_injection: Whether to check for injection patterns.
        
    Returns:
        Decorated function with input validation.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Sanitize keyword arguments
            sanitized_kwargs = {}
            for key, value in kwargs.items():
                if isinstance(value, str):
                    # Check for injection patterns
                    if check_injection:
                        patterns = detect_injection_patterns(value)
                        if patterns:
                            raise InputValidationError(
                                f"Potential injection detected in {key}",
                                field=key,
                                value=value[:50]
                            )
                    sanitized_kwargs[key] = sanitize_string(value, sanitization_config)
                elif isinstance(value, dict):
                    sanitized_kwargs[key] = sanitize_dict(value, sanitization_config)
                elif isinstance(value, list):
                    sanitized_kwargs[key] = sanitize_list(value, sanitization_config)
                else:
                    sanitized_kwargs[key] = value
            
            return func(*args, **sanitized_kwargs)
        return wrapper  # type: ignore
    return decorator


def audit_log(
    event_type: SecurityEventType,
    action: str,
    resource_type: Optional[str] = None
) -> Callable[[F], F]:
    """
    Decorator to automatically log security events for a function.
    
    Args:
        event_type: Type of security event to log.
        action: Action description for the audit log.
        resource_type: Optional resource type being accessed.
        
    Returns:
        Decorated function with automatic audit logging.
    """
    audit_logger = AuditLogger()
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            user_id = kwargs.get('user_id') or kwargs.get('customer_email')
            correlation_id = kwargs.get('correlation_id')
            resource_id = kwargs.get('order_id') or kwargs.get('resource_id')
            
            try:
                result = func(*args, **kwargs)
                audit_logger.log_event(
                    event_type=event_type,
                    action=action,
                    outcome="success",
                    user_id=str(user_id) if user_id else None,
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    correlation_id=str(correlation_id) if correlation_id else None
                )
                return result
            except Exception as e:
                audit_logger.log_event(
                    event_type=event_type,
                    action=action,
                    outcome="failure",
                    user_id=str(user_id) if user_id else None,
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    correlation_id=str(correlation_id) if correlation_id else None,
                    details={"error": str(e)}
                )
                raise
        return wrapper  # type: ignore
    return decorator


def require_encryption_validation(func: F) -> F:
    """
    Decorator to ensure encryption is properly configured before data operations.
    
    Validates that the KMS key ID is available before allowing sensitive
    data operations to proceed.
    """
    import os
    
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        kms_key_id = os.environ.get("KMS_KEY_ID") or kwargs.get("kms_key_id")
        
        if not kms_key_id:
            raise ValueError(
                "Encryption not configured: KMS_KEY_ID environment variable "
                "or kms_key_id parameter is required for this operation"
            )
        
        return func(*args, **kwargs)
    
    return wrapper  # type: ignore


# ==============================================================================
# Global Audit Logger Instance
# ==============================================================================

# Default audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
