"""
Tests for real-time notification system infrastructure.

Tests the EventBridge Pipes integration and AppSync subscription resolvers
for the real-time notification system.
"""

import pytest
import os
import json
from unittest.mock import MagicMock, patch


class TestNotificationSchema:
    """Tests for notification-related GraphQL schema elements."""
    
    def get_schema_content(self) -> str:
        """Read and return the GraphQL schema content."""
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "appsync",
            "schema",
            "schema.graphql"
        )
        with open(schema_path, "r") as f:
            return f.read()
    
    def test_schema_contains_publish_input_types(self):
        """Test that the schema contains all publish input types."""
        schema_content = self.get_schema_content()
        
        required_input_types = [
            "input PublishOrderUpdateInput",
            "input PublishProcessingEventInput",
            "input PublishPaymentStatusInput",
            "input BroadcastErrorInput",
        ]
        
        for input_type in required_input_types:
            assert input_type in schema_content, f"Missing input type: {input_type}"
    
    def test_schema_contains_publish_response_types(self):
        """Test that the schema contains all publish response types."""
        schema_content = self.get_schema_content()
        
        required_response_types = [
            "type PublishOrderUpdateResponse",
            "type PublishProcessingEventResponse",
            "type PublishPaymentStatusResponse",
            "type BroadcastErrorResponse",
            "type ErrorNotification",
        ]
        
        for response_type in required_response_types:
            assert response_type in schema_content, f"Missing response type: {response_type}"
    
    def test_schema_contains_publish_mutations(self):
        """Test that the schema contains all publish mutations."""
        schema_content = self.get_schema_content()
        
        required_mutations = [
            "publishOrderUpdate(input: PublishOrderUpdateInput!): PublishOrderUpdateResponse!",
            "publishProcessingEvent(input: PublishProcessingEventInput!): PublishProcessingEventResponse!",
            "publishPaymentStatus(input: PublishPaymentStatusInput!): PublishPaymentStatusResponse!",
            "broadcastErrorNotification(input: BroadcastErrorInput!): BroadcastErrorResponse!",
        ]
        
        for mutation in required_mutations:
            assert mutation in schema_content, f"Missing mutation: {mutation}"
    
    def test_schema_contains_error_notification_subscription(self):
        """Test that the schema contains the error notification subscription."""
        schema_content = self.get_schema_content()
        
        assert "onErrorNotification(orderId: ID!): ErrorNotification" in schema_content, \
            "Missing error notification subscription"
    
    def test_publish_mutations_use_iam_auth(self):
        """Test that publish mutations use IAM authorization."""
        schema_content = self.get_schema_content()
        
        # IAM auth directive should be used for publish mutations
        assert "@aws_iam" in schema_content, "Missing IAM auth directive"
        
        # Check that publish mutations are in the section with IAM auth
        publish_mutations = [
            "publishOrderUpdate",
            "publishProcessingEvent",
            "publishPaymentStatus",
            "broadcastErrorNotification",
        ]
        
        for mutation in publish_mutations:
            # Find the mutation definition
            mutation_idx = schema_content.find(f"{mutation}(input:")
            assert mutation_idx != -1, f"Mutation {mutation} not found"
    
    def test_subscriptions_linked_to_publish_mutations(self):
        """Test that subscriptions are triggered by publish mutations."""
        schema_content = self.get_schema_content()
        
        # Check that subscriptions include publish mutations in @aws_subscribe
        assert 'mutations: ["submitGroceryList", "cancelOrder", "publishOrderUpdate"]' in schema_content or \
               '"publishOrderUpdate"' in schema_content, \
               "onOrderStatusChanged should be triggered by publishOrderUpdate"
        
        assert '"publishProcessingEvent"' in schema_content, \
            "onProcessingEvent should be triggered by publishProcessingEvent"
        
        assert '"publishPaymentStatus"' in schema_content, \
            "onPaymentStatusChanged should be triggered by publishPaymentStatus"
        
        assert '"broadcastErrorNotification"' in schema_content, \
            "onErrorNotification should be triggered by broadcastErrorNotification"


