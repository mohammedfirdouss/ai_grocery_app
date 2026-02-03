"""
Unit tests for Monitoring Construct.

Tests CloudWatch alarms, dashboards, and health check configurations.
"""

import pytest
import aws_cdk as cdk
from aws_cdk import (
    assertions,
    aws_lambda as lambda_,
    aws_sqs as sqs,
    aws_dynamodb as dynamodb,
)

from infrastructure.monitoring.monitoring_construct import MonitoringConstruct


class TestMonitoringConstruct:
    """Test monitoring construct configuration."""
    
    @pytest.fixture
    def test_stack(self):
        """Create test stack with mock resources."""
        app = cdk.App()
        stack = cdk.Stack(app, "TestStack")
        
        # Create mock Lambda functions
        lambda_function = lambda_.Function(
            stack,
            "TestFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_inline("def handler(event, context): pass"),
            timeout=cdk.Duration.seconds(30)
        )
        
        # Create mock SQS queues
        dlq = sqs.Queue(stack, "TestDLQ")
        queue = sqs.Queue(stack, "TestQueue")
        
        # Create mock DynamoDB table
        table = dynamodb.Table(
            stack,
            "TestTable",
            partition_key=dynamodb.Attribute(
                name="id",
                type=dynamodb.AttributeType.STRING
            )
        )
        
        return {
            "stack": stack,
            "lambda_functions": {"test-function": lambda_function},
            "sqs_queues": {"test-queue": queue, "test-dlq": dlq},
            "dynamodb_tables": {"test-table": table}
        }
    
    def test_creates_alarm_topic(self, test_stack):
        """Test that SNS alarm topic is created."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"]
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Verify SNS topic is created
        template.resource_count_is("AWS::SNS::Topic", 1)
        template.has_resource_properties("AWS::SNS::Topic", {
            "TopicName": "ai-grocery-alarms-test"
        })
    
    def test_creates_alarm_topic_with_email(self, test_stack):
        """Test that SNS topic has email subscription when provided."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"],
            alarm_email="test@example.com"
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Verify email subscription is created
        template.resource_count_is("AWS::SNS::Subscription", 1)
        template.has_resource_properties("AWS::SNS::Subscription", {
            "Protocol": "email",
            "Endpoint": "test@example.com"
        })
    
    def test_creates_lambda_alarms(self, test_stack):
        """Test that Lambda CloudWatch alarms are created."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"]
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Check for Lambda error alarm
        template.has_resource_properties("AWS::CloudWatch::Alarm", {
            "AlarmName": "ai-grocery-test-test-function-errors",
            "MetricName": "Errors",
            "Namespace": "AWS/Lambda"
        })
        
        # Check for Lambda latency alarm
        template.has_resource_properties("AWS::CloudWatch::Alarm", {
            "AlarmName": "ai-grocery-test-test-function-latency"
        })
        
        # Check for Lambda throttle alarm
        template.has_resource_properties("AWS::CloudWatch::Alarm", {
            "AlarmName": "ai-grocery-test-test-function-throttles"
        })
    
    def test_creates_sqs_alarms(self, test_stack):
        """Test that SQS CloudWatch alarms are created."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"]
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Check for DLQ messages alarm
        template.has_resource_properties("AWS::CloudWatch::Alarm", {
            "AlarmName": "ai-grocery-test-test-dlq-dlq-messages"
        })
    
    def test_creates_dynamodb_alarms(self, test_stack):
        """Test that DynamoDB CloudWatch alarms are created."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"]
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Check for DynamoDB read throttle alarm
        template.has_resource_properties("AWS::CloudWatch::Alarm", {
            "AlarmName": "ai-grocery-test-test-table-read-throttle",
            "MetricName": "ReadThrottleEvents",
            "Namespace": "AWS/DynamoDB"
        })
        
        # Check for DynamoDB write throttle alarm
        template.has_resource_properties("AWS::CloudWatch::Alarm", {
            "AlarmName": "ai-grocery-test-test-table-write-throttle"
        })
        
        # Check for DynamoDB system error alarm
        template.has_resource_properties("AWS::CloudWatch::Alarm", {
            "AlarmName": "ai-grocery-test-test-table-system-errors"
        })
    
    def test_creates_dashboard(self, test_stack):
        """Test that CloudWatch dashboard is created."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"]
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Verify dashboard is created
        template.resource_count_is("AWS::CloudWatch::Dashboard", 1)
        template.has_resource_properties("AWS::CloudWatch::Dashboard", {
            "DashboardName": "ai-grocery-test-dashboard"
        })
    
    def test_creates_budget_alert(self, test_stack):
        """Test that AWS Budget alert is created."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"],
            monthly_budget_limit=100.0
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Verify budget is created
        template.resource_count_is("AWS::Budgets::Budget", 1)
        template.has_resource_properties("AWS::Budgets::Budget", {
            "Budget": {
                "BudgetName": "ai-grocery-test-monthly-budget",
                "BudgetType": "COST",
                "TimeUnit": "MONTHLY",
                "BudgetLimit": {
                    "Amount": 100,
                    "Unit": "USD"
                }
            }
        })
    
    def test_creates_health_check_lambda(self, test_stack):
        """Test that health check Lambda is created."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"]
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Verify health check Lambda is created
        template.has_resource_properties("AWS::Lambda::Function", {
            "FunctionName": "ai-grocery-health-check-test",
            "Runtime": "python3.11",
            "Handler": "index.handler"
        })
    
    def test_creates_health_check_schedule(self, test_stack):
        """Test that health check schedule is created."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"]
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Verify EventBridge rule is created for scheduling
        template.has_resource_properties("AWS::Events::Rule", {
            "Name": "ai-grocery-health-check-schedule-test",
            "ScheduleExpression": "rate(5 minutes)"
        })
    
    def test_health_check_has_required_permissions(self, test_stack):
        """Test that health check Lambda has required IAM permissions."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"]
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Verify IAM role has required permissions
        template.has_resource_properties("AWS::IAM::Policy", {
            "PolicyDocument": {
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": assertions.Match.array_with([
                            "dynamodb:DescribeTable",
                            "sqs:GetQueueAttributes",
                            "lambda:GetFunction",
                            "cloudwatch:GetMetricData"
                        ]),
                        "Effect": "Allow"
                    })
                ])
            }
        })
    
    def test_alarm_treats_missing_data_as_not_breaching(self, test_stack):
        """Test that alarms treat missing data as not breaching."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"]
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Verify alarms have TreatMissingData set correctly
        template.has_resource_properties("AWS::CloudWatch::Alarm", {
            "TreatMissingData": "notBreaching"
        })
    
    def test_no_budget_created_when_limit_is_zero(self, test_stack):
        """Test that no budget is created when limit is zero."""
        MonitoringConstruct(
            test_stack["stack"],
            "TestMonitoring",
            env_name="test",
            lambda_functions=test_stack["lambda_functions"],
            sqs_queues=test_stack["sqs_queues"],
            dynamodb_tables=test_stack["dynamodb_tables"],
            monthly_budget_limit=0
        )
        
        template = assertions.Template.from_stack(test_stack["stack"])
        
        # Verify no budget is created
        template.resource_count_is("AWS::Budgets::Budget", 0)


class TestMonitoringConstructIntegration:
    """Integration tests for monitoring construct with full stack."""
    
    def test_integration_with_ai_grocery_stack(self):
        """Test that monitoring integrates correctly with main stack."""
        import os
        os.environ.setdefault("CDK_DEFAULT_ACCOUNT", "123456789012")
        os.environ.setdefault("CDK_DEFAULT_REGION", "us-east-1")
        
        from infrastructure.config.environment_config import EnvironmentConfig
        from infrastructure.stacks.ai_grocery_stack import AiGroceryStack
        
        app = cdk.App()
        config = EnvironmentConfig.get_config("dev")
        
        stack = AiGroceryStack(
            app,
            "TestAiGroceryStack",
            config=config,
            env=cdk.Environment(
                account="123456789012",
                region="us-east-1"
            )
        )
        
        template = assertions.Template.from_stack(stack)
        
        # Verify monitoring resources are created
        template.resource_count_is("AWS::CloudWatch::Dashboard", 1)
        template.resource_count_is("AWS::SNS::Topic", 1)
        
        # Verify health check Lambda is created
        template.has_resource_properties("AWS::Lambda::Function", {
            "FunctionName": "ai-grocery-health-check-dev"
        })
