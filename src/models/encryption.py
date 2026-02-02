"""
Encryption helpers for sensitive data in the AI Grocery App.

This module provides utilities for encrypting and decrypting sensitive data
such as customer email addresses and payment information using AWS KMS.
"""

import base64
import hashlib
import hmac
import os
import secrets
from typing import Optional, Dict, Any

import boto3
from botocore.exceptions import ClientError


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
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext data using AWS KMS.
        
        Args:
            plaintext: The text to encrypt.
            
        Returns:
            Base64-encoded encrypted ciphertext.
            
        Raises:
            ValueError: If KMS key ID is not configured.
            ClientError: If KMS encryption fails.
        """
        if not self.kms_key_id:
            raise ValueError("KMS key ID is not configured")
        
        response = self._kms_client.encrypt(
            KeyId=self.kms_key_id,
            Plaintext=plaintext.encode("utf-8")
        )
        
        ciphertext_blob = response["CiphertextBlob"]
        return base64.b64encode(ciphertext_blob).decode("utf-8")
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt ciphertext using AWS KMS.
        
        Args:
            ciphertext: Base64-encoded encrypted ciphertext.
            
        Returns:
            Decrypted plaintext.
            
        Raises:
            ClientError: If KMS decryption fails.
        """
        ciphertext_blob = base64.b64decode(ciphertext)
        
        response = self._kms_client.decrypt(
            CiphertextBlob=ciphertext_blob
        )
        
        return response["Plaintext"].decode("utf-8")


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
    """
    salt = salt or os.environ.get("EMAIL_HASH_SALT", "default-salt")
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
