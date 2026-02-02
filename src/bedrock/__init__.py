"""
Amazon Bedrock Agent Integration Module.

This module provides comprehensive integration with Amazon Bedrock for the AI Grocery App,
including agent configuration, client implementation, prompt management, and structured
data extraction with confidence scoring.
"""

from src.bedrock.config import BedrockConfig, BedrockModelConfig, GuardrailConfig
from src.bedrock.client import BedrockAgentClient
from src.bedrock.extractors import GroceryItemExtractor, ExtractionResult
from src.bedrock.prompts import PromptTemplates, PromptBuilder

__all__ = [
    "BedrockConfig",
    "BedrockModelConfig",
    "GuardrailConfig",
    "BedrockAgentClient",
    "GroceryItemExtractor",
    "ExtractionResult",
    "PromptTemplates",
    "PromptBuilder",
]
