"""
Environment-specific configuration management for the AI Grocery App.

This module provides configuration classes for different deployment environments
(dev, staging, production) following AWS best practices for parameter management.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
import os


@dataclass
class EnvironmentConfig:
    """Environment-specific configuration settings."""
    
    environment_name: str
    aws_region: str
    
    # DynamoDB settings
    dynamodb_billing_mode: str
    dynamodb_point_in_time_recovery: bool
    
    # Lambda settings
    lambda_timeout_seconds: int
    lambda_memory_mb: int
    lambda_reserved_concurrency: Optional[int]
    
    # SQS settings
    sqs_visibility_timeout_seconds: int
    sqs_message_retention_seconds: int
    sqs_max_receive_count: int
    
    # AppSync settings
    appsync_log_level: str
    appsync_field_log_level: str
    
    # Bedrock settings
    bedrock_model_id: str
    bedrock_max_tokens: int
    bedrock_temperature: float
    bedrock_max_retries: int
    bedrock_retry_delay_seconds: float
    bedrock_uncertainty_threshold: float
    bedrock_guardrails_enabled: bool
    bedrock_knowledge_base_enabled: bool
    
    # PayStack settings
    paystack_base_url: str
    
    # Monitoring settings
    enable_xray_tracing: bool
    log_retention_days: int
    alarm_email: Optional[str] = None
    monthly_budget_limit: float = 100.0
    
    @classmethod
    def get_config(cls, environment: str) -> "EnvironmentConfig":
        """Get configuration for the specified environment."""
        configs = {
            "dev": cls._dev_config(),
            "staging": cls._staging_config(),
            "production": cls._production_config()
        }
        
        if environment not in configs:
            raise ValueError(f"Unknown environment: {environment}")
        
        return configs[environment]
    
    @classmethod
    def _dev_config(cls) -> "EnvironmentConfig":
        """Development environment configuration."""
        return cls(
            environment_name="dev",
            aws_region="us-east-1",
            
            # DynamoDB - On-demand for dev flexibility
            dynamodb_billing_mode="PAY_PER_REQUEST",
            dynamodb_point_in_time_recovery=False,
            
            # Lambda - Lower limits for cost optimization
            lambda_timeout_seconds=30,
            lambda_memory_mb=512,
            lambda_reserved_concurrency=None,
            
            # SQS - Standard settings
            sqs_visibility_timeout_seconds=60,
            sqs_message_retention_seconds=1209600,  # 14 days
            sqs_max_receive_count=3,
            
            # AppSync - Debug logging enabled
            appsync_log_level="ALL",
            appsync_field_log_level="ALL",
            
            # Bedrock - Claude 3.5 Sonnet with retry and guardrails
            bedrock_model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
            bedrock_max_tokens=4096,
            bedrock_temperature=0.1,
            bedrock_max_retries=3,
            bedrock_retry_delay_seconds=1.0,
            bedrock_uncertainty_threshold=0.7,
            bedrock_guardrails_enabled=True,
            bedrock_knowledge_base_enabled=False,  # Can be enabled when KB is set up
            
            # PayStack - Test environment
            paystack_base_url="https://api.paystack.co",
            
            # Monitoring - Detailed for debugging
            enable_xray_tracing=True,
            log_retention_days=7,
            alarm_email=None,
            monthly_budget_limit=50.0
        )
    
    @classmethod
    def _staging_config(cls) -> "EnvironmentConfig":
        """Staging environment configuration."""
        return cls(
            environment_name="staging",
            aws_region="us-east-1",
            
            # DynamoDB - On-demand with backup
            dynamodb_billing_mode="PAY_PER_REQUEST",
            dynamodb_point_in_time_recovery=True,
            
            # Lambda - Production-like settings
            lambda_timeout_seconds=60,
            lambda_memory_mb=1024,
            lambda_reserved_concurrency=10,
            
            # SQS - Extended retention
            sqs_visibility_timeout_seconds=120,
            sqs_message_retention_seconds=1209600,  # 14 days
            sqs_max_receive_count=5,
            
            # AppSync - Error logging only
            appsync_log_level="ERROR",
            appsync_field_log_level="ERROR",
            
            # Bedrock - Claude 3.5 Sonnet with production-like settings
            bedrock_model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
            bedrock_max_tokens=4096,
            bedrock_temperature=0.1,
            bedrock_max_retries=4,
            bedrock_retry_delay_seconds=2.0,
            bedrock_uncertainty_threshold=0.7,
            bedrock_guardrails_enabled=True,
            bedrock_knowledge_base_enabled=True,
            
            # PayStack - Production API
            paystack_base_url="https://api.paystack.co",
            
            # Monitoring - Balanced
            enable_xray_tracing=True,
            log_retention_days=30,
            alarm_email=None,
            monthly_budget_limit=200.0
        )
    
    @classmethod
    def _production_config(cls) -> "EnvironmentConfig":
        """Production environment configuration."""
        return cls(
            environment_name="production",
            aws_region="us-east-1",
            
            # DynamoDB - Provisioned with backup
            dynamodb_billing_mode="PAY_PER_REQUEST",
            dynamodb_point_in_time_recovery=True,
            
            # Lambda - Optimized for performance
            lambda_timeout_seconds=300,
            lambda_memory_mb=2048,
            lambda_reserved_concurrency=50,
            
            # SQS - Extended settings for reliability
            sqs_visibility_timeout_seconds=300,
            sqs_message_retention_seconds=1209600,  # 14 days
            sqs_max_receive_count=10,
            
            # AppSync - Error logging only
            appsync_log_level="ERROR",
            appsync_field_log_level="NONE",
            
            # Bedrock - Claude 3.5 Sonnet with production settings
            bedrock_model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
            bedrock_max_tokens=4096,
            bedrock_temperature=0.1,
            bedrock_max_retries=5,
            bedrock_retry_delay_seconds=2.0,
            bedrock_uncertainty_threshold=0.7,
            bedrock_guardrails_enabled=True,
            bedrock_knowledge_base_enabled=True,
            
            # PayStack - Production API
            paystack_base_url="https://api.paystack.co",
            
            # Monitoring - Essential only
            enable_xray_tracing=True,
            log_retention_days=90,
            alarm_email=None,
            monthly_budget_limit=1000.0
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for parameter store."""
        return {
            "environment_name": self.environment_name,
            "aws_region": self.aws_region,
            "dynamodb_billing_mode": self.dynamodb_billing_mode,
            "lambda_timeout_seconds": str(self.lambda_timeout_seconds),
            "lambda_memory_mb": str(self.lambda_memory_mb),
            "sqs_visibility_timeout_seconds": str(self.sqs_visibility_timeout_seconds),
            "bedrock_model_id": self.bedrock_model_id,
            "bedrock_max_tokens": str(self.bedrock_max_tokens),
            "bedrock_temperature": str(self.bedrock_temperature),
            "bedrock_max_retries": str(self.bedrock_max_retries),
            "bedrock_retry_delay_seconds": str(self.bedrock_retry_delay_seconds),
            "bedrock_uncertainty_threshold": str(self.bedrock_uncertainty_threshold),
            "bedrock_guardrails_enabled": str(self.bedrock_guardrails_enabled),
            "bedrock_knowledge_base_enabled": str(self.bedrock_knowledge_base_enabled),
            "paystack_base_url": self.paystack_base_url,
            "log_retention_days": str(self.log_retention_days)
        }