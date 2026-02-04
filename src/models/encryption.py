"""
Encryption helpers for sensitive data in the AI Grocery App.

This module provides utilities for encrypting and decrypting sensitive data
such as customer email addresses and payment information using AWS KMS.

Features:
- AWS KMS encryption/decryption
- Key rotation support (via AWS KMS automatic rotation)
- Encryption validation decorators
- Sensitive data masking
- Correlation ID generation
"""

import base64
import functools
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime
from typing import Any, Callable, Dict, Optional, TypeVar

import boto3
from botocore.exceptions import ClientError

# Type variable for generic function decorators
F = TypeVar('F', bound=Callable[..., Any])

# Logger for encryption operations
logger = logging.getLogger("encryption.operations")


class EncryptionValidationError(Exception):
    """Exception raised when encryption validation fails."""
    
    def __init__(self, message: str, key_id: Optional[str] = None):
        self.message = message
        self.key_id = key_id
        super().__init__(self.message)


class EncryptionHelper:
    """Helper class for encrypting and decrypting sensitive data using AWS KMS."""
    
    def __init__(
        self,
        kms_key_id: Optional[str] = None,
        region: str = "us-east-1",
        endpoint_url: Optional[str] = None
    ):
        """
        Initialize the encryption helper.
        
        Args:
            kms_key_id: The KMS key ID or ARN to use for encryption.
                       If not provided, will try to get from environment variable.
            region: AWS region for KMS client.
            endpoint_url: Optional endpoint URL for LocalStack testing.
        """
        self.kms_key_id = kms_key_id or os.environ.get("KMS_KEY_ID")
        self.region = region
        
        # Create KMS client
        client_kwargs: Dict[str, Any] = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        
        self._kms_client = boto3.client("kms", **client_kwargs)
        self._key_metadata_cache: Optional[Dict[str, Any]] = None
    
    def validate_key(self) -> bool:
        """
        Validate that the KMS key is accessible and enabled.
        
        Returns:
            True if the key is valid and accessible.
            
        Raises:
            EncryptionValidationError: If the key is not valid or accessible.
        """
        if not self.kms_key_id:
            raise EncryptionValidationError(
                "KMS key ID is not configured",
                key_id=None
            )
        
        try:
            response = self._kms_client.describe_key(KeyId=self.kms_key_id)
            key_metadata = response.get("KeyMetadata", {})
            
            # Check if key is enabled
            if key_metadata.get("KeyState") != "Enabled":
                raise EncryptionValidationError(
                    f"KMS key is not enabled. Current state: {key_metadata.get('KeyState')}",
                    key_id=self.kms_key_id
                )
            
            # Check if key allows encryption
            key_usage = key_metadata.get("KeyUsage", "")
            if key_usage not in ["ENCRYPT_DECRYPT", "GENERATE_VERIFY_MAC"]:
                raise EncryptionValidationError(
                    f"KMS key does not support encryption. Key usage: {key_usage}",
                    key_id=self.kms_key_id
                )
            
            # Cache metadata for future reference
            self._key_metadata_cache = key_metadata
            
            logger.info(
                f"KMS key validated successfully: "
                f"KeyId={mask_key_id(self.kms_key_id)}, "
                f"RotationEnabled={key_metadata.get('KeyRotationEnabled', False)}"
            )
            
            return True
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise EncryptionValidationError(
                f"Failed to validate KMS key: {error_code}",
                key_id=self.kms_key_id
            ) from e
    
    def get_key_rotation_status(self) -> bool:
        """
        Check if automatic key rotation is enabled for the KMS key.
        
        Returns:
            True if key rotation is enabled.
            
        Raises:
            EncryptionValidationError: If the key rotation status cannot be determined.
        """
        if not self.kms_key_id:
            raise EncryptionValidationError(
                "KMS key ID is not configured",
                key_id=None
            )
        
        try:
            response = self._kms_client.get_key_rotation_status(KeyId=self.kms_key_id)
            return response.get("KeyRotationEnabled", False)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            raise EncryptionValidationError(
                f"Failed to get key rotation status: {error_code}",
                key_id=self.kms_key_id
            ) from e
    
    def encrypt(self, plaintext: str, encryption_context: Optional[Dict[str, str]] = None) -> str:
        """
        Encrypt plaintext data using AWS KMS.
        
        Args:
            plaintext: The text to encrypt.
            encryption_context: Optional encryption context for additional security.
                              This must be provided during decryption as well.
            
        Returns:
            Base64-encoded encrypted ciphertext.
            
        Raises:
            ValueError: If KMS key ID is not configured.
            ClientError: If KMS encryption fails.
        """
        if not self.kms_key_id:
            raise ValueError("KMS key ID is not configured")
        
        encrypt_params: Dict[str, Any] = {
            "KeyId": self.kms_key_id,
            "Plaintext": plaintext.encode("utf-8")
        }
        
        if encryption_context:
            encrypt_params["EncryptionContext"] = encryption_context
        
        response = self._kms_client.encrypt(**encrypt_params)
        
        ciphertext_blob = response["CiphertextBlob"]
        
        logger.debug(
            f"Encryption completed: KeyId={mask_key_id(self.kms_key_id)}, "
            f"ContextProvided={encryption_context is not None}"
        )
        
        return base64.b64encode(ciphertext_blob).decode("utf-8")
    
    def decrypt(self, ciphertext: str, encryption_context: Optional[Dict[str, str]] = None) -> str:
        """
        Decrypt ciphertext using AWS KMS.
        
        Args:
            ciphertext: Base64-encoded encrypted ciphertext.
            encryption_context: Optional encryption context. Must match the context
                              used during encryption if one was provided.
            
        Returns:
            Decrypted plaintext.
            
        Raises:
            ClientError: If KMS decryption fails.
        """
        ciphertext_blob = base64.b64decode(ciphertext)
        
        decrypt_params: Dict[str, Any] = {
            "CiphertextBlob": ciphertext_blob
        }
        
        if encryption_context:
            decrypt_params["EncryptionContext"] = encryption_context
        
        response = self._kms_client.decrypt(**decrypt_params)
        
        logger.debug(
            f"Decryption completed: ContextProvided={encryption_context is not None}"
        )
        
        return response["Plaintext"].decode("utf-8")
    
    def encrypt_with_validation(
        self,
        plaintext: str,
        encryption_context: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Encrypt plaintext with key validation.
        
        This method validates the KMS key before performing encryption,
        ensuring that the key is accessible, enabled, and supports encryption.
        
        Args:
            plaintext: The text to encrypt.
            encryption_context: Optional encryption context.
            
        Returns:
            Base64-encoded encrypted ciphertext.
            
        Raises:
            EncryptionValidationError: If the key validation fails.
            ValueError: If KMS key ID is not configured.
            ClientError: If KMS encryption fails.
        """
        self.validate_key()
        return self.encrypt(plaintext, encryption_context)


def generate_correlation_id() -> str:
    """
    Generate a unique correlation ID for request tracing.
    
    Returns:
        A UUID-like correlation ID string.
    """
    return secrets.token_hex(16)


def hash_email(email: str, salt: Optional[str] = None) -> str:
    """
    Create a one-way hash of an email address for indexing.
    
    This allows searching by email without storing plaintext in indexes.
    
    Args:
        email: The email address to hash.
        salt: Optional salt for the hash. If not provided, uses environment variable.
        
    Returns:
        Hex-encoded hash of the email.
        
    Raises:
        ValueError: If salt is not provided and EMAIL_HASH_SALT environment variable is not set.
    """
    if salt is None:
        salt = os.environ.get("EMAIL_HASH_SALT")
        if salt is None:
            raise ValueError(
                "Email hash salt is required. "
                "Either provide 'salt' parameter or set EMAIL_HASH_SALT environment variable."
            )
    
    email_normalized = email.lower().strip()
    
    # Use HMAC-SHA256 for consistent, salted hashing
    hash_bytes = hmac.new(
        salt.encode("utf-8"),
        email_normalized.encode("utf-8"),
        hashlib.sha256
    ).digest()
    
    return base64.urlsafe_b64encode(hash_bytes).decode("utf-8").rstrip("=")


def mask_email(email: str) -> str:
    """
    Mask an email address for display purposes.
    
    Args:
        email: The email address to mask.
        
    Returns:
        Masked email (e.g., "t***@example.com").
    """
    if "@" not in email:
        return "***"
    
    local, domain = email.rsplit("@", 1)
    
    if len(local) <= 1:
        masked_local = "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 1)
    
    return f"{masked_local}@{domain}"


def mask_sensitive_data(data: str, visible_chars: int = 4) -> str:
    """
    Mask sensitive data, showing only the last few characters.
    
    Args:
        data: The sensitive data to mask.
        visible_chars: Number of characters to leave visible at the end.
        
    Returns:
        Masked string (e.g., "****1234").
    """
    if len(data) <= visible_chars:
        return "*" * len(data)
    
    return "*" * (len(data) - visible_chars) + data[-visible_chars:]


class DataProtector:
    """
    Context manager for handling sensitive data with automatic cleanup.
    
    Usage:
        with DataProtector() as protector:
            protector.store("key", sensitive_value)
            # Use sensitive data
        # Data is automatically cleared
    """
    
    def __init__(self):
        """Initialize the data protector."""
        self._data: Dict[str, str] = {}
    
    def __enter__(self) -> "DataProtector":
        """Enter the context."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context and clear sensitive data."""
        self.clear()
        return False
    
    def store(self, key: str, value: str) -> None:
        """
        Store sensitive data.
        
        Args:
            key: Key to identify the data.
            value: The sensitive value to store.
        """
        self._data[key] = value
    
    def get(self, key: str) -> Optional[str]:
        """
        Retrieve sensitive data.
        
        Args:
            key: Key to identify the data.
            
        Returns:
            The stored value or None if not found.
        """
        return self._data.get(key)
    
    def clear(self) -> None:
        """Clear all stored sensitive data."""
        # Overwrite with zeros before clearing for security
        for key in self._data:
            self._data[key] = "\x00" * len(self._data[key])
        self._data.clear()


def mask_key_id(key_id: str) -> str:
    """
    Mask a KMS key ID for logging purposes.
    
    Args:
        key_id: The KMS key ID to mask.
        
    Returns:
        Masked key ID showing only first and last 4 characters.
    """
    if not key_id:
        return "[NONE]"
    if len(key_id) <= 8:
        return "*" * len(key_id)
    return key_id[:4] + "*" * (len(key_id) - 8) + key_id[-4:]


def require_encryption(func: F) -> F:
    """
    Decorator to ensure encryption is properly configured before data operations.
    
    Validates that the KMS key ID is available before allowing sensitive
    data operations to proceed.
    
    Usage:
        @require_encryption
        def save_sensitive_data(data: str, kms_key_id: Optional[str] = None) -> str:
            # This function requires encryption to be configured
            ...
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        kms_key_id = os.environ.get("KMS_KEY_ID") or kwargs.get("kms_key_id")
        
        if not kms_key_id:
            raise EncryptionValidationError(
                "Encryption not configured: KMS_KEY_ID environment variable "
                "or kms_key_id parameter is required for this operation",
                key_id=None
            )
        
        return func(*args, **kwargs)
    
    return wrapper  # type: ignore


def validate_encrypted_field(ciphertext: str) -> bool:
    """
    Validate that a field contains valid encrypted data.
    
    Args:
        ciphertext: The encrypted value to validate.
        
    Returns:
        True if the field appears to contain valid encrypted data.
    """
    if not ciphertext or not isinstance(ciphertext, str):
        return False
    
    # Check if it's valid base64
    try:
        decoded = base64.b64decode(ciphertext)
        # AWS KMS ciphertext has a minimum length
        return len(decoded) >= 30
    except Exception:
        return False


def create_encryption_context(
    resource_type: str,
    resource_id: str,
    purpose: str = "encryption"
) -> Dict[str, str]:
    """
    Create a standardized encryption context for KMS operations.
    
    Encryption context provides additional authenticated data (AAD) for
    KMS operations, helping to ensure that encrypted data can only be
    decrypted in the correct context.
    
    Args:
        resource_type: Type of resource being encrypted (e.g., "order", "payment").
        resource_id: Identifier of the resource.
        purpose: Purpose of the encryption (e.g., "storage", "transit").
        
    Returns:
        Dictionary suitable for use as KMS encryption context.
    """
    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "purpose": purpose,
        "service": "ai-grocery-app"
    }