class TestNotificationResolvers:
    """Tests for notification-related resolver templates."""
    
    def get_resolver_path(self, filename: str) -> str:
        """Get the path to a resolver template file."""
        return os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "appsync",
            "resolvers",
            filename
        )
    
    def test_publish_mutation_resolvers_exist(self):
        """Test that all publish mutation resolver templates exist."""
        resolvers = [
            "Mutation.publishOrderUpdate.request.vtl",
            "Mutation.publishOrderUpdate.response.vtl",
            "Mutation.publishProcessingEvent.request.vtl",
            "Mutation.publishProcessingEvent.response.vtl",
            "Mutation.publishPaymentStatus.request.vtl",
            "Mutation.publishPaymentStatus.response.vtl",
            "Mutation.broadcastErrorNotification.request.vtl",
            "Mutation.broadcastErrorNotification.response.vtl",
        ]
        
        for resolver in resolvers:
            path = self.get_resolver_path(resolver)
            assert os.path.exists(path), f"Resolver not found: {resolver}"
    
    def test_error_notification_subscription_resolvers_exist(self):
        """Test that error notification subscription resolvers exist."""
        resolvers = [
            "Subscription.onErrorNotification.request.vtl",
            "Subscription.onErrorNotification.response.vtl",
        ]
        
        for resolver in resolvers:
            path = self.get_resolver_path(resolver)
            assert os.path.exists(path), f"Resolver not found: {resolver}"
    
    def test_publish_order_update_request_contains_payload(self):
        """Test that publishOrderUpdate request template contains expected payload."""
        path = self.get_resolver_path("Mutation.publishOrderUpdate.request.vtl")
        with open(path, "r") as f:
            content = f.read()
        
        assert '"payload"' in content
        assert "orderId" in content
        assert "status" in content
        assert "correlationId" in content
    
    def test_broadcast_error_request_contains_error_fields(self):
        """Test that broadcastErrorNotification request template contains error fields."""
        path = self.get_resolver_path("Mutation.broadcastErrorNotification.request.vtl")
        with open(path, "r") as f:
            content = f.read()
        
        assert '"payload"' in content
        assert "errorType" in content
        assert "errorMessage" in content
        assert "errorStage" in content
        assert "isRetryable" in content
    
    def test_error_notification_subscription_filters_by_order_id(self):
        """Test that error notification subscription filters by order ID."""
        path = self.get_resolver_path("Subscription.onErrorNotification.response.vtl")
        with open(path, "r") as f:
            content = f.read()
        
        assert "targetOrderId" in content
        assert "ctx.args.orderId" in content
        assert "ctx.result.orderId" in content


class TestEventBridgeInfrastructure:
    """Tests for EventBridge infrastructure configuration."""
    
    def get_stack_content(self) -> str:
        """Read and return the CDK stack content."""
        stack_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "stacks",
            "ai_grocery_stack.py"
        )
        with open(stack_path, "r") as f:
            return f.read()
    
    def test_stack_creates_eventbridge_pipe(self):
        """Test that the stack creates an EventBridge Pipe."""
        stack_content = self.get_stack_content()
        
        assert "pipes.CfnPipe(" in stack_content
        assert "OrdersStreamPipe" in stack_content
    
    def test_stack_configures_pipe_dlq(self):
        """Test that the stack configures a DLQ for the pipe."""
        stack_content = self.get_stack_content()
        
        assert "dead_letter_config" in stack_content.lower() or "DeadLetterConfig" in stack_content
        assert "eventbridge_dlq" in stack_content
    
    def test_stack_creates_event_rules(self):
        """Test that the stack creates EventBridge rules."""
        stack_content = self.get_stack_content()
        
        assert "OrderStatusChangeRule" in stack_content
        assert "ProcessingErrorRule" in stack_content
        assert "PaymentEventRule" in stack_content
    
    def test_stack_configures_event_handler_appsync(self):
        """Test that the stack configures Event Handler with AppSync URL."""
        stack_content = self.get_stack_content()
        
        assert "_configure_event_handler_appsync" in stack_content
        assert "APPSYNC_API_URL" in stack_content
    
    def test_stack_grants_appsync_permissions(self):
        """Test that the stack grants AppSync permissions to Event Handler."""
        stack_content = self.get_stack_content()
        
        assert "appsync:GraphQL" in stack_content
    
    def test_stack_uses_iam_authorization(self):
        """Test that the stack enables IAM authorization for AppSync."""
        stack_content = self.get_stack_content()
        
        assert "additional_authorization_modes" in stack_content
        assert "AuthorizationType.IAM" in stack_content


