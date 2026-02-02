"""
Tests for AppSync GraphQL API infrastructure.
"""

import pytest
import os
import json
from unittest.mock import MagicMock, patch


class TestAppSyncSchema:
    """Tests for AppSync GraphQL schema validation."""
    
    def test_schema_file_exists(self):
        """Test that the GraphQL schema file exists."""
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "appsync",
            "schema",
            "schema.graphql"
        )
        assert os.path.exists(schema_path), f"Schema file not found at {schema_path}"
    
    def test_schema_contains_required_types(self):
        """Test that the schema contains all required types."""
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "appsync",
            "schema",
            "schema.graphql"
        )
        
        with open(schema_path, "r") as f:
            schema_content = f.read()
        
        # Check for required types
        required_types = [
            "type Order",
            "type PaymentLink",
            "type ExtractedItem",
            "type MatchedItem",
            "type ProcessingEvent",
            "type SubmitGroceryListResponse",
            "type OrderConnection",
        ]
        
        for type_def in required_types:
            assert type_def in schema_content, f"Missing type: {type_def}"
    
    def test_schema_contains_required_queries(self):
        """Test that the schema contains all required queries."""
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "appsync",
            "schema",
            "schema.graphql"
        )
        
        with open(schema_path, "r") as f:
            schema_content = f.read()
        
        # Check for required queries
        required_queries = [
            "getOrder(orderId: ID!): Order",
            "listOrders(",
            "getMyOrders(",
            "getPaymentLink(orderId: ID!): PaymentLink",
        ]
        
        for query in required_queries:
            assert query in schema_content, f"Missing query: {query}"
    
    def test_schema_contains_required_mutations(self):
        """Test that the schema contains all required mutations."""
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "appsync",
            "schema",
            "schema.graphql"
        )
        
        with open(schema_path, "r") as f:
            schema_content = f.read()
        
        # Check for required mutations
        required_mutations = [
            "submitGroceryList(input: SubmitGroceryListInput!): SubmitGroceryListResponse!",
            "cancelOrder(orderId: ID!): Order",
        ]
        
        for mutation in required_mutations:
            assert mutation in schema_content, f"Missing mutation: {mutation}"
    
    def test_schema_contains_required_subscriptions(self):
        """Test that the schema contains all required subscriptions."""
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "appsync",
            "schema",
            "schema.graphql"
        )
        
        with open(schema_path, "r") as f:
            schema_content = f.read()
        
        # Check for required subscriptions
        required_subscriptions = [
            "onOrderStatusChanged(orderId: ID!): Order",
            "onProcessingEvent(orderId: ID!): ProcessingEvent",
            "onPaymentStatusChanged(orderId: ID!): PaymentLink",
        ]
        
        for subscription in required_subscriptions:
            assert subscription in schema_content, f"Missing subscription: {subscription}"
    
    def test_schema_contains_cognito_auth_directives(self):
        """Test that the schema uses Cognito User Pools authorization."""
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "appsync",
            "schema",
            "schema.graphql"
        )
        
        with open(schema_path, "r") as f:
            schema_content = f.read()
        
        # Check for Cognito auth directive
        assert "@aws_cognito_user_pools" in schema_content, "Missing Cognito auth directive"


