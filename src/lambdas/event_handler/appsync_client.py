"""
AppSync Client for Real-time Notifications.

This module provides a client for publishing real-time notifications via AppSync
GraphQL mutations. It enables event-driven updates to be pushed to subscribed clients.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
import urllib.request
from aws_lambda_powertools import Logger

logger = Logger(child=True)


class AppSyncClient:
    """Client for publishing notifications to AppSync subscriptions."""
    
    def __init__(
        self,
        api_url: Optional[str] = None,
        region: Optional[str] = None
    ):
        """
        Initialize the AppSync client.
        
        Args:
            api_url: AppSync GraphQL API URL. Defaults to APPSYNC_API_URL env var.
            region: AWS region. Defaults to AWS_REGION env var.
        """
        self.api_url = api_url or os.environ.get("APPSYNC_API_URL", "")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        
        if not self.api_url:
            logger.warning("AppSync API URL not configured")
    
    def _sign_request(self, method: str, url: str, body: str) -> Dict[str, str]:
        """
        Sign a request using AWS Signature V4.
        
        Args:
            method: HTTP method (POST)
            url: Request URL
            body: Request body
            
        Returns:
            Dictionary of signed headers
        """
        session = boto3.Session()
        credentials = session.get_credentials()
        
        request = AWSRequest(
            method=method,
            url=url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Host": urlparse(url).netloc
            }
        )
        
        SigV4Auth(credentials, "appsync", self.region).add_auth(request)
        return dict(request.headers)
    
    def _execute_mutation(self, mutation: str, variables: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Execute a GraphQL mutation on AppSync.
        
        Args:
            mutation: GraphQL mutation query string
            variables: Variables for the mutation
            
        Returns:
            Response data or None if error
        """
        if not self.api_url:
            logger.warning("Cannot execute mutation: AppSync API URL not configured")
            return None
        
        body = json.dumps({
            "query": mutation,
            "variables": variables
        })
        
        try:
            headers = self._sign_request("POST", self.api_url, body)
            
            req = urllib.request.Request(
                self.api_url,
                data=body.encode("utf-8"),
                headers=headers,
                method="POST"
            )
            
            # Use 10-second timeout for better responsiveness in real-time notifications
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
                
                if "errors" in result:
                    logger.error(
                        "GraphQL errors in mutation",
                        extra={"errors": result["errors"]}
                    )
                    return None
                
                return result.get("data")
                
        except Exception as e:
            logger.exception("Failed to execute AppSync mutation", extra={"error": str(e)})
            return None
    
    def publish_order_update(
        self,
        order_id: str,
        status: str,
        customer_email: str,
        correlation_id: str,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Publish an order status update notification.
        
        Args:
            order_id: The order ID
            status: New order status
            customer_email: Customer's email address
            correlation_id: Correlation ID for tracing
            additional_data: Additional data to include
            
        Returns:
            True if published successfully, False otherwise
        """
        mutation = """
        mutation PublishOrderUpdate($input: PublishOrderUpdateInput!) {
            publishOrderUpdate(input: $input) {
                orderId
                status
                timestamp
            }
        }
        """
        
        variables = {
            "input": {
                "orderId": order_id,
                "status": status,
                "customerEmail": customer_email,
                "correlationId": correlation_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data": json.dumps(additional_data) if additional_data else None
            }
        }
        
        result = self._execute_mutation(mutation, variables)
        
        if result:
            logger.info(
                "Published order update notification",
                extra={"order_id": order_id, "status": status}
            )
            return True
        
        return False
    
    def publish_processing_event(
        self,
        order_id: str,
        event_type: str,
        status: str,
        message: str,
        correlation_id: str,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Publish a processing event notification.
        
        Args:
            order_id: The order ID
            event_type: Type of processing event
            status: Current processing status
            message: Human-readable message
            correlation_id: Correlation ID for tracing
            data: Additional event data
            
        Returns:
            True if published successfully, False otherwise
        """
        mutation = """
        mutation PublishProcessingEvent($input: PublishProcessingEventInput!) {
            publishProcessingEvent(input: $input) {
                orderId
                eventType
                status
                timestamp
            }
        }
        """
        
        variables = {
            "input": {
                "orderId": order_id,
                "eventType": event_type,
                "status": status,
                "message": message,
                "correlationId": correlation_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data": json.dumps(data) if data else None
            }
        }
        
        result = self._execute_mutation(mutation, variables)
        
        if result:
            logger.info(
                "Published processing event notification",
                extra={"order_id": order_id, "event_type": event_type}
            )
            return True
        
        return False
    
    def publish_payment_status(
        self,
        order_id: str,
        status: str,
        payment_url: Optional[str] = None,
        amount: Optional[float] = None,
        currency: str = "NGN"
    ) -> bool:
        """
        Publish a payment status update notification.
        
        Args:
            order_id: The order ID
            status: Payment status (PENDING, PAID, FAILED, etc.)
            payment_url: PayStack payment URL if available
            amount: Payment amount
            currency: Currency code
            
        Returns:
            True if published successfully, False otherwise
        """
        mutation = """
        mutation PublishPaymentStatus($input: PublishPaymentStatusInput!) {
            publishPaymentStatus(input: $input) {
                orderId
                status
                timestamp
            }
        }
        """
        
        variables = {
            "input": {
                "orderId": order_id,
                "status": status,
                "paymentUrl": payment_url,
                "amount": amount,
                "currency": currency,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        }
        
        result = self._execute_mutation(mutation, variables)
        
        if result:
            logger.info(
                "Published payment status notification",
                extra={"order_id": order_id, "status": status}
            )
            return True
        
        return False
    
    def broadcast_error_notification(
        self,
        order_id: str,
        error_type: str,
        error_message: str,
        error_stage: str,
        correlation_id: str,
        is_retryable: bool = False
    ) -> bool:
        """
        Broadcast an error notification to subscribers.
        
        Args:
            order_id: The order ID
            error_type: Type of error
            error_message: Human-readable error message
            error_stage: Processing stage where error occurred
            correlation_id: Correlation ID for tracing
            is_retryable: Whether the operation can be retried
            
        Returns:
            True if published successfully, False otherwise
        """
        mutation = """
        mutation BroadcastErrorNotification($input: BroadcastErrorInput!) {
            broadcastErrorNotification(input: $input) {
                orderId
                errorType
                timestamp
            }
        }
        """
        
        variables = {
            "input": {
                "orderId": order_id,
                "errorType": error_type,
                "errorMessage": error_message,
                "errorStage": error_stage,
                "correlationId": correlation_id,
                "isRetryable": is_retryable,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        }
        
        result = self._execute_mutation(mutation, variables)
        
        if result:
            logger.info(
                "Broadcast error notification",
                extra={
                    "order_id": order_id,
                    "error_type": error_type,
                    "error_stage": error_stage
                }
            )
            return True
        
        return False


# Global client instance (initialized lazily)
_client: Optional[AppSyncClient] = None


def get_appsync_client() -> AppSyncClient:
    """Get the global AppSync client instance."""
    global _client
    if _client is None:
        _client = AppSyncClient()
    return _client
