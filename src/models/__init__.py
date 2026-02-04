# Data models package

from src.models.core import (
    Order,
    Product,
    ExtractedItem,
    MatchedItem,
    PaymentLink,
    ProcessingEvent,
    ProcessingStatus,
    PaymentStatus,
    OrderDict,
    ProductDict,
    ExtractedItemDict,
    MatchedItemDict,
)
from src.models.encryption import (
    EncryptionHelper,
    EncryptionValidationError,
    DataProtector,
    generate_correlation_id,
    hash_email,
    mask_email,
    mask_key_id,
    mask_sensitive_data,
    require_encryption,
    validate_encrypted_field,
    create_encryption_context,
)
from src.models.security import (
    # Input validation and sanitization
    InputValidationError,
    SanitizationConfig,
    sanitize_string,
    sanitize_dict,
    sanitize_list,
    validate_email,
    validate_uuid,
    detect_injection_patterns,
    # Rate limiting
    RateLimitConfig,
    RateLimiter,
    RateLimitExceeded,
    rate_limit,
    # Audit logging
    SecurityEventType,
    SecurityEvent,
    AuditLogger,
    get_audit_logger,
    # Security decorators
    validate_input,
    audit_log,
    require_encryption_validation,
)

__all__ = [
    # Core models
    "Order",
    "Product",
    "ExtractedItem",
    "MatchedItem",
    "PaymentLink",
    "ProcessingEvent",
    "ProcessingStatus",
    "PaymentStatus",
    # Type aliases
    "OrderDict",
    "ProductDict",
    "ExtractedItemDict",
    "MatchedItemDict",
    # Encryption helpers
    "EncryptionHelper",
    "EncryptionValidationError",
    "DataProtector",
    "generate_correlation_id",
    "hash_email",
    "mask_email",
    "mask_key_id",
    "mask_sensitive_data",
    "require_encryption",
    "validate_encrypted_field",
    "create_encryption_context",
    # Security - Input validation
    "InputValidationError",
    "SanitizationConfig",
    "sanitize_string",
    "sanitize_dict",
    "sanitize_list",
    "validate_email",
    "validate_uuid",
    "detect_injection_patterns",
    # Security - Rate limiting
    "RateLimitConfig",
    "RateLimiter",
    "RateLimitExceeded",
    "rate_limit",
    # Security - Audit logging
    "SecurityEventType",
    "SecurityEvent",
    "AuditLogger",
    "get_audit_logger",
    # Security - Decorators
    "validate_input",
    "audit_log",
    "require_encryption_validation",
]