"""
Main CDK stack for the AI Grocery App.

This stack defines the core infrastructure components including DynamoDB tables,
Lambda functions, SQS queues, AppSync API, and supporting AWS services.
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_sqs as sqs,
    aws_appsync as appsync,
    aws_iam as iam,
    aws_logs as logs,
    aws_ssm as ssm,
    aws_secretsmanager as secretsmanager,
    aws_kms as kms,
)
from constructs import Construct
from typing import Dict, Any

from infrastructure.config.environment_config import EnvironmentConfig


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
        
        # Create SQS queues
        self.dlq = self._create_dead_letter_queue()
        self.processing_queue = self._create_processing_queue()
        
        # Create Parameter Store parameters
        self._create_parameter_store_config()
        
        # Create Secrets Manager secrets
        self._create_secrets()
        
        # Create IAM roles (will be used by Lambda functions in later tasks)
        self.lambda_execution_role = self._create_lambda_execution_role()
        
        # Create CloudWatch log groups
        self._create_log_groups()
    
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
    
    def _create_processing_queue(self) -> sqs.Queue:
        """Create SQS queue for order processing."""
        return sqs.Queue(
            self,
            "ProcessingQueue",
            queue_name=f"ai-grocery-processing-{self.env_name}",
            visibility_timeout=Duration.seconds(self.config.sqs_visibility_timeout_seconds),
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=self.config.sqs_max_receive_count,
                queue=self.dlq
            ),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
    
    def _create_dead_letter_queue(self) -> sqs.Queue:
        """Create dead letter queue for failed messages."""
        return sqs.Queue(
            self,
            "DeadLetterQueue",
            queue_name=f"ai-grocery-dlq-{self.env_name}",
            retention_period=Duration.seconds(self.config.sqs_message_retention_seconds),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.kms_key
        )
    
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
        secretsmanager.Secret(
            self,
            "PayStackApiKey",
            secret_name=f"ai-grocery/{self.env_name}/paystack-api-key",
            description=f"PayStack API key for {self.env_name} environment",
            encryption_key=self.kms_key
        )
        
        # Bedrock configuration secret (for future use)
        secretsmanager.Secret(
            self,
            "BedrockConfig",
            secret_name=f"ai-grocery/{self.env_name}/bedrock-config",
            description=f"Bedrock configuration for {self.env_name} environment",
            encryption_key=self.kms_key
        )
    
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
        
        # Add permissions for SQS
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "sqs:SendMessage",
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes"
            ],
            resources=[
                self.processing_queue.queue_arn,
                self.dlq.queue_arn
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