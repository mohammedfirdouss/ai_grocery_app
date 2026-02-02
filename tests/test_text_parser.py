"""
Unit tests for Text Parser Lambda function.

Tests text processing, validation logic, correlation ID handling,
structured logging, and error handling.
"""

import json
import pytest
from unittest.mock import Mock, MagicMock, patch
from botocore.exceptions import ClientError

# Import the handler module
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'lambdas', 'text_parser'))

from handler import (
    sanitize_text,
    validate_text,
    process_text,
    update_order_status,
    send_to_product_matcher,
    generate_correlation_id,
    TextValidationError,
    ProcessingError,
    MAX_TEXT_LENGTH,
    MIN_TEXT_LENGTH,
    MAX_LINE_COUNT
)


class TestTextSanitization:
    """Test text sanitization and normalization."""
    
    def test_sanitize_basic_text(self):
        """Test basic text sanitization."""
        text = "  Tomatoes\n  Onions  \n\nPotatoes  "
        result = sanitize_text(text)
        assert result == "Tomatoes\nOnions\n\nPotatoes"
    
    def test_sanitize_unicode_normalization(self):
        """Test Unicode normalization to NFKC form."""
        text = "Café"  # Contains composed characters
        result = sanitize_text(text)
        assert result == "Café"
    
    def test_sanitize_control_characters(self):
        """Test removal of control characters."""
        text = "Tomatoes\x00\x01\x02"
        result = sanitize_text(text)
        assert result == "Tomatoes"
    
    def test_sanitize_line_endings(self):
        """Test normalization of different line endings."""
        # Windows line endings
        text = "Tomatoes\r\nOnions\rPotatoes"
        result = sanitize_text(text)
        assert result == "Tomatoes\nOnions\nPotatoes"
    
    def test_sanitize_excessive_whitespace(self):
        """Test normalization of excessive whitespace."""
        text = "Tomatoes   with   spaces"
        result = sanitize_text(text)
        assert result == "Tomatoes with spaces"
    
    def test_sanitize_excessive_newlines(self):
        """Test removal of excessive consecutive newlines."""
        text = "Tomatoes\n\n\n\n\nOnions"
        result = sanitize_text(text)
        assert result == "Tomatoes\n\nOnions"
    
    def test_sanitize_normalizes_tabs(self):
        """Test that tabs are normalized to spaces."""
        text = "Tomatoes\tOnions"
        result = sanitize_text(text)
        # Tabs are normalized to spaces during whitespace normalization
        assert result == "Tomatoes Onions"
    
    def test_sanitize_non_string_input(self):
        """Test error handling for non-string input."""
        with pytest.raises(TextValidationError, match="Text must be a string"):
            sanitize_text(123)
    
    def test_sanitize_empty_string(self):
        """Test sanitization of empty string."""
        result = sanitize_text("")
        assert result == ""
    
    def test_sanitize_whitespace_only(self):
        """Test sanitization of whitespace-only string."""
        result = sanitize_text("   \n\n   ")
        assert result == ""


class TestTextValidation:
    """Test text validation logic."""
    
    def test_validate_valid_text(self):
        """Test validation of valid text."""
        text = "Tomatoes\nOnions\nPotatoes"
        correlation_id = "test-123"
        # Should not raise any exception
        validate_text(text, correlation_id)
    
    def test_validate_empty_text(self):
        """Test validation of empty text."""
        with pytest.raises(TextValidationError, match="Empty grocery list text"):
            validate_text("", "test-123")
    
    def test_validate_text_too_long(self):
        """Test validation of text exceeding maximum length."""
        text = "x" * (MAX_TEXT_LENGTH + 1)
        with pytest.raises(TextValidationError, match="exceeds maximum length"):
            validate_text(text, "test-123")
    
    def test_validate_too_many_lines(self):
        """Test validation of text with too many lines."""
        text = "\n".join(["item"] * (MAX_LINE_COUNT + 1))
        with pytest.raises(TextValidationError, match="exceeds maximum.*lines"):
            validate_text(text, "test-123")
    
    def test_validate_suspicious_script_tag(self):
        """Test detection of suspicious script tags."""
        text = "Tomatoes <script>alert('xss')</script>"
        with pytest.raises(TextValidationError, match="Invalid characters or patterns"):
            validate_text(text, "test-123")
    
    def test_validate_suspicious_javascript_protocol(self):
        """Test detection of javascript: protocol."""
        text = "Tomatoes javascript:void(0)"
        with pytest.raises(TextValidationError, match="Invalid characters or patterns"):
            validate_text(text, "test-123")
    
    def test_validate_suspicious_event_handler(self):
        """Test detection of event handlers."""
        text = "Tomatoes onclick=alert(1)"
        with pytest.raises(TextValidationError, match="Invalid characters or patterns"):
            validate_text(text, "test-123")
    
    def test_validate_suspicious_data_uri(self):
        """Test detection of data URIs."""
        text = "Tomatoes data:text/html,<script>"
        with pytest.raises(TextValidationError, match="Invalid characters or patterns"):
            validate_text(text, "test-123")
    
    def test_validate_at_max_length(self):
        """Test validation at exactly maximum length."""
        text = "x" * MAX_TEXT_LENGTH
        validate_text(text, "test-123")  # Should not raise
    
    def test_validate_at_max_lines(self):
        """Test validation at exactly maximum line count."""
        text = "\n".join(["item"] * MAX_LINE_COUNT)
        validate_text(text, "test-123")  # Should not raise


