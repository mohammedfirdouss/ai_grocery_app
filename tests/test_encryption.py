"""
Unit tests for encryption helpers.
"""

import pytest
from unittest.mock import MagicMock, patch
import base64

from models.encryption import (
    EncryptionHelper,
    DataProtector,
    generate_correlation_id,
    hash_email,
    mask_email,
    mask_sensitive_data,
)


class TestGenerateCorrelationId:
    """Tests for correlation ID generation."""
    
    def test_generates_unique_ids(self):
        """Test that correlation IDs are unique."""
        ids = [generate_correlation_id() for _ in range(100)]
        assert len(set(ids)) == 100
    
    def test_correlation_id_length(self):
        """Test correlation ID has expected length."""
        correlation_id = generate_correlation_id()
        assert len(correlation_id) == 32  # 16 bytes as hex = 32 chars


class TestHashEmail:
    """Tests for email hashing."""
    
    def test_hash_email_consistent(self):
        """Test that hashing the same email produces consistent results."""
        email = "test@example.com"
        salt = "test-salt"
        
        hash1 = hash_email(email, salt)
        hash2 = hash_email(email, salt)
        
        assert hash1 == hash2
    
    def test_hash_email_case_insensitive(self):
        """Test that email hashing is case insensitive."""
        salt = "test-salt"
        
        hash1 = hash_email("Test@Example.COM", salt)
        hash2 = hash_email("test@example.com", salt)
        
        assert hash1 == hash2
    
    def test_hash_email_different_with_different_salt(self):
        """Test that different salts produce different hashes."""
        email = "test@example.com"
        
        hash1 = hash_email(email, "salt1")
        hash2 = hash_email(email, "salt2")
        
        assert hash1 != hash2
    
    def test_hash_email_strips_whitespace(self):
        """Test that whitespace is stripped from email."""
        salt = "test-salt"
        
        hash1 = hash_email("  test@example.com  ", salt)
        hash2 = hash_email("test@example.com", salt)
        
        assert hash1 == hash2
    
    def test_hash_email_requires_salt(self):
        """Test that hash_email raises error when salt is not provided."""
        import os
        
        # Ensure env variable is not set
        original = os.environ.pop("EMAIL_HASH_SALT", None)
        try:
            with pytest.raises(ValueError, match="Email hash salt is required"):
                hash_email("test@example.com")
        finally:
            if original:
                os.environ["EMAIL_HASH_SALT"] = original
    
    def test_hash_email_uses_env_var(self):
        """Test that hash_email uses environment variable if salt not provided."""
        import os
        
        os.environ["EMAIL_HASH_SALT"] = "env-salt"
        try:
            hash1 = hash_email("test@example.com")
            hash2 = hash_email("test@example.com", "env-salt")
            assert hash1 == hash2
        finally:
            del os.environ["EMAIL_HASH_SALT"]


class TestMaskEmail:
    """Tests for email masking."""
    
    def test_mask_email_basic(self):
        """Test basic email masking."""
        result = mask_email("test@example.com")
        assert result == "t***@example.com"
    
    def test_mask_email_single_char_local(self):
        """Test masking email with single character local part."""
        result = mask_email("a@example.com")
        assert result == "*@example.com"
    
    def test_mask_email_invalid_format(self):
        """Test masking invalid email format."""
        result = mask_email("not-an-email")
        assert result == "***"
    
    def test_mask_email_long_local_part(self):
        """Test masking email with long local part."""
        result = mask_email("verylongemailaddress@example.com")
        assert result == "v*******************@example.com"


class TestMaskSensitiveData:
    """Tests for generic sensitive data masking."""
    
    def test_mask_with_default_visible_chars(self):
        """Test masking with default visible characters."""
        result = mask_sensitive_data("1234567890")
        assert result == "******7890"
    
    def test_mask_with_custom_visible_chars(self):
        """Test masking with custom visible characters."""
        result = mask_sensitive_data("1234567890", visible_chars=2)
        assert result == "********90"
    
    def test_mask_short_data(self):
        """Test masking data shorter than visible chars."""
        result = mask_sensitive_data("abc", visible_chars=4)
        assert result == "***"
    
    def test_mask_exact_length(self):
        """Test masking data with exact visible length."""
        result = mask_sensitive_data("1234", visible_chars=4)
        assert result == "****"


class TestDataProtector:
    """Tests for DataProtector context manager."""
    
    def test_store_and_retrieve(self):
        """Test storing and retrieving data."""
        with DataProtector() as protector:
            protector.store("key1", "value1")
            assert protector.get("key1") == "value1"
    
    def test_get_nonexistent_key(self):
        """Test getting a nonexistent key returns None."""
        with DataProtector() as protector:
            assert protector.get("nonexistent") is None
    
    def test_data_cleared_on_exit(self):
        """Test that data is cleared when exiting context."""
        protector = DataProtector()
        protector.store("key1", "value1")
        
        with protector:
            pass
        
        assert protector.get("key1") is None
    
    def test_manual_clear(self):
        """Test manual clearing of data."""
        protector = DataProtector()
        protector.store("key1", "value1")
        protector.clear()
        
        assert protector.get("key1") is None


class TestEncryptionHelper:
    """Tests for EncryptionHelper with mocked KMS."""
    
    @patch('models.encryption.boto3.client')
    def test_encrypt(self, mock_boto_client):
        """Test encryption with mocked KMS."""
        # Setup mock
        mock_kms = MagicMock()
        mock_kms.encrypt.return_value = {
            "CiphertextBlob": b"encrypted_data"
        }
        mock_boto_client.return_value = mock_kms
        
        # Test
        helper = EncryptionHelper(kms_key_id="test-key-id")
        result = helper.encrypt("test plaintext")
        
        assert result == base64.b64encode(b"encrypted_data").decode("utf-8")
        mock_kms.encrypt.assert_called_once()
    
    @patch('models.encryption.boto3.client')
    def test_decrypt(self, mock_boto_client):
        """Test decryption with mocked KMS."""
        # Setup mock
        mock_kms = MagicMock()
        mock_kms.decrypt.return_value = {
            "Plaintext": b"decrypted_text"
        }
        mock_boto_client.return_value = mock_kms
        
        # Test
        helper = EncryptionHelper(kms_key_id="test-key-id")
        ciphertext = base64.b64encode(b"encrypted_data").decode("utf-8")
        result = helper.decrypt(ciphertext)
        
        assert result == "decrypted_text"
        mock_kms.decrypt.assert_called_once()
    
    @patch('models.encryption.boto3.client')
    def test_encrypt_without_key_id_raises_error(self, mock_boto_client):
        """Test that encryption without KMS key ID raises error."""
        helper = EncryptionHelper(kms_key_id=None)
        
        with pytest.raises(ValueError, match="KMS key ID is not configured"):
            helper.encrypt("test plaintext")
