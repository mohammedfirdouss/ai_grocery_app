"""
Amazon Bedrock Agent Configuration Module.

This module provides configuration classes for Amazon Bedrock integration,
including model settings, guardrails, and knowledge base configuration.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum


class BedrockModelFamily(str, Enum):
    """Supported Bedrock model families."""
    ANTHROPIC = "anthropic"
    AMAZON = "amazon"
    META = "meta"
    COHERE = "cohere"


class ContentFilterStrength(str, Enum):
    """Guardrail content filter strength levels."""
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class BedrockModelConfig:
    """Configuration for Bedrock model settings."""
    
    # Model identification
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    model_family: BedrockModelFamily = BedrockModelFamily.ANTHROPIC
    
    # Inference parameters
    max_tokens: int = 4096
    temperature: float = 0.1
    top_p: float = 0.9
    top_k: int = 250
    stop_sequences: List[str] = field(default_factory=list)
    
    # API version (for Anthropic models)
    anthropic_version: str = "bedrock-2023-05-31"
    
    @classmethod
    def for_grocery_extraction(cls) -> "BedrockModelConfig":
        """
        Create optimized configuration for grocery item extraction.
        
        Uses low temperature for consistent, deterministic outputs
        and sufficient tokens for detailed item lists.
        """
        return cls(
            model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
            model_family=BedrockModelFamily.ANTHROPIC,
            max_tokens=4096,
            temperature=0.1,  # Low for consistency
            top_p=0.9,
            top_k=250,
            stop_sequences=["```", "\n\n\n"],
        )
    
    @classmethod
    def for_product_matching(cls) -> "BedrockModelConfig":
        """
        Create optimized configuration for product matching.
        
        Uses even lower temperature for highly consistent matching results.
        """
        return cls(
            model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
            model_family=BedrockModelFamily.ANTHROPIC,
            max_tokens=2048,
            temperature=0.05,  # Very low for consistent matching
            top_p=0.95,
            top_k=200,
            stop_sequences=["```"],
        )
    
    def to_inference_params(self) -> Dict[str, Any]:
        """Convert to Bedrock inference parameters format."""
        params = {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        
        if self.model_family == BedrockModelFamily.ANTHROPIC:
            params["anthropic_version"] = self.anthropic_version
            if self.top_k:
                params["top_k"] = self.top_k
            if self.stop_sequences:
                params["stop_sequences"] = self.stop_sequences
        
        return params


@dataclass
class GuardrailConfig:
    """Configuration for Bedrock Guardrails content filtering."""
    
    # Guardrail identification
    guardrail_id: Optional[str] = None
    guardrail_version: str = "DRAFT"
    
    # Content filter settings
    hate_filter_strength: ContentFilterStrength = ContentFilterStrength.HIGH
    insults_filter_strength: ContentFilterStrength = ContentFilterStrength.HIGH
    sexual_filter_strength: ContentFilterStrength = ContentFilterStrength.HIGH
    violence_filter_strength: ContentFilterStrength = ContentFilterStrength.MEDIUM
    misconduct_filter_strength: ContentFilterStrength = ContentFilterStrength.HIGH
    
    # Topic policy - blocked topics
    blocked_topics: List[str] = field(default_factory=lambda: [
        "financial_advice",
        "medical_advice",
        "legal_advice",
        "personal_information_requests",
    ])
    
    # Word policy - blocked words/phrases
    blocked_words: List[str] = field(default_factory=list)
    managed_word_lists: List[str] = field(default_factory=lambda: ["profanity"])
    
    # PII handling
    pii_entities_to_block: List[str] = field(default_factory=lambda: [
        "CREDIT_DEBIT_CARD_NUMBER",
        "DRIVER_ID",
        "PASSPORT_NUMBER",
        "PIN",
        "US_SOCIAL_SECURITY_NUMBER",
    ])
    pii_entities_to_anonymize: List[str] = field(default_factory=lambda: [
        "EMAIL",
        "PHONE",
        "ADDRESS",
        "NAME",
    ])
    
    @classmethod
    def for_grocery_app(cls) -> "GuardrailConfig":
        """
        Create guardrail configuration optimized for grocery app use case.
        
        Allows product-related content while blocking inappropriate requests.
        """
        return cls(
            hate_filter_strength=ContentFilterStrength.HIGH,
            insults_filter_strength=ContentFilterStrength.MEDIUM,
            sexual_filter_strength=ContentFilterStrength.HIGH,
            violence_filter_strength=ContentFilterStrength.MEDIUM,
            misconduct_filter_strength=ContentFilterStrength.HIGH,
            blocked_topics=[
                "financial_advice",
                "medical_advice",
                "legal_advice",
                "personal_information_requests",
                "weapons",
                "drugs",
            ],
            blocked_words=[],
            managed_word_lists=["profanity"],
            pii_entities_to_block=[
                "CREDIT_DEBIT_CARD_NUMBER",
                "PIN",
            ],
            pii_entities_to_anonymize=[
                "EMAIL",
                "PHONE",
            ],
        )
    
    def to_guardrail_params(self) -> Optional[Dict[str, Any]]:
        """Convert to Bedrock guardrail parameters format."""
        if not self.guardrail_id:
            return None
        
        return {
            "guardrailIdentifier": self.guardrail_id,
            "guardrailVersion": self.guardrail_version,
        }
    
    def to_cdk_content_filters(self) -> List[Dict[str, Any]]:
        """Convert to CDK-compatible content filter configuration."""
        return [
            {
                "type": "HATE",
                "inputStrength": self.hate_filter_strength.value,
                "outputStrength": self.hate_filter_strength.value,
            },
            {
                "type": "INSULTS",
                "inputStrength": self.insults_filter_strength.value,
                "outputStrength": self.insults_filter_strength.value,
            },
            {
                "type": "SEXUAL",
                "inputStrength": self.sexual_filter_strength.value,
                "outputStrength": self.sexual_filter_strength.value,
            },
            {
                "type": "VIOLENCE",
                "inputStrength": self.violence_filter_strength.value,
                "outputStrength": self.violence_filter_strength.value,
            },
            {
                "type": "MISCONDUCT",
                "inputStrength": self.misconduct_filter_strength.value,
                "outputStrength": self.misconduct_filter_strength.value,
            },
        ]


@dataclass
class KnowledgeBaseConfig:
    """Configuration for Bedrock Knowledge Base integration."""
    
    # Knowledge base identification
    knowledge_base_id: Optional[str] = None
    
    # Data source settings
    data_source_type: str = "S3"
    s3_bucket_arn: Optional[str] = None
    s3_prefix: str = "product-catalog/"
    
    # Embedding model
    embedding_model_arn: str = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v1"
    
    # Vector store settings
    vector_store_type: str = "OPENSEARCH_SERVERLESS"
    vector_field_name: str = "bedrock-knowledge-base-default-vector"
    text_field_name: str = "AMAZON_BEDROCK_TEXT_CHUNK"
    metadata_field_name: str = "AMAZON_BEDROCK_METADATA"
    
    # Retrieval settings
    number_of_results: int = 5
    
    @classmethod
    def for_product_catalog(cls, s3_bucket_arn: str) -> "KnowledgeBaseConfig":
        """Create knowledge base config for product catalog."""
        return cls(
            s3_bucket_arn=s3_bucket_arn,
            s3_prefix="product-catalog/",
            number_of_results=10,  # More results for better product matching
        )
    
    def to_retrieval_config(self) -> Dict[str, Any]:
        """Convert to Bedrock retrieval configuration."""
        if not self.knowledge_base_id:
            return {}
        
        return {
            "knowledgeBaseId": self.knowledge_base_id,
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {
                    "numberOfResults": self.number_of_results,
                }
            }
        }


@dataclass
class BedrockConfig:
    """
    Main configuration class for Amazon Bedrock integration.
    
    Aggregates model, guardrail, and knowledge base configurations
    with environment-aware defaults.
    """
    
    # Environment
    environment: str = "dev"
    region: str = "us-east-1"
    
    # Component configurations
    model_config: BedrockModelConfig = field(default_factory=BedrockModelConfig.for_grocery_extraction)
    guardrail_config: GuardrailConfig = field(default_factory=GuardrailConfig.for_grocery_app)
    knowledge_base_config: Optional[KnowledgeBaseConfig] = None
    
    # Retry settings
    max_retries: int = 3
    base_retry_delay_seconds: float = 1.0
    max_retry_delay_seconds: float = 30.0
    retry_jitter: bool = True
    
    # Timeout settings
    request_timeout_seconds: int = 60
    connection_timeout_seconds: int = 10
    
    # Rate limiting settings
    requests_per_minute: int = 60
    tokens_per_minute: int = 100000
    
    # Logging settings
    log_requests: bool = True
    log_responses: bool = True
    log_confidence_scores: bool = True
    uncertainty_threshold: float = 0.7  # Log items below this confidence
    
    @classmethod
    def from_environment(cls) -> "BedrockConfig":
        """
        Create configuration from environment variables.
        
        Loads settings from environment with sensible defaults.
        """
        environment = os.environ.get("ENVIRONMENT", "dev")
        region = os.environ.get("AWS_REGION", "us-east-1")
        
        model_config = BedrockModelConfig(
            model_id=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
            max_tokens=int(os.environ.get("BEDROCK_MAX_TOKENS", "4096")),
            temperature=float(os.environ.get("BEDROCK_TEMPERATURE", "0.1")),
        )
        
        guardrail_config = GuardrailConfig.for_grocery_app()
        guardrail_id = os.environ.get("BEDROCK_GUARDRAIL_ID")
        if guardrail_id:
            guardrail_config.guardrail_id = guardrail_id
            guardrail_config.guardrail_version = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
        
        knowledge_base_config = None
        kb_id = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID")
        if kb_id:
            knowledge_base_config = KnowledgeBaseConfig(knowledge_base_id=kb_id)
        
        return cls(
            environment=environment,
            region=region,
            model_config=model_config,
            guardrail_config=guardrail_config,
            knowledge_base_config=knowledge_base_config,
            max_retries=int(os.environ.get("BEDROCK_MAX_RETRIES", "3")),
            request_timeout_seconds=int(os.environ.get("BEDROCK_TIMEOUT_SECONDS", "60")),
            uncertainty_threshold=float(os.environ.get("BEDROCK_UNCERTAINTY_THRESHOLD", "0.7")),
        )
    
    @classmethod
    def for_dev(cls) -> "BedrockConfig":
        """Create development environment configuration."""
        return cls(
            environment="dev",
            model_config=BedrockModelConfig.for_grocery_extraction(),
            guardrail_config=GuardrailConfig.for_grocery_app(),
            max_retries=3,
            log_requests=True,
            log_responses=True,
            log_confidence_scores=True,
        )
    
    @classmethod
    def for_production(cls) -> "BedrockConfig":
        """Create production environment configuration."""
        return cls(
            environment="production",
            model_config=BedrockModelConfig.for_grocery_extraction(),
            guardrail_config=GuardrailConfig.for_grocery_app(),
            max_retries=5,
            max_retry_delay_seconds=60.0,
            request_timeout_seconds=120,
            log_requests=False,  # Reduce logging overhead
            log_responses=False,
            log_confidence_scores=True,  # Keep confidence logging for monitoring
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for serialization."""
        return {
            "environment": self.environment,
            "region": self.region,
            "model_id": self.model_config.model_id,
            "max_tokens": self.model_config.max_tokens,
            "temperature": self.model_config.temperature,
            "max_retries": self.max_retries,
            "request_timeout_seconds": self.request_timeout_seconds,
            "guardrail_enabled": self.guardrail_config.guardrail_id is not None,
            "knowledge_base_enabled": self.knowledge_base_config is not None,
        }