class TestProcessText:
    """Test text processing function."""
    
    def test_process_valid_text(self):
        """Test processing of valid text."""
        text = "Tomatoes\nOnions\nPotatoes"
        order_id = "order-123"
        correlation_id = "corr-123"
        
        result = process_text(text, order_id, correlation_id)
        
        assert result["order_id"] == order_id
        assert result["processed_text"] == "Tomatoes\nOnions\nPotatoes"
        assert result["text_length"] == len("Tomatoes\nOnions\nPotatoes")
        assert result["line_count"] == 3
        assert result["non_empty_line_count"] == 3
        assert result["average_line_length"] > 0
    
    def test_process_text_with_empty_lines(self):
        """Test processing text with empty lines."""
        text = "Tomatoes\n\nOnions\n\nPotatoes"
        order_id = "order-123"
        correlation_id = "corr-123"
        
        result = process_text(text, order_id, correlation_id)
        
        assert result["line_count"] == 5
        assert result["non_empty_line_count"] == 3
    
    def test_process_text_sanitization_error(self):
        """Test handling of sanitization errors."""
        with pytest.raises((TextValidationError, TypeError)):
            process_text(123, "order-123", "corr-123")  # Non-string input
    
    def test_process_empty_text_after_sanitization(self):
        """Test processing of text that becomes empty after sanitization."""
        text = "   \n\n   "
        with pytest.raises(TextValidationError, match="Empty grocery list text"):
            process_text(text, "order-123", "corr-123")
    
    def test_process_text_too_long(self):
        """Test processing of text that's too long."""
        text = "x" * (MAX_TEXT_LENGTH + 1)
        with pytest.raises(TextValidationError, match="exceeds maximum length"):
            process_text(text, "order-123", "corr-123")


class TestUpdateOrderStatus:
    """Test order status update function."""
    
    @patch('handler.dynamodb')
    def test_update_order_status_success(self, mock_dynamodb):
        """Test successful order status update."""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        
        with patch('handler.ORDERS_TABLE_NAME', 'test-table'):
            update_order_status(
                order_id="order-123",
                status="PARSING_COMPLETE",
                created_at="2024-01-01T00:00:00Z",
                correlation_id="corr-123"
            )
        
        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs['Key'] == {
            "order_id": "order-123",
            "created_at": "2024-01-01T00:00:00Z"
        }
        assert ":status" in call_kwargs['ExpressionAttributeValues']
        assert call_kwargs['ExpressionAttributeValues'][':status'] == "PARSING_COMPLETE"
    
    @patch('handler.dynamodb')
    def test_update_order_status_with_additional_attributes(self, mock_dynamodb):
        """Test order status update with additional attributes."""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        
        with patch('handler.ORDERS_TABLE_NAME', 'test-table'):
            update_order_status(
                order_id="order-123",
                status="PARSING_COMPLETE",
                created_at="2024-01-01T00:00:00Z",
                correlation_id="corr-123",
                additional_attributes={
                    "processed_text": "Some text",
                    "text_length": 9
                }
            )
        
        call_kwargs = mock_table.update_item.call_args[1]
        assert ":attr_processed_text" in call_kwargs['ExpressionAttributeValues']
        assert ":attr_text_length" in call_kwargs['ExpressionAttributeValues']
    
    def test_update_order_status_no_table_name(self):
        """Test order status update when table name is not configured."""
        with patch('handler.ORDERS_TABLE_NAME', ''):
            # Should not raise, just log warning
            update_order_status(
                order_id="order-123",
                status="PARSING_COMPLETE",
                created_at="2024-01-01T00:00:00Z",
                correlation_id="corr-123"
            )
    
    @patch('handler.dynamodb')
    def test_update_order_status_retry_on_failure(self, mock_dynamodb):
        """Test retry logic on DynamoDB failure."""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        
        # Simulate transient error then success
        mock_table.update_item.side_effect = [
            ClientError(
                {'Error': {'Code': 'ProvisionedThroughputExceededException'}},
                'UpdateItem'
            ),
            None  # Success on second attempt
        ]
        
        with patch('handler.ORDERS_TABLE_NAME', 'test-table'):
            update_order_status(
                order_id="order-123",
                status="PARSING_COMPLETE",
                created_at="2024-01-01T00:00:00Z",
                correlation_id="corr-123"
            )
        
        assert mock_table.update_item.call_count == 2
    
    @patch('handler.dynamodb')
    def test_update_order_status_fails_after_retries(self, mock_dynamodb):
        """Test failure after all retries exhausted."""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        
        # Simulate persistent error
        mock_table.update_item.side_effect = ClientError(
            {'Error': {'Code': 'InternalServerError'}},
            'UpdateItem'
        )
        
        with patch('handler.ORDERS_TABLE_NAME', 'test-table'):
            with pytest.raises(ProcessingError, match="Failed to update order status"):
                update_order_status(
                    order_id="order-123",
                    status="PARSING_COMPLETE",
                    created_at="2024-01-01T00:00:00Z",
                    correlation_id="corr-123"
                )
        
        assert mock_table.update_item.call_count == 3  # Max retries


