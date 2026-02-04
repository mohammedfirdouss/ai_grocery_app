"""
Main CDK stack for the AI Grocery App.

This stack defines the core infrastructure components including DynamoDB tables,
Lambda functions, SQS queues, AppSync API, and supporting AWS services.
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_event_sources,
    aws_sqs as sqs,
    aws_appsync as appsync,
    aws_iam as iam,
    aws_logs as logs,
    aws_ssm as ssm,
    aws_secretsmanager as secretsmanager,
    aws_kms as kms,
    aws_events as events,
    aws_events_targets as events_targets,
    aws_pipes as pipes,
    aws_cognito as cognito,
)
from constructs import Construct
from typing import Dict, Any, Optional
import os

from infrastructure.config.environment_config import EnvironmentConfig
from infrastructure.monitoring.monitoring_construct import MonitoringConstruct


class AiGroceryStack(Stack):
    """Main CDK stack for AI Grocery App infrastructure."""
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: EnvironmentConfig,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.config = config
        self.env_name = config.environment_name
        
        # Create KMS key for encryption
        self.kms_key = self._create_kms_key()
        
        # Create DynamoDB tables
        self.orders_table = self._create_orders_table()
        self.products_table = self._create_products_table()
        self.payment_links_table = self._create_payment_links_table()
        
        # Create SQS queues with dedicated DLQs for each processing stage
        self._create_sqs_infrastructure()
        
        # Create Parameter Store parameters
        self._create_parameter_store_config()
        
        # Create Secrets Manager secrets
        self._create_secrets()
        
        # Create Lambda layer for shared dependencies
        self.shared_layer = self._create_lambda_layer()
        
        # Create IAM roles for Lambda functions
        self.lambda_execution_role = self._create_lambda_execution_role()
        
        # Create Lambda functions
        self._create_lambda_functions()
        
        # Create CloudWatch log groups
        self._create_log_groups()
        
        # Set up EventBridge and EventBridge Pipes
        self._create_eventbridge_infrastructure()
        
        # Create Cognito User Pool for authentication
        self._create_cognito_user_pool()
        
        # Create AppSync GraphQL API
        self._create_appsync_api()
        
        # Create monitoring and observability infrastructure
        self._create_monitoring_infrastructure()
        # Configure Event Handler with AppSync API URL (must be after AppSync creation)
        self._configure_event_handler_appsync()
        
        # Create stack outputs
        self._create_outputs()
    
    def _create_kms_key(self) -> kms.Key:
        """Create KMS key for data encryption."""
        return kms.Key(
            self,
            "AiGroceryKmsKey",
            description=f"KMS key for AI Grocery App {self.env_name} environment",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY if self.env_name == "dev" else RemovalPolicy.RETAIN
        )
    
    def _create_orders_table(self) -> dynamodb.Table:
        """Create DynamoDB table for orders."""
        table = dynamodb.Table(
            self,
            "OrdersTable",
            table_name=f"ai-grocery-orders-{self.env_name}",
            partition_key=dynamodb.Attribute(
                name="order_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=self.config.dynamodb_point_in_time_recovery,
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.kms_key,
            removal_policy=RemovalPolicy.DESTROY if self.env_name == "dev" else RemovalPolicy.RETAIN
        )
        
        # Add GSI for customer email queries
        table.add_global_secondary_index(
            index_name="customer-email-index",
            partition_key=dynamodb.Attribute(
                name="customer_email",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at",
                type=dynamodb.AttributeType.STRING
            )
        )
        
        # Add GSI for status queries
        table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at",
                type=dynamodb.AttributeType.STRING
            )
        )
        
        return table
    
    def _create_products_table(self) -> dynamodb.Table:
        """Create DynamoDB table for products."""
        table = dynamodb.Table(
            self,
            "ProductsTable",
            table_name=f"ai-grocery-products-{self.env_name}",
            partition_key=dynamodb.Attribute(
                name="product_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=self.config.dynamodb_point_in_time_recovery,
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.kms_key,
            removal_policy=RemovalPolicy.DESTROY if self.env_name == "dev" else RemovalPolicy.RETAIN
        )
        
        # Add GSI for category queries
        table.add_global_secondary_index(
            index_name="category-index",
            partition_key=dynamodb.Attribute(
                name="category",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="name",
                type=dynamodb.AttributeType.STRING
            )
        )
        
        # Add GSI for name-based searches
        table.add_global_secondary_index(
            index_name="name-index",
            partition_key=dynamodb.Attribute(
                name="name",
                type=dynamodb.AttributeType.STRING
            )
        )
        
        return table
    
    def _create_payment_links_table(self) -> dynamodb.Table:
        """Create DynamoDB table for payment links with TTL."""
        return dynamodb.Table(
            self,
            "PaymentLinksTable",
            table_name=f"ai-grocery-payment-links-{self.env_name}",
            partition_key=dynamodb.Attribute(
                name="order_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=self.config.dynamodb_point_in_time_recovery,
            time_to_live_attribute="expires_at",
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.kms_key,
            removal_policy=RemovalPolicy.DESTROY if self.env_name == "dev" else RemovalPolicy.RETAIN
        )
    
    def _create_sqs_infrastructure(self) -> None:
        """Create comprehensive SQS infrastructure with dedicated queues and DLQs."""
        
        # Main dead letter queue for general failures
        self.main_dlq = sqs.Queue(
            self,
            "MainDeadLetterQueue",
            queue_name=f"ai-grocery-main-dlq-{self.env_name}",
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
        
        # Text Parser DLQ and Queue
        self.text_parser_dlq = sqs.Queue(
            self,
            "TextParserDLQ",
            queue_name=f"ai-grocery-text-parser-dlq-{self.env_name}",
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
        
        self.text_parser_queue = sqs.Queue(
            self,
            "TextParserQueue",
            queue_name=f"ai-grocery-text-parser-{self.env_name}",
            visibility_timeout=Duration.seconds(self.config.sqs_visibility_timeout_seconds),
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=self.config.sqs_max_receive_count,
                queue=self.text_parser_dlq
            ),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
        
        # Product Matcher DLQ and Queue
        self.product_matcher_dlq = sqs.Queue(
            self,
            "ProductMatcherDLQ",
            queue_name=f"ai-grocery-product-matcher-dlq-{self.env_name}",
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
        
        self.product_matcher_queue = sqs.Queue(
            self,
            "ProductMatcherQueue",
            queue_name=f"ai-grocery-product-matcher-{self.env_name}",
            visibility_timeout=Duration.seconds(self.config.sqs_visibility_timeout_seconds * 2),  # Longer for AI processing
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=self.config.sqs_max_receive_count,
                queue=self.product_matcher_dlq
            ),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
        
        # Payment Processor DLQ and Queue
        self.payment_processor_dlq = sqs.Queue(
            self,
            "PaymentProcessorDLQ",
            queue_name=f"ai-grocery-payment-processor-dlq-{self.env_name}",
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
        
        self.payment_processor_queue = sqs.Queue(
            self,
            "PaymentProcessorQueue",
            queue_name=f"ai-grocery-payment-processor-{self.env_name}",
            visibility_timeout=Duration.seconds(self.config.sqs_visibility_timeout_seconds),
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=self.config.sqs_max_receive_count,
                queue=self.payment_processor_dlq
            ),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
        
        # EventBridge DLQ for failed event processing
        self.eventbridge_dlq = sqs.Queue(
            self,
            "EventBridgeDLQ",
            queue_name=f"ai-grocery-eventbridge-dlq-{self.env_name}",
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
        
        # Legacy processing queue for backward compatibility
        self.dlq = self.main_dlq  # Alias for backward compatibility
        self.processing_queue = self.text_parser_queue  # Alias for backward compatibility
    
    def _create_parameter_store_config(self) -> None:
        """Create Parameter Store parameters for configuration."""
        config_dict = self.config.to_dict()
        
        for key, value in config_dict.items():
            ssm.StringParameter(
                self,
                f"Config{key.replace('_', '').title()}",
                parameter_name=f"/ai-grocery/{self.env_name}/{key}",
                string_value=str(value),
                description=f"AI Grocery App {key} configuration for {self.env_name}"
            )
    
    def _create_secrets(self) -> None:
        """Create Secrets Manager secrets for sensitive configuration."""
        # PayStack API key secret
        self.paystack_secret = secretsmanager.Secret(
            self,
            "PayStackApiKey",
            secret_name=f"ai-grocery/{self.env_name}/paystack-api-key",
            description=f"PayStack API key for {self.env_name} environment",
            encryption_key=self.kms_key
        )
        
        # Bedrock configuration secret (for future use)
        self.bedrock_secret = secretsmanager.Secret(
            self,
            "BedrockConfig",
            secret_name=f"ai-grocery/{self.env_name}/bedrock-config",
            description=f"Bedrock configuration for {self.env_name} environment",
            encryption_key=self.kms_key
        )
    
    def _create_lambda_layer(self) -> lambda_.LayerVersion:
        """Create Lambda layer for shared dependencies."""
        return lambda_.LayerVersion(
            self,
            "SharedDependenciesLayer",
            layer_version_name=f"ai-grocery-shared-deps-{self.env_name}",
            description="Shared dependencies for AI Grocery App Lambda functions",
            code=lambda_.Code.from_asset("lambda_layers/shared"),
            compatible_runtimes=[
                lambda_.Runtime.PYTHON_3_11,
                lambda_.Runtime.PYTHON_3_12
            ],
            compatible_architectures=[lambda_.Architecture.X86_64],
            removal_policy=RemovalPolicy.DESTROY if self.env_name == "dev" else RemovalPolicy.RETAIN
        )
    
    def _create_lambda_functions(self) -> None:
        """Create Lambda functions for processing pipeline."""
        
        # Common Lambda environment variables
        common_env = {
            "ENVIRONMENT": self.env_name,
            "ORDERS_TABLE_NAME": self.orders_table.table_name,
            "PRODUCTS_TABLE_NAME": self.products_table.table_name,
            "PAYMENT_LINKS_TABLE_NAME": self.payment_links_table.table_name,
            "KMS_KEY_ARN": self.kms_key.key_arn,
            "PAYSTACK_SECRET_ARN": self.paystack_secret.secret_arn,
            "BEDROCK_MODEL_ID": self.config.bedrock_model_id,
            "LOG_LEVEL": "DEBUG" if self.env_name == "dev" else "INFO",
            "POWERTOOLS_SERVICE_NAME": "ai-grocery-app",
            "POWERTOOLS_METRICS_NAMESPACE": f"AiGroceryApp/{self.env_name}",
        }
        
        # Text Parser Lambda Function
        self.text_parser_function = lambda_.Function(
            self,
            "TextParserFunction",
            function_name=f"ai-grocery-text-parser-{self.env_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("src/lambdas/text_parser"),
            timeout=Duration.seconds(self.config.lambda_timeout_seconds),
            memory_size=self.config.lambda_memory_mb,
            reserved_concurrent_executions=self.config.lambda_reserved_concurrency,
            role=self.lambda_execution_role,
            layers=[self.shared_layer],
            environment={
                **common_env,
                "PRODUCT_MATCHER_QUEUE_URL": self.product_matcher_queue.queue_url,
            },
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray_tracing else lambda_.Tracing.DISABLED,
        )
        
        # Add SQS event source for Text Parser
        self.text_parser_function.add_event_source(
            lambda_event_sources.SqsEventSource(
                self.text_parser_queue,
                batch_size=1,
                max_batching_window=Duration.seconds(0),
                report_batch_item_failures=True,
            )
        )
        
        # Product Matcher Lambda Function
        self.product_matcher_function = lambda_.Function(
            self,
            "ProductMatcherFunction",
            function_name=f"ai-grocery-product-matcher-{self.env_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("src/lambdas/product_matcher"),
            timeout=Duration.seconds(self.config.lambda_timeout_seconds * 2),  # Longer timeout for AI processing
            memory_size=self.config.lambda_memory_mb * 2,  # More memory for AI processing
            reserved_concurrent_executions=self.config.lambda_reserved_concurrency,
            role=self.lambda_execution_role,
            layers=[self.shared_layer],
            environment={
                **common_env,
                "PAYMENT_PROCESSOR_QUEUE_URL": self.payment_processor_queue.queue_url,
                "BEDROCK_MAX_TOKENS": str(self.config.bedrock_max_tokens),
                "BEDROCK_TEMPERATURE": str(self.config.bedrock_temperature),
            },
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray_tracing else lambda_.Tracing.DISABLED,
        )
        
        # Add SQS event source for Product Matcher
        self.product_matcher_function.add_event_source(
            lambda_event_sources.SqsEventSource(
                self.product_matcher_queue,
                batch_size=1,
                max_batching_window=Duration.seconds(0),
                report_batch_item_failures=True,
            )
        )
        
        # Payment Processor Lambda Function
        self.payment_processor_function = lambda_.Function(
            self,
            "PaymentProcessorFunction",
            function_name=f"ai-grocery-payment-processor-{self.env_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("src/lambdas/payment_processor"),
            timeout=Duration.seconds(self.config.lambda_timeout_seconds),
            memory_size=self.config.lambda_memory_mb,
            reserved_concurrent_executions=self.config.lambda_reserved_concurrency,
            role=self.lambda_execution_role,
            layers=[self.shared_layer],
            environment={
                **common_env,
                "PAYSTACK_BASE_URL": self.config.paystack_base_url,
                "PAYMENT_EXPIRATION_HOURS": "24",
            },
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray_tracing else lambda_.Tracing.DISABLED,
        )
        
        # Add SQS event source for Payment Processor
        self.payment_processor_function.add_event_source(
            lambda_event_sources.SqsEventSource(
                self.payment_processor_queue,
                batch_size=1,
                max_batching_window=Duration.seconds(0),
                report_batch_item_failures=True,
            )
        )
        
        # Payment Webhook Handler Lambda Function (for PayStack webhooks)
        self.payment_webhook_function = lambda_.Function(
            self,
            "PaymentWebhookFunction",
            function_name=f"ai-grocery-payment-webhook-{self.env_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("src/lambdas/payment_webhook"),
            timeout=Duration.seconds(30),
            memory_size=256,
            reserved_concurrent_executions=self.config.lambda_reserved_concurrency,
            role=self.lambda_execution_role,
            layers=[self.shared_layer],
            environment=common_env,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray_tracing else lambda_.Tracing.DISABLED,
        )
        
        # Event Handler Lambda Function (for EventBridge events)
        self.event_handler_function = lambda_.Function(
            self,
            "EventHandlerFunction",
            function_name=f"ai-grocery-event-handler-{self.env_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("src/lambdas/event_handler"),
            timeout=Duration.seconds(30),
            memory_size=256,
            reserved_concurrent_executions=self.config.lambda_reserved_concurrency,
            role=self.lambda_execution_role,
            layers=[self.shared_layer],
            environment=common_env,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray_tracing else lambda_.Tracing.DISABLED,
        )
        
        # Grant additional permissions to Lambda functions
        self._grant_lambda_permissions()
    
    def _create_lambda_execution_role(self) -> iam.Role:
        """Create IAM role for Lambda function execution."""
        role = iam.Role(
            self,
            "LambdaExecutionRole",
            role_name=f"ai-grocery-lambda-role-{self.env_name}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AWSXRayDaemonWriteAccess")
            ]
        )
        
        # Add permissions for DynamoDB
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
                "dynamodb:Query",
                "dynamodb:Scan"
            ],
            resources=[
                self.orders_table.table_arn,
                self.products_table.table_arn,
                self.payment_links_table.table_arn,
                f"{self.orders_table.table_arn}/index/*",
                f"{self.products_table.table_arn}/index/*"
            ]
        ))
        
        # Add permissions for SQS (all queues)
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "sqs:SendMessage",
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes",
                "sqs:ChangeMessageVisibility"
            ],
            resources=[
                self.text_parser_queue.queue_arn,
                self.text_parser_dlq.queue_arn,
                self.product_matcher_queue.queue_arn,
                self.product_matcher_dlq.queue_arn,
                self.payment_processor_queue.queue_arn,
                self.payment_processor_dlq.queue_arn,
                self.main_dlq.queue_arn,
                self.eventbridge_dlq.queue_arn
            ]
        ))
        
        # Add permissions for Parameter Store
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "ssm:GetParameter",
                "ssm:GetParameters",
                "ssm:GetParametersByPath"
            ],
            resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/ai-grocery/{self.env_name}/*"]
        ))
        
        # Add permissions for Secrets Manager
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "secretsmanager:GetSecretValue"
            ],
            resources=[f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:ai-grocery/{self.env_name}/*"]
        ))
        
        # Add permissions for KMS
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kms:Decrypt",
                "kms:DescribeKey"
            ],
            resources=[self.kms_key.key_arn]
        ))
        
        # Add permissions for Bedrock (for future use)
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "bedrock:InvokeAgent",
                "bedrock:InvokeModel"
            ],
            resources=["*"]  # Bedrock resources are region-specific
        ))
        
        return role
    
    def _grant_lambda_permissions(self) -> None:
        """Grant additional permissions to Lambda functions after they are created."""
        
        # Grant SQS send permissions between queues
        self.product_matcher_queue.grant_send_messages(self.text_parser_function)
        self.payment_processor_queue.grant_send_messages(self.product_matcher_function)
        
        # Grant DynamoDB permissions to all Lambda functions
        for func in [
            self.text_parser_function,
            self.product_matcher_function,
            self.payment_processor_function,
            self.payment_webhook_function,
            self.event_handler_function
        ]:
            self.orders_table.grant_read_write_data(func)
            self.products_table.grant_read_data(func)
            self.payment_links_table.grant_read_write_data(func)
            self.kms_key.grant_encrypt_decrypt(func)
        
        # Grant Secrets Manager access
        self.paystack_secret.grant_read(self.payment_processor_function)
        self.paystack_secret.grant_read(self.payment_webhook_function)
        self.bedrock_secret.grant_read(self.product_matcher_function)
    
    def _create_eventbridge_infrastructure(self) -> None:
        """Create EventBridge and EventBridge Pipes for event-driven architecture."""
        
        # Create EventBridge Event Bus for AI Grocery App
        self.event_bus = events.EventBus(
            self,
            "AiGroceryEventBus",
            event_bus_name=f"ai-grocery-events-{self.env_name}"
        )
        
        # Create IAM role for EventBridge Pipes
        pipes_role = iam.Role(
            self,
            "EventBridgePipesRole",
            role_name=f"ai-grocery-pipes-role-{self.env_name}",
            assumed_by=iam.ServicePrincipal("pipes.amazonaws.com"),
        )
        
        # Grant DynamoDB Streams read permissions to Pipes role
        pipes_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "dynamodb:DescribeStream",
                "dynamodb:GetRecords",
                "dynamodb:GetShardIterator",
                "dynamodb:ListStreams"
            ],
            resources=[
                f"{self.orders_table.table_arn}/stream/*"
            ]
        ))
        
        # Grant EventBridge PutEvents permissions to Pipes role
        pipes_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["events:PutEvents"],
            resources=[self.event_bus.event_bus_arn]
        ))
        
        # Grant SQS permissions for DLQ
        pipes_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["sqs:SendMessage"],
            resources=[self.eventbridge_dlq.queue_arn]
        ))
        
        # Grant KMS permissions
        self.kms_key.grant_decrypt(pipes_role)
        
        # Create EventBridge Pipe from DynamoDB Streams to EventBridge
        # Note: The pipe connects DynamoDB Streams to EventBridge for real-time event routing
        self.orders_pipe = pipes.CfnPipe(
            self,
            "OrdersStreamPipe",
            name=f"ai-grocery-orders-pipe-{self.env_name}",
            role_arn=pipes_role.role_arn,
            source=self.orders_table.table_stream_arn,
            source_parameters=pipes.CfnPipe.PipeSourceParametersProperty(
                dynamo_db_stream_parameters=pipes.CfnPipe.PipeSourceDynamoDBStreamParametersProperty(
                    starting_position="LATEST",
                    batch_size=1,
                    maximum_batching_window_in_seconds=0,
                    dead_letter_config=pipes.CfnPipe.DeadLetterConfigProperty(
                        arn=self.eventbridge_dlq.queue_arn
                    ),
                    maximum_record_age_in_seconds=60,
                    maximum_retry_attempts=3,
                    parallelization_factor=1
                )
            ),
            target=self.event_bus.event_bus_arn,
            target_parameters=pipes.CfnPipe.PipeTargetParametersProperty(
                event_bridge_event_bus_parameters=pipes.CfnPipe.PipeTargetEventBridgeEventBusParametersProperty(
                    detail_type="OrderUpdate",
                    source="ai-grocery.orders"
                ),
                input_template='{"orderId": <$.dynamodb.Keys.order_id.S>, "eventType": <$.eventName>, "newImage": <$.dynamodb.NewImage>, "oldImage": <$.dynamodb.OldImage>}'
            ),
            description=f"Pipe from Orders DynamoDB Stream to EventBridge for {self.env_name}"
        )
        
        # Create EventBridge Rules for different event types
        
        # Rule for order status changes - triggers notification handler
        self.order_status_rule = events.Rule(
            self,
            "OrderStatusChangeRule",
            rule_name=f"ai-grocery-order-status-{self.env_name}",
            event_bus=self.event_bus,
            description="Route order status change events to handler",
            event_pattern=events.EventPattern(
                source=["ai-grocery.orders"],
                detail_type=["OrderUpdate"]
            ),
            targets=[
                events_targets.LambdaFunction(
                    self.event_handler_function,
                    dead_letter_queue=self.eventbridge_dlq,
                    max_event_age=Duration.hours(1),
                    retry_attempts=3
                )
            ]
        )
        
        # Rule for processing errors - routes to error handling
        self.processing_error_rule = events.Rule(
            self,
            "ProcessingErrorRule",
            rule_name=f"ai-grocery-processing-error-{self.env_name}",
            event_bus=self.event_bus,
            description="Route processing error events for alerting",
            event_pattern=events.EventPattern(
                source=["ai-grocery.processing"],
                detail_type=["ProcessingError"]
            ),
            targets=[
                events_targets.LambdaFunction(
                    self.event_handler_function,
                    dead_letter_queue=self.eventbridge_dlq,
                    max_event_age=Duration.hours(1),
                    retry_attempts=3
                )
            ]
        )
        
        # Rule for payment events
        self.payment_event_rule = events.Rule(
            self,
            "PaymentEventRule",
            rule_name=f"ai-grocery-payment-event-{self.env_name}",
            event_bus=self.event_bus,
            description="Route payment-related events",
            event_pattern=events.EventPattern(
                source=["ai-grocery.payments"],
                detail_type=["PaymentLinkCreated", "PaymentReceived", "PaymentFailed"]
            ),
            targets=[
                events_targets.LambdaFunction(
                    self.event_handler_function,
                    dead_letter_queue=self.eventbridge_dlq,
                    max_event_age=Duration.hours(1),
                    retry_attempts=3
                )
            ]
        )
    
    def _configure_event_handler_appsync(self) -> None:
        """Configure Event Handler Lambda with AppSync API URL for real-time notifications."""
        
        # Add AppSync API URL as environment variable to Event Handler Lambda
        self.event_handler_function.add_environment(
            "APPSYNC_API_URL",
            self.graphql_api.graphql_url
        )
        
        self.event_handler_function.add_environment(
            "EVENT_BUS_NAME",
            self.event_bus.event_bus_name
        )
        
        # Grant AppSync invoke permissions to Event Handler Lambda
        self.event_handler_function.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["appsync:GraphQL"],
                resources=[
                    f"{self.graphql_api.arn}/*",
                    f"{self.graphql_api.arn}/types/Mutation/*"
                ]
            )
        )
    
    def _create_outputs(self) -> None:
        """Create CloudFormation outputs for key resources."""
        
        # SQS Queue URLs
        CfnOutput(
            self,
            "TextParserQueueUrl",
            value=self.text_parser_queue.queue_url,
            description="URL of the Text Parser SQS Queue",
            export_name=f"ai-grocery-{self.env_name}-text-parser-queue-url"
        )
        
        CfnOutput(
            self,
            "ProductMatcherQueueUrl",
            value=self.product_matcher_queue.queue_url,
            description="URL of the Product Matcher SQS Queue",
            export_name=f"ai-grocery-{self.env_name}-product-matcher-queue-url"
        )
        
        CfnOutput(
            self,
            "PaymentProcessorQueueUrl",
            value=self.payment_processor_queue.queue_url,
            description="URL of the Payment Processor SQS Queue",
            export_name=f"ai-grocery-{self.env_name}-payment-processor-queue-url"
        )
        
        # Lambda Function ARNs
        CfnOutput(
            self,
            "TextParserFunctionArn",
            value=self.text_parser_function.function_arn,
            description="ARN of the Text Parser Lambda Function",
            export_name=f"ai-grocery-{self.env_name}-text-parser-function-arn"
        )
        
        CfnOutput(
            self,
            "ProductMatcherFunctionArn",
            value=self.product_matcher_function.function_arn,
            description="ARN of the Product Matcher Lambda Function",
            export_name=f"ai-grocery-{self.env_name}-product-matcher-function-arn"
        )
        
        CfnOutput(
            self,
            "PaymentProcessorFunctionArn",
            value=self.payment_processor_function.function_arn,
            description="ARN of the Payment Processor Lambda Function",
            export_name=f"ai-grocery-{self.env_name}-payment-processor-function-arn"
        )
        
        # EventBridge Event Bus ARN
        CfnOutput(
            self,
            "EventBusArn",
            value=self.event_bus.event_bus_arn,
            description="ARN of the AI Grocery EventBridge Event Bus",
            export_name=f"ai-grocery-{self.env_name}-event-bus-arn"
        )
        
        # DynamoDB Table Names
        CfnOutput(
            self,
            "OrdersTableName",
            value=self.orders_table.table_name,
            description="Name of the Orders DynamoDB Table",
            export_name=f"ai-grocery-{self.env_name}-orders-table-name"
        )
        
        CfnOutput(
            self,
            "ProductsTableName",
            value=self.products_table.table_name,
            description="Name of the Products DynamoDB Table",
            export_name=f"ai-grocery-{self.env_name}-products-table-name"
        )
        
        # KMS Key ARN
        CfnOutput(
            self,
            "KmsKeyArn",
            value=self.kms_key.key_arn,
            description="ARN of the KMS Key for encryption",
            export_name=f"ai-grocery-{self.env_name}-kms-key-arn"
        )
        
        # AppSync GraphQL API outputs
        CfnOutput(
            self,
            "GraphQLApiUrl",
            value=self.graphql_api.graphql_url,
            description="URL of the AppSync GraphQL API",
            export_name=f"ai-grocery-{self.env_name}-graphql-api-url"
        )
        
        CfnOutput(
            self,
            "GraphQLApiId",
            value=self.graphql_api.api_id,
            description="ID of the AppSync GraphQL API",
            export_name=f"ai-grocery-{self.env_name}-graphql-api-id"
        )
        
        # Cognito User Pool outputs
        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="ID of the Cognito User Pool",
            export_name=f"ai-grocery-{self.env_name}-user-pool-id"
        )
        
        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="ID of the Cognito User Pool Client",
            export_name=f"ai-grocery-{self.env_name}-user-pool-client-id"
        )
    
    def _get_log_retention(self, days: int) -> logs.RetentionDays:
        """Map days to RetentionDays enum."""
        retention_map = {
            1: logs.RetentionDays.ONE_DAY,
            3: logs.RetentionDays.THREE_DAYS,
            5: logs.RetentionDays.FIVE_DAYS,
            7: logs.RetentionDays.ONE_WEEK,
            14: logs.RetentionDays.TWO_WEEKS,
            30: logs.RetentionDays.ONE_MONTH,
            60: logs.RetentionDays.TWO_MONTHS,
            90: logs.RetentionDays.THREE_MONTHS,
            120: logs.RetentionDays.FOUR_MONTHS,
            150: logs.RetentionDays.FIVE_MONTHS,
            180: logs.RetentionDays.SIX_MONTHS,
            365: logs.RetentionDays.ONE_YEAR,
            400: logs.RetentionDays.THIRTEEN_MONTHS,
            545: logs.RetentionDays.EIGHTEEN_MONTHS,
            731: logs.RetentionDays.TWO_YEARS,
            1096: logs.RetentionDays.THREE_YEARS,
            1827: logs.RetentionDays.FIVE_YEARS,
            2192: logs.RetentionDays.SIX_YEARS,
            2557: logs.RetentionDays.SEVEN_YEARS,
            2922: logs.RetentionDays.EIGHT_YEARS,
            3288: logs.RetentionDays.NINE_YEARS,
            3653: logs.RetentionDays.TEN_YEARS,
        }
        
        if days in retention_map:
            return retention_map[days]
        
        # Find closest matching retention period (round up)
        sorted_keys = sorted(retention_map.keys())
        for key in sorted_keys:
            if days <= key:
                return retention_map[key]
        
        # If days exceeds all options, raise an error
        raise ValueError(
            f"Unsupported log retention period: {days} days. "
            f"Supported values: {sorted(retention_map.keys())}"
        )
    
    def _create_log_groups(self) -> None:
        """Create CloudWatch log groups for Lambda functions."""
        retention = self._get_log_retention(self.config.log_retention_days)
        
        # Log group for text parser Lambda
        logs.LogGroup(
            self,
            "TextParserLogGroup",
            log_group_name=f"/aws/lambda/ai-grocery-text-parser-{self.env_name}",
            retention=retention,
            encryption_key=self.kms_key,
            removal_policy=RemovalPolicy.DESTROY
        )
        
        # Log group for product matcher Lambda
        logs.LogGroup(
            self,
            "ProductMatcherLogGroup",
            log_group_name=f"/aws/lambda/ai-grocery-product-matcher-{self.env_name}",
            retention=retention,
            encryption_key=self.kms_key,
            removal_policy=RemovalPolicy.DESTROY
        )
        
        # Log group for payment processor Lambda
        logs.LogGroup(
            self,
            "PaymentProcessorLogGroup",
            log_group_name=f"/aws/lambda/ai-grocery-payment-processor-{self.env_name}",
            retention=retention,
            encryption_key=self.kms_key,
            removal_policy=RemovalPolicy.DESTROY
        )
        
        # Log group for payment webhook Lambda
        logs.LogGroup(
            self,
            "PaymentWebhookLogGroup",
            log_group_name=f"/aws/lambda/ai-grocery-payment-webhook-{self.env_name}",
            retention=retention,
            encryption_key=self.kms_key,
            removal_policy=RemovalPolicy.DESTROY
        )
    
    def _create_cognito_user_pool(self) -> None:
        """Create Cognito User Pool for authentication."""
        
        # Create User Pool
        self.user_pool = cognito.UserPool(
            self,
            "AiGroceryUserPool",
            user_pool_name=f"ai-grocery-user-pool-{self.env_name}",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=False
            ),
            auto_verify=cognito.AutoVerifiedAttrs(
                email=True
            ),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(
                    required=True,
                    mutable=True
                ),
                fullname=cognito.StandardAttribute(
                    required=False,
                    mutable=True
                )
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
                temp_password_validity=Duration.days(7)
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.DESTROY if self.env_name == "dev" else RemovalPolicy.RETAIN
        )
        
        # Create Admin group
        cognito.CfnUserPoolGroup(
            self,
            "AdminGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="Admins",
            description="Administrator group with elevated privileges"
        )
        
        # Create User Pool Client for AppSync
        self.user_pool_client = self.user_pool.add_client(
            "AiGroceryAppClient",
            user_pool_client_name=f"ai-grocery-app-client-{self.env_name}",
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True
            ),
            generate_secret=False,
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30)
        )
    
    def _create_appsync_api(self) -> None:
        """Create AppSync GraphQL API with DynamoDB and SQS data sources."""
        
        # Get the schema file path
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "appsync", "schema", "schema.graphql"
        )
        
        # Create AppSync API with Cognito User Pool and IAM authorization
        # Cognito is used for user-facing operations
        # IAM is used for backend services (Lambda) to publish notifications
        self.graphql_api = appsync.GraphqlApi(
            self,
            "AiGroceryGraphQLApi",
            name=f"ai-grocery-api-{self.env_name}",
            definition=appsync.Definition.from_file(schema_path),
            authorization_config=appsync.AuthorizationConfig(
                default_authorization=appsync.AuthorizationMode(
                    authorization_type=appsync.AuthorizationType.USER_POOL,
                    user_pool_config=appsync.UserPoolConfig(
                        user_pool=self.user_pool
                    )
                ),
                additional_authorization_modes=[
                    appsync.AuthorizationMode(
                        authorization_type=appsync.AuthorizationType.IAM
                    )
                ]
            ),
            log_config=appsync.LogConfig(
                field_log_level=appsync.FieldLogLevel.ALL if self.env_name == "dev" else appsync.FieldLogLevel.ERROR,
                exclude_verbose_content=self.env_name != "dev"
            ),
            xray_enabled=self.config.enable_xray_tracing
        )
        
        # Create DynamoDB data source for Orders table
        orders_data_source = self.graphql_api.add_dynamo_db_data_source(
            "OrdersDataSource",
            self.orders_table,
            description="DynamoDB data source for Orders table"
        )
        
        # Create DynamoDB data source for Payment Links table
        payment_links_data_source = self.graphql_api.add_dynamo_db_data_source(
            "PaymentLinksDataSource",
            self.payment_links_table,
            description="DynamoDB data source for Payment Links table"
        )
        
        # Create HTTP data source for SQS integration
        sqs_data_source = self.graphql_api.add_http_data_source(
            "SQSDataSource",
            f"https://sqs.{self.region}.amazonaws.com",
            description="HTTP data source for SQS integration",
            authorization_config=appsync.AwsIamConfig(
                signing_region=self.region,
                signing_service_name="sqs"
            )
        )
        
        # Grant SQS permissions to the HTTP data source service role
        self.text_parser_queue.grant_send_messages(sqs_data_source.grant_principal)
        
        # Get resolver template paths
        resolvers_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "appsync", "resolvers"
        )
        
        # Helper function to read VTL templates
        def read_template(filename: str) -> str:
            with open(os.path.join(resolvers_path, filename), "r") as f:
                return f.read()
        
        # Create Query resolvers
        
        # getOrder resolver
        orders_data_source.create_resolver(
            "GetOrderResolver",
            type_name="Query",
            field_name="getOrder",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Query.getOrder.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Query.getOrder.response.vtl")
            )
        )
        
        # listOrders resolver
        orders_data_source.create_resolver(
            "ListOrdersResolver",
            type_name="Query",
            field_name="listOrders",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Query.listOrders.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Query.listOrders.response.vtl")
            )
        )
        
        # getMyOrders resolver
        orders_data_source.create_resolver(
            "GetMyOrdersResolver",
            type_name="Query",
            field_name="getMyOrders",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Query.getMyOrders.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Query.getMyOrders.response.vtl")
            )
        )
        
        # getPaymentLink resolver
        payment_links_data_source.create_resolver(
            "GetPaymentLinkResolver",
            type_name="Query",
            field_name="getPaymentLink",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Query.getPaymentLink.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Query.getPaymentLink.response.vtl")
            )
        )
        
        # Create Mutation resolvers using Pipeline resolver for submitGroceryList
        # First, create the DynamoDB function for storing the order
        submit_dynamo_function = appsync.AppsyncFunction(
            self,
            "SubmitGroceryListDynamoFunction",
            name="submitGroceryListDynamo",
            api=self.graphql_api,
            data_source=orders_data_source,
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.submitGroceryList.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.submitGroceryList.response.vtl")
            )
        )
        
        # Create the SQS function for queuing the message
        # First, inject the queue URL into the request template
        sqs_request_template = read_template("Mutation.submitGroceryList.sqs.request.vtl")
        sqs_request_template_with_url = f'$util.qr($ctx.stash.put("queueUrl", "{self.text_parser_queue.queue_url}"))\n{sqs_request_template}'
        
        submit_sqs_function = appsync.AppsyncFunction(
            self,
            "SubmitGroceryListSQSFunction",
            name="submitGroceryListSQS",
            api=self.graphql_api,
            data_source=sqs_data_source,
            request_mapping_template=appsync.MappingTemplate.from_string(
                sqs_request_template_with_url
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.submitGroceryList.sqs.response.vtl")
            )
        )
        
        # Create Pipeline resolver for submitGroceryList
        appsync.Resolver(
            self,
            "SubmitGroceryListResolver",
            api=self.graphql_api,
            type_name="Mutation",
            field_name="submitGroceryList",
            pipeline_config=[submit_dynamo_function, submit_sqs_function],
            request_mapping_template=appsync.MappingTemplate.from_string("{}"),
            response_mapping_template=appsync.MappingTemplate.from_string("$util.toJson($ctx.prev.result)")
        )
        
        # Create functions for cancelOrder pipeline resolver
        # First function: Query order and validate
        cancel_order_query_function = appsync.AppsyncFunction(
            self,
            "CancelOrderQueryFunction",
            name="cancelOrderQuery",
            api=self.graphql_api,
            data_source=orders_data_source,
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.cancelOrder.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.cancelOrder.response.vtl")
            )
        )
        
        # Second function: Update order status
        cancel_order_update_function = appsync.AppsyncFunction(
            self,
            "CancelOrderUpdateFunction",
            name="cancelOrderUpdate",
            api=self.graphql_api,
            data_source=orders_data_source,
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.cancelOrder.update.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.cancelOrder.update.response.vtl")
            )
        )
        
        # Create Pipeline resolver for cancelOrder
        appsync.Resolver(
            self,
            "CancelOrderResolver",
            api=self.graphql_api,
            type_name="Mutation",
            field_name="cancelOrder",
            pipeline_config=[cancel_order_query_function, cancel_order_update_function],
            request_mapping_template=appsync.MappingTemplate.from_string("{}"),
            response_mapping_template=appsync.MappingTemplate.from_string("$util.toJson($ctx.prev.result)")
        )
        
        # Create Subscription resolvers (these use NONE data source)
        none_data_source = self.graphql_api.add_none_data_source(
            "NoneDataSource",
            description="None data source for subscriptions"
        )
        
        # onOrderStatusChanged subscription
        none_data_source.create_resolver(
            "OnOrderStatusChangedResolver",
            type_name="Subscription",
            field_name="onOrderStatusChanged",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Subscription.onOrderStatusChanged.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Subscription.onOrderStatusChanged.response.vtl")
            )
        )
        
        # onProcessingEvent subscription
        none_data_source.create_resolver(
            "OnProcessingEventResolver",
            type_name="Subscription",
            field_name="onProcessingEvent",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Subscription.onProcessingEvent.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Subscription.onProcessingEvent.response.vtl")
            )
        )
        
        # onPaymentStatusChanged subscription
        none_data_source.create_resolver(
            "OnPaymentStatusChangedResolver",
            type_name="Subscription",
            field_name="onPaymentStatusChanged",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Subscription.onPaymentStatusChanged.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Subscription.onPaymentStatusChanged.response.vtl")
            )
        )
        
        # onErrorNotification subscription
        none_data_source.create_resolver(
            "OnErrorNotificationResolver",
            type_name="Subscription",
            field_name="onErrorNotification",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Subscription.onErrorNotification.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Subscription.onErrorNotification.response.vtl")
            )
        )
        
        # Create publish mutation resolvers (IAM auth for backend services)
        
        # publishOrderUpdate mutation
        none_data_source.create_resolver(
            "PublishOrderUpdateResolver",
            type_name="Mutation",
            field_name="publishOrderUpdate",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.publishOrderUpdate.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.publishOrderUpdate.response.vtl")
            )
        )
        
        # publishProcessingEvent mutation
        none_data_source.create_resolver(
            "PublishProcessingEventResolver",
            type_name="Mutation",
            field_name="publishProcessingEvent",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.publishProcessingEvent.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.publishProcessingEvent.response.vtl")
            )
        )
        
        # publishPaymentStatus mutation
        none_data_source.create_resolver(
            "PublishPaymentStatusResolver",
            type_name="Mutation",
            field_name="publishPaymentStatus",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.publishPaymentStatus.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.publishPaymentStatus.response.vtl")
            )
        )
        
        # broadcastErrorNotification mutation
        none_data_source.create_resolver(
            "BroadcastErrorNotificationResolver",
            type_name="Mutation",
            field_name="broadcastErrorNotification",
            request_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.broadcastErrorNotification.request.vtl")
            ),
            response_mapping_template=appsync.MappingTemplate.from_string(
                read_template("Mutation.broadcastErrorNotification.response.vtl")
            )
        )
        
        # Create AppSync log group
        logs.LogGroup(
            self,
            "AppSyncLogGroup",
            log_group_name=f"/aws/appsync/apis/{self.graphql_api.api_id}",
            retention=self._get_log_retention(self.config.log_retention_days),
            removal_policy=RemovalPolicy.DESTROY
        )
    
    def _create_monitoring_infrastructure(self) -> None:
        """Create monitoring and observability infrastructure."""
        # Collect Lambda functions
        lambda_functions = {
            "text-parser": self.text_parser_function,
            "product-matcher": self.product_matcher_function,
            "payment-processor": self.payment_processor_function,
            "payment-webhook": self.payment_webhook_function,
            "event-handler": self.event_handler_function,
        }
        
        # Collect SQS queues
        sqs_queues = {
            "text-parser": self.text_parser_queue,
            "text-parser-dlq": self.text_parser_dlq,
            "product-matcher": self.product_matcher_queue,
            "product-matcher-dlq": self.product_matcher_dlq,
            "payment-processor": self.payment_processor_queue,
            "payment-processor-dlq": self.payment_processor_dlq,
            "eventbridge-dlq": self.eventbridge_dlq,
            "main-dlq": self.main_dlq,
        }
        
        # Collect DynamoDB tables
        dynamodb_tables = {
            "orders": self.orders_table,
            "products": self.products_table,
            "payment-links": self.payment_links_table,
        }
        
        # Create monitoring construct using configuration values
        self.monitoring = MonitoringConstruct(
            self,
            "Monitoring",
            env_name=self.env_name,
            lambda_functions=lambda_functions,
            sqs_queues=sqs_queues,
            dynamodb_tables=dynamodb_tables,
            alarm_email=self.config.alarm_email,
            monthly_budget_limit=self.config.monthly_budget_limit
        )