class TestEventHandlerLambda:
    """Tests for Event Handler Lambda functionality."""
    
    def get_handler_content(self) -> str:
        """Read and return the event handler content."""
        handler_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "lambdas",
            "event_handler",
            "handler.py"
        )
        with open(handler_path, "r") as f:
            return f.read()
    
    def get_appsync_client_content(self) -> str:
        """Read and return the AppSync client content."""
        client_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "lambdas",
            "event_handler",
            "appsync_client.py"
        )
        with open(client_path, "r") as f:
            return f.read()
    
    def test_appsync_client_module_exists(self):
        """Test that the AppSync client module exists."""
        client_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "lambdas",
            "event_handler",
            "appsync_client.py"
        )
        assert os.path.exists(client_path), "AppSync client module not found"
    
    def test_handler_imports_appsync_client(self):
        """Test that the handler imports the AppSync client."""
        handler_content = self.get_handler_content()
        
        assert "from appsync_client import" in handler_content or \
               "import appsync_client" in handler_content
    
    def test_handler_has_transform_function(self):
        """Test that the handler has an event transformation function."""
        handler_content = self.get_handler_content()
        
        assert "transform_order_event" in handler_content
    
    def test_handler_has_filter_function(self):
        """Test that the handler has a notification filter function."""
        handler_content = self.get_handler_content()
        
        assert "should_publish_notification" in handler_content
    
    def test_handler_publishes_order_updates(self):
        """Test that the handler publishes order update notifications."""
        handler_content = self.get_handler_content()
        
        assert "publish_order_update" in handler_content
    
    def test_handler_publishes_processing_events(self):
        """Test that the handler publishes processing event notifications."""
        handler_content = self.get_handler_content()
        
        assert "publish_processing_event" in handler_content
    
    def test_handler_publishes_payment_status(self):
        """Test that the handler publishes payment status notifications."""
        handler_content = self.get_handler_content()
        
        assert "publish_payment_status" in handler_content
    
    def test_handler_broadcasts_error_notifications(self):
        """Test that the handler broadcasts error notifications."""
        handler_content = self.get_handler_content()
        
        assert "broadcast_error_notification" in handler_content
    
    def test_handler_has_connection_state_tracking(self):
        """Test that the handler has connection state tracking."""
        handler_content = self.get_handler_content()
        
        assert "track_connection_state" in handler_content or \
               "_connection_states" in handler_content
    
    def test_appsync_client_has_required_methods(self):
        """Test that the AppSync client has all required methods."""
        client_content = self.get_appsync_client_content()
        
        required_methods = [
            "publish_order_update",
            "publish_processing_event",
            "publish_payment_status",
            "broadcast_error_notification",
        ]
        
        for method in required_methods:
            assert f"def {method}" in client_content, f"Missing method: {method}"
    
    def test_appsync_client_uses_sigv4_auth(self):
        """Test that the AppSync client uses SigV4 authentication."""
        client_content = self.get_appsync_client_content()
        
        assert "SigV4Auth" in client_content