class TestSendToProductMatcher:
    """Test sending messages to Product Matcher queue."""
    
    @patch('handler.sqs_client')
    def test_send_to_product_matcher_success(self, mock_sqs):
        """Test successful message send."""
        mock_sqs.send_message.return_value = {"MessageId": "msg-123"}
        
        payload = {
            "order_id": "order-123",
            "processed_text": "Tomatoes\nOnions",
            "correlation_id": "corr-123"
        }
        
        with patch('handler.PRODUCT_MATCHER_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/123/test'):
            send_to_product_matcher(payload, "corr-123")
        
        mock_sqs.send_message.assert_called_once()
        call_kwargs = mock_sqs.send_message.call_args[1]
        assert call_kwargs['QueueUrl'] == 'https://sqs.us-east-1.amazonaws.com/123/test'
        assert 'MessageBody' in call_kwargs
        body = json.loads(call_kwargs['MessageBody'])
        assert body['order_id'] == "order-123"
    
    def test_send_to_product_matcher_no_queue_url(self):
        """Test message send when queue URL is not configured."""
        with patch('handler.PRODUCT_MATCHER_QUEUE_URL', ''):
            # Should not raise, just log warning
            send_to_product_matcher({"order_id": "order-123"}, "corr-123")
    
    @patch('handler.sqs_client')
    def test_send_to_product_matcher_retry_on_failure(self, mock_sqs):
        """Test retry logic on SQS failure."""
        # Simulate transient error then success
        mock_sqs.send_message.side_effect = [
            ClientError(
                {'Error': {'Code': 'ServiceUnavailable'}},
                'SendMessage'
            ),
            {"MessageId": "msg-123"}  # Success on second attempt
        ]
        
        payload = {"order_id": "order-123"}
        
        with patch('handler.PRODUCT_MATCHER_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/123/test'):
            send_to_product_matcher(payload, "corr-123")
        
        assert mock_sqs.send_message.call_count == 2
    
    @patch('handler.sqs_client')
    def test_send_to_product_matcher_fails_after_retries(self, mock_sqs):
        """Test failure after all retries exhausted."""
        # Simulate persistent error
        mock_sqs.send_message.side_effect = ClientError(
            {'Error': {'Code': 'InternalServerError'}},
            'SendMessage'
        )
        
        with patch('handler.PRODUCT_MATCHER_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/123/test'):
            with pytest.raises(ProcessingError, match="Failed to send message to Product Matcher"):
                send_to_product_matcher({"order_id": "order-123"}, "corr-123")
        
        assert mock_sqs.send_message.call_count == 3  # Max retries


class TestCorrelationId:
    """Test correlation ID generation."""
    
    def test_generate_correlation_id(self):
        """Test that correlation ID is generated."""
        corr_id = generate_correlation_id()
        assert corr_id is not None
        assert len(corr_id) > 0
    
    def test_generate_unique_correlation_ids(self):
        """Test that generated correlation IDs are unique."""
        corr_id1 = generate_correlation_id()
        corr_id2 = generate_correlation_id()
        assert corr_id1 != corr_id2


