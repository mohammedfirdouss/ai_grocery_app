"""
Monitoring and Observability Construct for AI Grocery App.

This module provides CloudWatch alarms, metrics, dashboards, and health check
infrastructure for comprehensive system monitoring.
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subscriptions,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_logs as logs,
    aws_budgets as budgets,
    aws_events as events,
    aws_events_targets as events_targets,
)
from constructs import Construct
from typing import List, Optional, Dict, Any


class MonitoringConstruct(Construct):
    """
    CDK Construct for monitoring and observability infrastructure.
    
    Implements:
    - CloudWatch alarms for error rates and latency
    - Custom metrics for processing stages
    - CloudWatch dashboards for system health
    - Cost monitoring and budget alerts
    - Health check endpoints
    """
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        lambda_functions: Dict[str, lambda_.Function],
        sqs_queues: Dict[str, Any],
        dynamodb_tables: Dict[str, Any],
        alarm_email: Optional[str] = None,
        monthly_budget_limit: float = 100.0,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.env_name = env_name
        self.lambda_functions = lambda_functions
        self.sqs_queues = sqs_queues
        self.dynamodb_tables = dynamodb_tables
        
        # Create SNS topic for alarms
        self.alarm_topic = self._create_alarm_topic(alarm_email)
        
        # Create CloudWatch alarms
        self._create_lambda_alarms()
        self._create_sqs_alarms()
        self._create_dynamodb_alarms()
        
        # Create CloudWatch dashboard
        self.dashboard = self._create_dashboard()
        
        # Create budget alert
        if monthly_budget_limit > 0:
            self._create_budget_alert(monthly_budget_limit, alarm_email)
        
        # Create health check Lambda
        self.health_check_function = self._create_health_check_lambda()
    
    def _create_alarm_topic(self, alarm_email: Optional[str]) -> sns.Topic:
        """Create SNS topic for alarm notifications."""
        topic = sns.Topic(
            self,
            "AlarmTopic",
            topic_name=f"ai-grocery-alarms-{self.env_name}",
            display_name=f"AI Grocery App Alarms ({self.env_name})"
        )
        
        if alarm_email:
            topic.add_subscription(
                sns_subscriptions.EmailSubscription(alarm_email)
            )
        
        return topic
    
    def _create_lambda_alarms(self) -> None:
        """Create CloudWatch alarms for Lambda functions."""
        alarm_action = cloudwatch_actions.SnsAction(self.alarm_topic)
        
        for func_name, func in self.lambda_functions.items():
            # Error rate alarm
            error_metric = func.metric_errors(
                period=Duration.minutes(5),
                statistic="Sum"
            )
            
            cloudwatch.Alarm(
                self,
                f"{func_name}ErrorAlarm",
                alarm_name=f"ai-grocery-{self.env_name}-{func_name}-errors",
                metric=error_metric,
                threshold=5,
                evaluation_periods=2,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                alarm_description=f"Lambda function {func_name} has more than 5 errors in 10 minutes",
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
            ).add_alarm_action(alarm_action)
            
            # Duration/latency alarm (90th percentile)
            duration_metric = func.metric_duration(
                period=Duration.minutes(5),
                statistic="p90"
            )
            
            # Calculate threshold based on function timeout (80% of timeout)
            timeout_seconds = func.timeout.to_seconds() if func.timeout else 30
            duration_threshold = timeout_seconds * 0.8 * 1000  # Convert to milliseconds
            
            cloudwatch.Alarm(
                self,
                f"{func_name}LatencyAlarm",
                alarm_name=f"ai-grocery-{self.env_name}-{func_name}-latency",
                metric=duration_metric,
                threshold=duration_threshold,
                evaluation_periods=3,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                alarm_description=f"Lambda function {func_name} p90 latency exceeds {duration_threshold}ms",
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
            ).add_alarm_action(alarm_action)
            
            # Throttling alarm
            throttle_metric = func.metric_throttles(
                period=Duration.minutes(5),
                statistic="Sum"
            )
            
            cloudwatch.Alarm(
                self,
                f"{func_name}ThrottleAlarm",
                alarm_name=f"ai-grocery-{self.env_name}-{func_name}-throttles",
                metric=throttle_metric,
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                alarm_description=f"Lambda function {func_name} is being throttled",
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
            ).add_alarm_action(alarm_action)
    
    def _create_sqs_alarms(self) -> None:
        """Create CloudWatch alarms for SQS queues."""
        alarm_action = cloudwatch_actions.SnsAction(self.alarm_topic)
        
        for queue_name, queue in self.sqs_queues.items():
            # DLQ message count alarm
            if "dlq" in queue_name.lower():
                dlq_metric = cloudwatch.Metric(
                    namespace="AWS/SQS",
                    metric_name="ApproximateNumberOfMessagesVisible",
                    dimensions_map={"QueueName": queue.queue_name},
                    period=Duration.minutes(5),
                    statistic="Average"
                )
                
                cloudwatch.Alarm(
                    self,
                    f"{queue_name}MessagesAlarm",
                    alarm_name=f"ai-grocery-{self.env_name}-{queue_name}-dlq-messages",
                    metric=dlq_metric,
                    threshold=1,
                    evaluation_periods=1,
                    comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                    alarm_description=f"DLQ {queue_name} has messages - potential processing failures",
                    treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
                ).add_alarm_action(alarm_action)
            else:
                # Regular queue - alarm on message age
                age_metric = cloudwatch.Metric(
                    namespace="AWS/SQS",
                    metric_name="ApproximateAgeOfOldestMessage",
                    dimensions_map={"QueueName": queue.queue_name},
                    period=Duration.minutes(5),
                    statistic="Maximum"
                )
                
                cloudwatch.Alarm(
                    self,
                    f"{queue_name}AgeAlarm",
                    alarm_name=f"ai-grocery-{self.env_name}-{queue_name}-message-age",
                    metric=age_metric,
                    threshold=3600,  # 1 hour
                    evaluation_periods=2,
                    comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                    alarm_description=f"Queue {queue_name} has messages older than 1 hour",
                    treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
                ).add_alarm_action(alarm_action)
    
    def _create_dynamodb_alarms(self) -> None:
        """Create CloudWatch alarms for DynamoDB tables."""
        alarm_action = cloudwatch_actions.SnsAction(self.alarm_topic)
        
        for table_name, table in self.dynamodb_tables.items():
            # Read throttling alarm
            read_throttle_metric = cloudwatch.Metric(
                namespace="AWS/DynamoDB",
                metric_name="ReadThrottleEvents",
                dimensions_map={"TableName": table.table_name},
                period=Duration.minutes(5),
                statistic="Sum"
            )
            
            cloudwatch.Alarm(
                self,
                f"{table_name}ReadThrottleAlarm",
                alarm_name=f"ai-grocery-{self.env_name}-{table_name}-read-throttle",
                metric=read_throttle_metric,
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                alarm_description=f"DynamoDB table {table_name} is experiencing read throttling",
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
            ).add_alarm_action(alarm_action)
            
            # Write throttling alarm
            write_throttle_metric = cloudwatch.Metric(
                namespace="AWS/DynamoDB",
                metric_name="WriteThrottleEvents",
                dimensions_map={"TableName": table.table_name},
                period=Duration.minutes(5),
                statistic="Sum"
            )
            
            cloudwatch.Alarm(
                self,
                f"{table_name}WriteThrottleAlarm",
                alarm_name=f"ai-grocery-{self.env_name}-{table_name}-write-throttle",
                metric=write_throttle_metric,
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                alarm_description=f"DynamoDB table {table_name} is experiencing write throttling",
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
            ).add_alarm_action(alarm_action)
            
            # System errors alarm
            system_error_metric = cloudwatch.Metric(
                namespace="AWS/DynamoDB",
                metric_name="SystemErrors",
                dimensions_map={"TableName": table.table_name},
                period=Duration.minutes(5),
                statistic="Sum"
            )
            
            cloudwatch.Alarm(
                self,
                f"{table_name}SystemErrorAlarm",
                alarm_name=f"ai-grocery-{self.env_name}-{table_name}-system-errors",
                metric=system_error_metric,
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                alarm_description=f"DynamoDB table {table_name} is experiencing system errors",
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
            ).add_alarm_action(alarm_action)
    
    def _create_dashboard(self) -> cloudwatch.Dashboard:
        """Create CloudWatch dashboard for system health monitoring."""
        dashboard = cloudwatch.Dashboard(
            self,
            "MonitoringDashboard",
            dashboard_name=f"ai-grocery-{self.env_name}-dashboard"
        )
        
        # Lambda metrics section
        lambda_widgets: List[cloudwatch.IWidget] = []
        
        # Lambda invocations graph
        invocation_metrics = [
            func.metric_invocations(period=Duration.minutes(5))
            for func in self.lambda_functions.values()
        ]
        
        lambda_widgets.append(
            cloudwatch.GraphWidget(
                title="Lambda Invocations",
                left=invocation_metrics,
                width=12,
                height=6
            )
        )
        
        # Lambda errors graph
        error_metrics = [
            func.metric_errors(period=Duration.minutes(5))
            for func in self.lambda_functions.values()
        ]
        
        lambda_widgets.append(
            cloudwatch.GraphWidget(
                title="Lambda Errors",
                left=error_metrics,
                width=12,
                height=6
            )
        )
        
        # Lambda duration graph
        duration_metrics = [
            func.metric_duration(period=Duration.minutes(5), statistic="p90")
            for func in self.lambda_functions.values()
        ]
        
        lambda_widgets.append(
            cloudwatch.GraphWidget(
                title="Lambda Duration (p90)",
                left=duration_metrics,
                width=12,
                height=6
            )
        )
        
        # Lambda concurrent executions
        concurrent_metrics = [
            func.metric(
                metric_name="ConcurrentExecutions",
                period=Duration.minutes(5),
                statistic="Maximum"
            )
            for func in self.lambda_functions.values()
        ]
        
        lambda_widgets.append(
            cloudwatch.GraphWidget(
                title="Lambda Concurrent Executions",
                left=concurrent_metrics,
                width=12,
                height=6
            )
        )
        
        dashboard.add_widgets(
            cloudwatch.Row(*lambda_widgets[:2]),
            cloudwatch.Row(*lambda_widgets[2:])
        )
        
        # SQS metrics section
        sqs_widgets: List[cloudwatch.IWidget] = []
        
        # Queue depth metrics
        queue_depth_metrics = []
        for queue_name, queue in self.sqs_queues.items():
            queue_depth_metrics.append(
                cloudwatch.Metric(
                    namespace="AWS/SQS",
                    metric_name="ApproximateNumberOfMessagesVisible",
                    dimensions_map={"QueueName": queue.queue_name},
                    period=Duration.minutes(5),
                    statistic="Average",
                    label=queue_name
                )
            )
        
        sqs_widgets.append(
            cloudwatch.GraphWidget(
                title="SQS Queue Depth",
                left=queue_depth_metrics,
                width=12,
                height=6
            )
        )
        
        # Message age metrics
        message_age_metrics = []
        for queue_name, queue in self.sqs_queues.items():
            message_age_metrics.append(
                cloudwatch.Metric(
                    namespace="AWS/SQS",
                    metric_name="ApproximateAgeOfOldestMessage",
                    dimensions_map={"QueueName": queue.queue_name},
                    period=Duration.minutes(5),
                    statistic="Maximum",
                    label=queue_name
                )
            )
        
        sqs_widgets.append(
            cloudwatch.GraphWidget(
                title="SQS Message Age",
                left=message_age_metrics,
                width=12,
                height=6
            )
        )
        
        dashboard.add_widgets(cloudwatch.Row(*sqs_widgets))
        
        # DynamoDB metrics section
        dynamodb_widgets: List[cloudwatch.IWidget] = []
        
        # Consumed read capacity
        read_capacity_metrics = []
        for table_name, table in self.dynamodb_tables.items():
            read_capacity_metrics.append(
                cloudwatch.Metric(
                    namespace="AWS/DynamoDB",
                    metric_name="ConsumedReadCapacityUnits",
                    dimensions_map={"TableName": table.table_name},
                    period=Duration.minutes(5),
                    statistic="Sum",
                    label=table_name
                )
            )
        
        dynamodb_widgets.append(
            cloudwatch.GraphWidget(
                title="DynamoDB Read Capacity",
                left=read_capacity_metrics,
                width=12,
                height=6
            )
        )
        
        # Consumed write capacity
        write_capacity_metrics = []
        for table_name, table in self.dynamodb_tables.items():
            write_capacity_metrics.append(
                cloudwatch.Metric(
                    namespace="AWS/DynamoDB",
                    metric_name="ConsumedWriteCapacityUnits",
                    dimensions_map={"TableName": table.table_name},
                    period=Duration.minutes(5),
                    statistic="Sum",
                    label=table_name
                )
            )
        
        dynamodb_widgets.append(
            cloudwatch.GraphWidget(
                title="DynamoDB Write Capacity",
                left=write_capacity_metrics,
                width=12,
                height=6
            )
        )
        
        dashboard.add_widgets(cloudwatch.Row(*dynamodb_widgets))
        
        # Custom application metrics section
        custom_widgets: List[cloudwatch.IWidget] = []
        
        # Text parsing metrics
        text_parsing_metrics = [
            cloudwatch.Metric(
                namespace=f"AiGroceryApp/{self.env_name}",
                metric_name="TextParsingSuccess",
                period=Duration.minutes(5),
                statistic="Sum",
                label="Success"
            ),
            cloudwatch.Metric(
                namespace=f"AiGroceryApp/{self.env_name}",
                metric_name="TextParsingError",
                period=Duration.minutes(5),
                statistic="Sum",
                label="Errors"
            ),
            cloudwatch.Metric(
                namespace=f"AiGroceryApp/{self.env_name}",
                metric_name="TextValidationError",
                period=Duration.minutes(5),
                statistic="Sum",
                label="Validation Errors"
            )
        ]
        
        custom_widgets.append(
            cloudwatch.GraphWidget(
                title="Text Parsing Metrics",
                left=text_parsing_metrics,
                width=12,
                height=6
            )
        )
        
        # Order processing metrics
        order_metrics = [
            cloudwatch.Metric(
                namespace=f"AiGroceryApp/{self.env_name}",
                metric_name="OrderStatusUpdateSuccess",
                period=Duration.minutes(5),
                statistic="Sum",
                label="Status Updates"
            ),
            cloudwatch.Metric(
                namespace=f"AiGroceryApp/{self.env_name}",
                metric_name="ProductMatcherQueueSendSuccess",
                period=Duration.minutes(5),
                statistic="Sum",
                label="Queue Sends"
            )
        ]
        
        custom_widgets.append(
            cloudwatch.GraphWidget(
                title="Order Processing Metrics",
                left=order_metrics,
                width=12,
                height=6
            )
        )
        
        dashboard.add_widgets(cloudwatch.Row(*custom_widgets))
        
        return dashboard
    
    def _create_budget_alert(
        self,
        monthly_limit: float,
        notification_email: Optional[str]
    ) -> None:
        """Create AWS Budget alert for cost monitoring."""
        subscribers = []
        if notification_email:
            subscribers.append(
                budgets.CfnBudget.SubscriberProperty(
                    address=notification_email,
                    subscription_type="EMAIL"
                )
            )
        
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=f"ai-grocery-{self.env_name}-monthly-budget",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=monthly_limit,
                    unit="USD"
                ),
                cost_filters={
                    "TagKeyValue": [
                        f"user:Environment${self.env_name}"
                    ]
                }
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type="ACTUAL",
                        threshold=80,
                        threshold_type="PERCENTAGE"
                    ),
                    subscribers=subscribers if subscribers else [
                        budgets.CfnBudget.SubscriberProperty(
                            address=self.alarm_topic.topic_arn,
                            subscription_type="SNS"
                        )
                    ]
                ),
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type="FORECASTED",
                        threshold=100,
                        threshold_type="PERCENTAGE"
                    ),
                    subscribers=subscribers if subscribers else [
                        budgets.CfnBudget.SubscriberProperty(
                            address=self.alarm_topic.topic_arn,
                            subscription_type="SNS"
                        )
                    ]
                )
            ]
        )
    
    def _create_health_check_lambda(self) -> lambda_.Function:
        """Create Lambda function for health checks."""
        # Create IAM role for health check Lambda
        health_check_role = iam.Role(
            self,
            "HealthCheckRole",
            role_name=f"ai-grocery-health-check-role-{self.env_name}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AWSXRayDaemonWriteAccess"
                )
            ]
        )
        
        # Add permissions to check health of other services
        health_check_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "dynamodb:DescribeTable",
                "sqs:GetQueueAttributes",
                "lambda:GetFunction",
                "cloudwatch:GetMetricData"
            ],
            resources=["*"]  # Health check needs to access multiple resources
        ))
        
        # Create the health check Lambda function
        health_check_function = lambda_.Function(
            self,
            "HealthCheckFunction",
            function_name=f"ai-grocery-health-check-{self.env_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_inline(self._get_health_check_code()),
            timeout=Duration.seconds(30),
            memory_size=256,
            role=health_check_role,
            environment={
                "ENVIRONMENT": self.env_name,
                "DYNAMODB_TABLES": ",".join(
                    table.table_name for table in self.dynamodb_tables.values()
                ),
                "SQS_QUEUES": ",".join(
                    queue.queue_url for queue in self.sqs_queues.values()
                ),
                "LAMBDA_FUNCTIONS": ",".join(
                    func.function_name for func in self.lambda_functions.values()
                )
            },
            tracing=lambda_.Tracing.ACTIVE
        )
        
        # Schedule health check to run every 5 minutes
        events.Rule(
            self,
            "HealthCheckSchedule",
            rule_name=f"ai-grocery-health-check-schedule-{self.env_name}",
            schedule=events.Schedule.rate(Duration.minutes(5)),
            targets=[
                events_targets.LambdaFunction(health_check_function)
            ]
        )
        
        return health_check_function
    
    def _get_health_check_code(self) -> str:
        """Return inline Python code for health check Lambda."""
        return '''
import json
import os
import boto3
from datetime import datetime

dynamodb_client = boto3.client("dynamodb")
sqs_client = boto3.client("sqs")
lambda_client = boto3.client("lambda")
cloudwatch_client = boto3.client("cloudwatch")


def check_dynamodb_tables(table_names):
    """Check health of DynamoDB tables."""
    results = {}
    for table_name in table_names:
        if not table_name:
            continue
        try:
            response = dynamodb_client.describe_table(TableName=table_name)
            status = response["Table"]["TableStatus"]
            results[table_name] = {
                "status": "healthy" if status == "ACTIVE" else "unhealthy",
                "table_status": status,
                "item_count": response["Table"].get("ItemCount", 0)
            }
        except Exception as e:
            results[table_name] = {
                "status": "unhealthy",
                "error": str(e)
            }
    return results


def check_sqs_queues(queue_urls):
    """Check health of SQS queues."""
    results = {}
    for queue_url in queue_urls:
        if not queue_url:
            continue
        try:
            queue_name = queue_url.split("/")[-1]
            response = sqs_client.get_queue_attributes(
                QueueUrl=queue_url,
                AttributeNames=["All"]
            )
            attrs = response.get("Attributes", {})
            results[queue_name] = {
                "status": "healthy",
                "messages_available": int(attrs.get("ApproximateNumberOfMessagesVisible", 0)),
                "messages_in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
                "messages_delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0))
            }
        except Exception as e:
            results[queue_url.split("/")[-1] if queue_url else "unknown"] = {
                "status": "unhealthy",
                "error": str(e)
            }
    return results


def check_lambda_functions(function_names):
    """Check health of Lambda functions."""
    results = {}
    for function_name in function_names:
        if not function_name:
            continue
        try:
            response = lambda_client.get_function(FunctionName=function_name)
            state = response["Configuration"]["State"]
            results[function_name] = {
                "status": "healthy" if state == "Active" else "unhealthy",
                "state": state,
                "runtime": response["Configuration"]["Runtime"],
                "memory_size": response["Configuration"]["MemorySize"],
                "timeout": response["Configuration"]["Timeout"],
                "last_modified": response["Configuration"]["LastModified"]
            }
        except Exception as e:
            results[function_name] = {
                "status": "unhealthy",
                "error": str(e)
            }
    return results


def handler(event, context):
    """Main health check handler."""
    environment = os.environ.get("ENVIRONMENT", "unknown")
    
    # Get resource lists from environment
    dynamodb_tables = [t for t in os.environ.get("DYNAMODB_TABLES", "").split(",") if t]
    sqs_queues = [q for q in os.environ.get("SQS_QUEUES", "").split(",") if q]
    lambda_functions = [f for f in os.environ.get("LAMBDA_FUNCTIONS", "").split(",") if f]
    
    # Perform health checks
    health_status = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "environment": environment,
        "overall_status": "healthy",
        "components": {
            "dynamodb": check_dynamodb_tables(dynamodb_tables),
            "sqs": check_sqs_queues(sqs_queues),
            "lambda": check_lambda_functions(lambda_functions)
        }
    }
    
    # Determine overall status
    for component_type, components in health_status["components"].items():
        for component_name, component_status in components.items():
            if component_status.get("status") == "unhealthy":
                health_status["overall_status"] = "unhealthy"
                break
        if health_status["overall_status"] == "unhealthy":
            break
    
    # Log health status
    print(json.dumps(health_status))
    
    # Emit custom metric for health status
    try:
        cloudwatch_client.put_metric_data(
            Namespace=f"AiGroceryApp/{environment}",
            MetricData=[
                {
                    "MetricName": "HealthCheckStatus",
                    "Value": 1 if health_status["overall_status"] == "healthy" else 0,
                    "Unit": "Count",
                    "Dimensions": [
                        {
                            "Name": "Environment",
                            "Value": environment
                        }
                    ]
                }
            ]
        )
    except Exception as e:
        print(f"Failed to emit health metric: {e}")
    
    return {
        "statusCode": 200 if health_status["overall_status"] == "healthy" else 503,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(health_status)
    }
'''
