"""
Amazon Bedrock Agent Client Module.

This module provides a robust client for invoking Amazon Bedrock models
with retry logic, rate limiting handling, and comprehensive error handling.
"""

import json
import time
import random
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable, Union
from functools import wraps
from contextlib import contextmanager
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from botocore.config import Config as BotoConfig
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit

from src.bedrock.config import BedrockConfig, BedrockModelConfig
from src.bedrock.guardrails import (
    BedrockGuardrailsManager,
    InputGuardrails,
    OutputGuardrails,
    GuardrailResult,
)
from src.bedrock.prompts import PromptTemplates, PromptBuilder, PromptType

logger = Logger(child=True)
tracer = Tracer()
metrics = Metrics()


class BedrockClientError(Exception):
    """Base exception for Bedrock client errors."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        retry_after: Optional[int] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.retry_after = retry_after
        self.original_error = original_error


class RateLimitError(BedrockClientError):
    """Exception for rate limit errors."""
    pass


class ModelUnavailableError(BedrockClientError):
    """Exception for model unavailability errors."""
    pass


class GuardrailBlockedError(BedrockClientError):
    """Exception for guardrail blocked requests."""
    pass


class ContentFilteredError(BedrockClientError):
    """Exception for content filtered by guardrails."""
    pass


@dataclass
class InvocationResult:
    """Result of a Bedrock model invocation."""
    
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: Optional[str] = None
    model_id: str = ""
    latency_ms: int = 0
    retry_count: int = 0
    guardrail_result: Optional[GuardrailResult] = None
    raw_response: Optional[Dict[str, Any]] = None
    
    @property
    def total_tokens(self) -> int:
        """Total tokens used in invocation."""
        return self.input_tokens + self.output_tokens
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "content_length": len(self.content),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "stop_reason": self.stop_reason,
            "model_id": self.model_id,
            "latency_ms": self.latency_ms,
            "retry_count": self.retry_count,
            "guardrail_violations": (
                len(self.guardrail_result.violations)
                if self.guardrail_result else 0
            ),
        }


class RetryStrategy:
    """
    Retry strategy with exponential backoff and jitter.
    
    Implements AWS best practices for handling transient failures
    and rate limiting.
    """
    
    # Error codes that should trigger retry
    RETRYABLE_ERRORS = {
        "ThrottlingException",
        "ServiceUnavailableException",
        "ModelStreamErrorException",
        "InternalServerException",
        "ModelTimeoutException",
        "ModelErrorException",
    }
    
    # HTTP status codes that should trigger retry
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: bool = True,
    ):
        """
        Initialize retry strategy.
        
        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
            jitter: Whether to add random jitter
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
    
    def should_retry(self, error: Exception, attempt: int) -> bool:
        """
        Determine if the error should trigger a retry.
        
        Args:
            error: The exception that occurred
            attempt: Current attempt number (0-indexed)
            
        Returns:
            True if should retry, False otherwise
        """
        if attempt >= self.max_retries:
            return False
        
        if isinstance(error, ClientError):
            error_code = error.response.get("Error", {}).get("Code", "")
            if error_code in self.RETRYABLE_ERRORS:
                return True
            
            status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            if status_code in self.RETRYABLE_STATUS_CODES:
                return True
        
        if isinstance(error, RateLimitError):
            return True
        
        return False
    
    def get_delay(self, attempt: int, retry_after: Optional[int] = None) -> float:
        """
        Calculate delay before next retry.
        
        Args:
            attempt: Current attempt number (0-indexed)
            retry_after: Server-specified retry delay if available
            
        Returns:
            Delay in seconds
        """
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        
        # Exponential backoff: base * 2^attempt
        delay = self.base_delay * (2 ** attempt)
        delay = min(delay, self.max_delay)
        
        # Add jitter (±25%)
        if self.jitter:
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0, delay)
    
    def execute_with_retry(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute a function with retry logic.
        
        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            The last exception if all retries fail
        """
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                
                if not self.should_retry(e, attempt):
                    raise
                
                # Extract retry-after header if available
                retry_after = None
                if isinstance(e, ClientError):
                    retry_after_str = e.response.get("ResponseMetadata", {}).get(
                        "HTTPHeaders", {}
                    ).get("retry-after")
                    if retry_after_str:
                        try:
                            retry_after = int(retry_after_str)
                        except ValueError:
                            pass
                
                delay = self.get_delay(attempt, retry_after)
                
                logger.warning(
                    f"Retry attempt {attempt + 1}/{self.max_retries}",
                    extra={
                        "error": str(e),
                        "delay_seconds": delay,
                        "attempt": attempt + 1,
                    }
                )
                
                metrics.add_metric(
                    name="BedrockRetryAttempt",
                    unit=MetricUnit.Count,
                    value=1
                )
                
                time.sleep(delay)
        
        raise last_error


class BedrockAgentClient:
    """
    Client for invoking Amazon Bedrock models with robust error handling.
    
    Features:
    - Retry logic with exponential backoff for rate limits
    - Input and output guardrails
    - Comprehensive metrics and logging
    - Support for streaming and non-streaming invocations
    """
    
    def __init__(
        self,
        config: Optional[BedrockConfig] = None,
        boto_session: Optional[boto3.Session] = None,
    ):
        """
        Initialize Bedrock client.
        
        Args:
            config: Bedrock configuration
            boto_session: Optional boto3 session for custom credentials
        """
        self.config = config or BedrockConfig.from_environment()
        
        # Configure boto client with timeouts
        boto_config = BotoConfig(
            connect_timeout=self.config.connection_timeout_seconds,
            read_timeout=self.config.request_timeout_seconds,
            retries={"max_attempts": 0}  # We handle retries ourselves
        )
        
        session = boto_session or boto3.Session()
        self.bedrock_runtime = session.client(
            "bedrock-runtime",
            region_name=self.config.region,
            config=boto_config
        )
        
        # Initialize guardrails manager
        self.guardrails = BedrockGuardrailsManager(
            input_guardrails=InputGuardrails(),
            output_guardrails=OutputGuardrails(),
        )
        
        # Initialize retry strategy
        self.retry_strategy = RetryStrategy(
            max_retries=self.config.max_retries,
            base_delay=self.config.base_retry_delay_seconds,
            max_delay=self.config.max_retry_delay_seconds,
            jitter=self.config.retry_jitter,
        )
    
    @tracer.capture_method
    def invoke_model(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model_config: Optional[BedrockModelConfig] = None,
        skip_input_guardrails: bool = False,
        skip_output_guardrails: bool = False,
    ) -> InvocationResult:
        """
        Invoke Bedrock model with the given prompt.
        
        Args:
            prompt: User prompt text
            system_prompt: Optional system prompt
            model_config: Optional model configuration override
            skip_input_guardrails: Skip input guardrail evaluation
            skip_output_guardrails: Skip output guardrail evaluation
            
        Returns:
            InvocationResult with model response
            
        Raises:
            GuardrailBlockedError: If input is blocked by guardrails
            RateLimitError: If rate limit is exceeded after retries
            BedrockClientError: For other API errors
        """
        start_time = time.time()
        config = model_config or self.config.model_config
        
        # Evaluate input guardrails
        input_result = None
        if not skip_input_guardrails:
            input_result = self.guardrails.evaluate_input(prompt)
            if not input_result.is_allowed:
                logger.error(
                    "Input blocked by guardrails",
                    extra={"violations": [v.to_dict() for v in input_result.violations]}
                )
                metrics.add_metric(
                    name="GuardrailInputBlocked",
                    unit=MetricUnit.Count,
                    value=1
                )
                raise GuardrailBlockedError(
                    "Input blocked by guardrails",
                    error_code="GUARDRAIL_BLOCKED"
                )
            # Use sanitized input if available
            prompt = input_result.sanitized_input or prompt
        
        # Log request if configured
        if self.config.log_requests:
            logger.info(
                "Invoking Bedrock model",
                extra={
                    "model_id": config.model_id,
                    "prompt_length": len(prompt),
                    "has_system_prompt": system_prompt is not None,
                }
            )
        
        # Build request body
        request_body = self._build_request_body(
            prompt=prompt,
            system_prompt=system_prompt,
            config=config,
        )
        
        # Execute with retry
        retry_count = 0
        try:
            result = self.retry_strategy.execute_with_retry(
                self._invoke_model_api,
                request_body=request_body,
                model_id=config.model_id,
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            
            if error_code == "ThrottlingException":
                raise RateLimitError(
                    "Rate limit exceeded after retries",
                    error_code=error_code,
                    original_error=e
                )
            elif error_code == "ServiceUnavailableException":
                raise ModelUnavailableError(
                    "Model is currently unavailable",
                    error_code=error_code,
                    original_error=e
                )
            else:
                raise BedrockClientError(
                    f"Bedrock API error: {error_code}",
                    error_code=error_code,
                    original_error=e
                )
        
        # Parse response
        response_body = json.loads(result["body"].read())
        content = self._extract_content(response_body)
        
        # Evaluate output guardrails
        output_result = None
        if not skip_output_guardrails:
            output_result = self.guardrails.evaluate_output(content)
            if not output_result.is_allowed:
                logger.warning(
                    "Output has guardrail violations",
                    extra={"violations": [v.to_dict() for v in output_result.violations]}
                )
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        # Extract token usage
        usage = response_body.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        
        # Log response if configured
        if self.config.log_responses:
            logger.info(
                "Bedrock model response received",
                extra={
                    "model_id": config.model_id,
                    "content_length": len(content),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                }
            )
        
        # Emit metrics
        metrics.add_metric(
            name="BedrockInvocationLatency",
            unit=MetricUnit.Milliseconds,
            value=latency_ms
        )
        metrics.add_metric(
            name="BedrockInputTokens",
            unit=MetricUnit.Count,
            value=input_tokens
        )
        metrics.add_metric(
            name="BedrockOutputTokens",
            unit=MetricUnit.Count,
            value=output_tokens
        )
        
        return InvocationResult(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=response_body.get("stop_reason"),
            model_id=config.model_id,
            latency_ms=latency_ms,
            retry_count=retry_count,
            guardrail_result=output_result,
            raw_response=response_body,
        )
    
    def _build_request_body(
        self,
        prompt: str,
        system_prompt: Optional[str],
        config: BedrockModelConfig,
    ) -> Dict[str, Any]:
        """Build request body for Bedrock API."""
        messages = [{"role": "user", "content": prompt}]
        
        body = {
            "anthropic_version": config.anthropic_version,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "messages": messages,
        }
        
        if system_prompt:
            body["system"] = system_prompt
        
        if config.top_k:
            body["top_k"] = config.top_k
        
        if config.stop_sequences:
            body["stop_sequences"] = config.stop_sequences
        
        return body
    
    def _invoke_model_api(
        self,
        request_body: Dict[str, Any],
        model_id: str,
    ) -> Dict[str, Any]:
        """Make the actual API call to Bedrock."""
        invoke_params = {
            "modelId": model_id,
            "contentType": "application/json",
            "accept": "application/json",
            "body": json.dumps(request_body),
        }
        
        # Add guardrail parameters if configured
        guardrail_params = self.config.guardrail_config.to_guardrail_params()
        if guardrail_params:
            invoke_params["guardrailIdentifier"] = guardrail_params["guardrailIdentifier"]
            invoke_params["guardrailVersion"] = guardrail_params["guardrailVersion"]
        
        return self.bedrock_runtime.invoke_model(**invoke_params)
    
    def _extract_content(self, response_body: Dict[str, Any]) -> str:
        """Extract text content from Bedrock response."""
        content_list = response_body.get("content", [])
        
        if not content_list:
            return ""
        
        # Handle different content types
        text_parts = []
        for content_item in content_list:
            if isinstance(content_item, dict):
                if content_item.get("type") == "text":
                    text_parts.append(content_item.get("text", ""))
                elif "text" in content_item:
                    text_parts.append(content_item["text"])
            elif isinstance(content_item, str):
                text_parts.append(content_item)
        
        return "\n".join(text_parts)
    
    @tracer.capture_method
    def extract_grocery_items(
        self,
        grocery_text: str,
        include_examples: bool = True,
    ) -> InvocationResult:
        """
        Extract grocery items from natural language text.
        
        Convenience method that uses the grocery extraction prompt template.
        
        Args:
            grocery_text: Raw grocery list text
            include_examples: Whether to include few-shot examples
            
        Returns:
            InvocationResult with JSON response
        """
        prompts = PromptTemplates.get_extraction_prompt(
            grocery_text=grocery_text,
            include_examples=include_examples,
        )
        
        return self.invoke_model(
            prompt=prompts["user"],
            system_prompt=prompts["system"],
        )
    
    @tracer.capture_method
    def invoke_with_knowledge_base(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> InvocationResult:
        """
        Invoke model with knowledge base context retrieval.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            
        Returns:
            InvocationResult with context-enriched response
        """
        if not self.config.knowledge_base_config:
            logger.warning("Knowledge base not configured, invoking without context")
            return self.invoke_model(prompt, system_prompt)
        
        # Retrieve relevant documents from knowledge base
        try:
            kb_client = boto3.client(
                "bedrock-agent-runtime",
                region_name=self.config.region
            )
            
            retrieval_config = self.config.knowledge_base_config.to_retrieval_config()
            
            response = kb_client.retrieve(
                knowledgeBaseId=retrieval_config["knowledgeBaseId"],
                retrievalQuery={"text": prompt},
                retrievalConfiguration=retrieval_config.get("retrievalConfiguration", {})
            )
            
            # Extract documents
            documents = []
            for result in response.get("retrievalResults", []):
                documents.append({
                    "content": result.get("content", {}).get("text", ""),
                    "metadata": result.get("metadata", {}),
                })
            
            # Build prompt with context
            builder = PromptBuilder(PromptType.EXTRACTION)
            builder.with_system_message(system_prompt or PromptTemplates.GROCERY_EXTRACTION_SYSTEM)
            builder.with_context_documents(documents)
            builder.with_user_message(prompt)
            
            built_prompt = builder.build_for_bedrock()
            
            return self.invoke_model(
                prompt=built_prompt["messages"][-1]["content"],
                system_prompt=built_prompt["system"],
            )
            
        except ClientError as e:
            logger.warning(
                "Knowledge base retrieval failed, falling back to direct invocation",
                extra={"error": str(e)}
            )
            return self.invoke_model(prompt, system_prompt)
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Bedrock connection.
        
        Returns:
            Dict with health status information
        """
        try:
            # Simple invocation to verify connectivity
            result = self.invoke_model(
                prompt="Respond with 'OK' only.",
                model_config=BedrockModelConfig(
                    max_tokens=10,
                    temperature=0,
                ),
                skip_input_guardrails=True,
                skip_output_guardrails=True,
            )
            
            return {
                "status": "healthy",
                "model_id": self.config.model_config.model_id,
                "latency_ms": result.latency_ms,
                "region": self.config.region,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "model_id": self.config.model_config.model_id,
                "region": self.config.region,
            }


# Convenience function for creating client
def create_bedrock_client(
    environment: Optional[str] = None,
    **kwargs
) -> BedrockAgentClient:
    """
    Create a BedrockAgentClient with environment-appropriate configuration.
    
    Args:
        environment: Environment name (dev, staging, production)
        **kwargs: Additional configuration overrides
        
    Returns:
        Configured BedrockAgentClient
    """
    if environment == "production":
        config = BedrockConfig.for_production()
    elif environment == "dev":
        config = BedrockConfig.for_dev()
    else:
        config = BedrockConfig.from_environment()
    
    # Apply any overrides
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    
    return BedrockAgentClient(config=config)