class TestRecordHandler:
    """Test SQS record handler."""
    
    @patch('handler.send_to_product_matcher')
    @patch('handler.update_order_status')
    @patch('handler.ORDERS_TABLE_NAME', 'test-table')
    @patch('handler.PRODUCT_MATCHER_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/123/test')
    def test_record_handler_success(self, mock_update, mock_send):
        """Test successful record processing."""
        from handler import record_handler
        from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
        
        # Create mock SQS record
        mock_record = Mock(spec=SQSRecord)
        mock_record.message_id = "msg-123"
        mock_record.receipt_handle = "receipt-handle-123456789"
        mock_record.body = json.dumps({
            "order_id": "order-123",
            "raw_text": "Tomatoes\nOnions",
            "created_at": "2024-01-01T00:00:00Z",
            "customer_email": "test@example.com",
            "correlation_id": "corr-123"
        })
        
        result = record_handler(mock_record)
        
        assert result["status"] == "success"
        assert result["order_id"] == "order-123"
        assert result["correlation_id"] == "corr-123"
        mock_update.assert_called_once()
        mock_send.assert_called_once()
    
    def test_record_handler_invalid_json(self):
        """Test handling of invalid JSON in record body."""
        from handler import record_handler
        from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
        
        mock_record = Mock(spec=SQSRecord)
        mock_record.message_id = "msg-123"
        mock_record.body = "invalid json {{{{"
        
        with pytest.raises(ValueError, match="Invalid JSON"):
            record_handler(mock_record)
    
    def test_record_handler_missing_order_id(self):
        """Test handling of missing order_id."""
        from handler import record_handler
        from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
        
        mock_record = Mock(spec=SQSRecord)
        mock_record.message_id = "msg-123"
        mock_record.body = json.dumps({
            "raw_text": "Tomatoes",
            "created_at": "2024-01-01T00:00:00Z"
        })
        
        with pytest.raises(ValueError, match="Missing required field: order_id"):
            record_handler(mock_record)
    
    def test_record_handler_missing_created_at(self):
        """Test handling of missing created_at."""
        from handler import record_handler
        from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
        
        mock_record = Mock(spec=SQSRecord)
        mock_record.message_id = "msg-123"
        mock_record.body = json.dumps({
            "order_id": "order-123",
            "raw_text": "Tomatoes"
        })
        
        with pytest.raises(ValueError, match="Missing required field: created_at"):
            record_handler(mock_record)
    
    def test_record_handler_missing_raw_text(self):
        """Test handling of missing raw_text."""
        from handler import record_handler
        from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
        
        mock_record = Mock(spec=SQSRecord)
        mock_record.message_id = "msg-123"
        mock_record.body = json.dumps({
            "order_id": "order-123",
            "created_at": "2024-01-01T00:00:00Z"
        })
        
        with pytest.raises(ValueError, match="Missing required field: raw_text"):
            record_handler(mock_record)
    
    @patch('handler.send_to_product_matcher')
    @patch('handler.update_order_status')
    @patch('handler.ORDERS_TABLE_NAME', 'test-table')
    @patch('handler.PRODUCT_MATCHER_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/123/test')
    def test_record_handler_generates_correlation_id(self, mock_update, mock_send):
        """Test that correlation ID is generated if not provided."""
        from handler import record_handler
        from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
        
        mock_record = Mock(spec=SQSRecord)
        mock_record.message_id = "msg-123"
        mock_record.receipt_handle = "receipt-handle-123456789"
        mock_record.body = json.dumps({
            "order_id": "order-123",
            "raw_text": "Tomatoes\nOnions",
            "created_at": "2024-01-01T00:00:00Z"
            # No correlation_id provided
        })
        
        result = record_handler(mock_record)
        
        assert "correlation_id" in result
        assert result["correlation_id"] is not None
        assert len(result["correlation_id"]) > 0
    
    @patch('handler.update_order_status')
    @patch('handler.ORDERS_TABLE_NAME', 'test-table')
    @patch('handler.PRODUCT_MATCHER_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/123/test')
    def test_record_handler_validation_error(self, mock_update):
        """Test handling of validation errors."""
        from handler import record_handler
        from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
        
        mock_record = Mock(spec=SQSRecord)
        mock_record.message_id = "msg-123"
        mock_record.receipt_handle = "receipt-handle-123456789"
        mock_record.body = json.dumps({
            "order_id": "order-123",
            "raw_text": "",  # Empty text will fail validation
            "created_at": "2024-01-01T00:00:00Z"
        })
        
        with pytest.raises(ValueError):  # Validation errors are converted to ValueError
            record_handler(mock_record)
        
        # Should attempt to update order status to FAILED
        mock_update.assert_called()