class TestAppSyncResolvers:
    """Tests for AppSync resolver VTL templates."""
    
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
    
    def test_query_resolvers_exist(self):
        """Test that all query resolver templates exist."""
        resolvers = [
            "Query.getOrder.request.vtl",
            "Query.getOrder.response.vtl",
            "Query.listOrders.request.vtl",
            "Query.listOrders.response.vtl",
            "Query.getMyOrders.request.vtl",
            "Query.getMyOrders.response.vtl",
            "Query.getPaymentLink.request.vtl",
            "Query.getPaymentLink.response.vtl",
        ]
        
        for resolver in resolvers:
            path = self.get_resolver_path(resolver)
            assert os.path.exists(path), f"Resolver not found: {resolver}"
    
    def test_mutation_resolvers_exist(self):
        """Test that all mutation resolver templates exist."""
        resolvers = [
            "Mutation.submitGroceryList.request.vtl",
            "Mutation.submitGroceryList.response.vtl",
            "Mutation.submitGroceryList.sqs.request.vtl",
            "Mutation.submitGroceryList.sqs.response.vtl",
            "Mutation.cancelOrder.request.vtl",
            "Mutation.cancelOrder.response.vtl",
            "Mutation.cancelOrder.update.request.vtl",
            "Mutation.cancelOrder.update.response.vtl",
        ]
        
        for resolver in resolvers:
            path = self.get_resolver_path(resolver)
            assert os.path.exists(path), f"Resolver not found: {resolver}"
    
    def test_subscription_resolvers_exist(self):
        """Test that all subscription resolver templates exist."""
        resolvers = [
            "Subscription.onOrderStatusChanged.request.vtl",
            "Subscription.onOrderStatusChanged.response.vtl",
            "Subscription.onProcessingEvent.request.vtl",
            "Subscription.onProcessingEvent.response.vtl",
            "Subscription.onPaymentStatusChanged.request.vtl",
            "Subscription.onPaymentStatusChanged.response.vtl",
        ]
        
        for resolver in resolvers:
            path = self.get_resolver_path(resolver)
            assert os.path.exists(path), f"Resolver not found: {resolver}"
    
    def test_getorder_request_contains_dynamodb_operation(self):
        """Test that getOrder request template contains DynamoDB operation."""
        path = self.get_resolver_path("Query.getOrder.request.vtl")
        with open(path, "r") as f:
            content = f.read()
        
        assert '"operation": "Query"' in content or '"operation": "GetItem"' in content
        assert "order_id" in content.lower() or "orderid" in content.lower()
    
    def test_submit_grocery_list_uses_putitem(self):
        """Test that submitGroceryList uses DynamoDB PutItem."""
        path = self.get_resolver_path("Mutation.submitGroceryList.request.vtl")
        with open(path, "r") as f:
            content = f.read()
        
        assert '"operation": "PutItem"' in content
        assert "order_id" in content.lower() or "orderid" in content.lower()
    
    def test_submit_grocery_list_sqs_sends_message(self):
        """Test that submitGroceryList SQS template sends a message."""
        path = self.get_resolver_path("Mutation.submitGroceryList.sqs.request.vtl")
        with open(path, "r") as f:
            content = f.read()
        
        assert "SendMessage" in content
        assert "QueueUrl" in content


class TestAppSyncInfrastructure:
    """Tests for AppSync infrastructure configuration in CDK stack."""
    
    def test_stack_imports_cognito(self):
        """Test that the stack imports Cognito module."""
        stack_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "stacks",
            "ai_grocery_stack.py"
        )
        
        with open(stack_path, "r") as f:
            content = f.read()
        
        assert "aws_cognito as cognito" in content
    
    def test_stack_creates_user_pool(self):
        """Test that the stack creates a Cognito User Pool."""
        stack_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "stacks",
            "ai_grocery_stack.py"
        )
        
        with open(stack_path, "r") as f:
            content = f.read()
        
        assert "cognito.UserPool(" in content
        assert "_create_cognito_user_pool" in content
    
    def test_stack_creates_graphql_api(self):
        """Test that the stack creates an AppSync GraphQL API."""
        stack_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "stacks",
            "ai_grocery_stack.py"
        )
        
        with open(stack_path, "r") as f:
            content = f.read()
        
        assert "appsync.GraphqlApi(" in content
        assert "_create_appsync_api" in content
    
    def test_stack_creates_data_sources(self):
        """Test that the stack creates AppSync data sources."""
        stack_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "stacks",
            "ai_grocery_stack.py"
        )
        
        with open(stack_path, "r") as f:
            content = f.read()
        
        assert "add_dynamo_db_data_source" in content
        assert "add_http_data_source" in content
        assert "OrdersDataSource" in content
        assert "PaymentLinksDataSource" in content
        assert "SQSDataSource" in content
    
    def test_stack_configures_cognito_auth(self):
        """Test that the stack configures Cognito User Pool authorization."""
        stack_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "stacks",
            "ai_grocery_stack.py"
        )
        
        with open(stack_path, "r") as f:
            content = f.read()
        
        assert "AuthorizationType.USER_POOL" in content
        assert "UserPoolConfig" in content
    
    def test_stack_creates_resolvers(self):
        """Test that the stack creates resolvers for all operations."""
        stack_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "stacks",
            "ai_grocery_stack.py"
        )
        
        with open(stack_path, "r") as f:
            content = f.read()
        
        # Check for resolver creations
        assert "GetOrderResolver" in content
        assert "ListOrdersResolver" in content
        assert "GetPaymentLinkResolver" in content
        assert "SubmitGroceryListResolver" in content
        assert "CancelOrderResolver" in content
    
    def test_stack_outputs_include_appsync(self):
        """Test that stack outputs include AppSync resources."""
        stack_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "infrastructure",
            "stacks",
            "ai_grocery_stack.py"
        )
        
        with open(stack_path, "r") as f:
            content = f.read()
        
        assert "GraphQLApiUrl" in content
        assert "GraphQLApiId" in content
        assert "UserPoolId" in content
        assert "UserPoolClientId" in content
