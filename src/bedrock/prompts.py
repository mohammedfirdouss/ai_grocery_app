"""
Amazon Bedrock Prompt Templates and Instructions Module.

This module provides prompt templates, system instructions, and prompt building
utilities for the grocery item extraction use case.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from string import Template
from enum import Enum


class PromptType(str, Enum):
    """Types of prompts for different operations."""
    EXTRACTION = "extraction"
    MATCHING = "matching"
    CLARIFICATION = "clarification"
    SUMMARIZATION = "summarization"


@dataclass
class SystemInstruction:
    """System-level instruction for the AI agent."""
    
    role: str
    capabilities: List[str]
    constraints: List[str]
    output_format: str
    examples: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_text(self) -> str:
        """Convert to text format for model input."""
        capabilities_text = "\n".join(f"- {c}" for c in self.capabilities)
        constraints_text = "\n".join(f"- {c}" for c in self.constraints)
        
        text = f"""You are {self.role}.

Your capabilities:
{capabilities_text}

Constraints:
{constraints_text}

Output format:
{self.output_format}"""
        
        if self.examples:
            examples_text = "\n\n".join(
                f"Example {i+1}:\nInput: {ex.get('input', '')}\nOutput: {ex.get('output', '')}"
                for i, ex in enumerate(self.examples)
            )
            text += f"\n\nExamples:\n{examples_text}"
        
        return text


class PromptTemplates:
    """
    Collection of prompt templates for grocery app operations.
    
    Templates use Python string.Template for safe substitution.
    """
    
    # Main extraction prompt
    GROCERY_EXTRACTION_SYSTEM = """You are a specialized grocery list processing assistant. Your task is to accurately extract and structure grocery items from natural language text.

Your capabilities:
- Parse grocery lists in various formats (bullet points, numbered lists, free text, voice transcriptions)
- Recognize common grocery items, produce, meat, dairy, pantry items, and household products
- Infer quantities and units from context when not explicitly stated
- Identify item specifications (brand preferences, sizes, organic/non-organic)
- Provide confidence scores for each extraction based on clarity of the input

Constraints:
- Only extract actual grocery/shopping items - ignore non-shopping content
- Do not make up items not mentioned in the text
- Do not provide medical, financial, or legal advice
- Do not process requests unrelated to grocery shopping
- Always provide valid JSON output

Output Format:
You must return a valid JSON object with the following structure:
{
  "items": [
    {
      "name": "item name (normalized to standard product name)",
      "quantity": numeric value (default to 1 if not specified),
      "unit": "unit of measurement (pieces, kg, lb, oz, liters, etc.)",
      "specifications": ["list", "of", "specifications"],
      "confidence": 0.0-1.0 (how confident you are in this extraction),
      "original_text": "the exact text segment this was extracted from"
    }
  ],
  "unrecognized_text": ["any text segments that couldn't be identified as grocery items"],
  "parsing_notes": "any relevant notes about the extraction process"
}"""

    GROCERY_EXTRACTION_USER = Template("""Please extract grocery items from the following text and return structured JSON.

Input text:
$grocery_text

Remember to:
1. Normalize item names to standard product names
2. Include confidence scores for each item
3. Handle quantities and units appropriately
4. Note any ambiguous items or specifications
5. Return ONLY valid JSON, no additional text""")

    # Product matching prompt
    PRODUCT_MATCHING_SYSTEM = """You are a product matching assistant that maps extracted grocery items to specific products in a catalog.

Your task:
- Match extracted items to the most appropriate product from the catalog
- Consider synonyms, brand variations, and common misspellings
- Provide match confidence based on how well the item matches the product
- Suggest alternatives when exact matches aren't available

Constraints:
- Only match to products in the provided catalog
- Prefer exact matches over fuzzy matches
- Consider quantity and unit compatibility

Output Format:
{
  "matches": [
    {
      "extracted_item": "original item name",
      "matched_product_id": "catalog product ID or null if no match",
      "matched_product_name": "matched product name",
      "match_type": "exact|fuzzy|category|none",
      "match_confidence": 0.0-1.0,
      "alternatives": ["list", "of", "alternative", "product_ids"]
    }
  ]
}"""

    PRODUCT_MATCHING_USER = Template("""Match the following extracted items to products in the catalog.

Extracted Items:
$items_json

Product Catalog:
$catalog_json

Return JSON with matches for each extracted item.""")

    # Clarification prompt for ambiguous items
    CLARIFICATION_SYSTEM = """You are a helpful assistant that identifies ambiguous grocery items and generates clarification questions.

Your task:
- Identify items that could have multiple interpretations
- Generate clear, specific questions to resolve ambiguity
- Prioritize questions that would most impact the order

Output Format:
{
  "ambiguous_items": [
    {
      "item_name": "the ambiguous item",
      "ambiguity_type": "quantity|brand|variety|size",
      "question": "question to ask the user",
      "options": ["possible", "options", "if applicable"]
    }
  ]
}"""

    CLARIFICATION_USER = Template("""Review these extracted items and identify any that need clarification:

Items:
$items_json

Identify ambiguous items and generate clarification questions.""")

    # Summarization prompt
    SUMMARIZATION_SYSTEM = """You are an assistant that summarizes grocery orders for confirmation.

Create a clear, readable summary that:
- Groups items by category
- Shows quantities and estimated prices
- Highlights any items that may need substitution
- Provides a total item count and estimated total

Keep the summary concise and easy to scan."""

    SUMMARIZATION_USER = Template("""Summarize this grocery order:

Items:
$items_json

Create a clear summary for customer confirmation.""")

    # Few-shot examples for extraction
    EXTRACTION_EXAMPLES = [
        {
            "input": "I need milk, 2 dozen eggs, and some bread",
            "output": """{
  "items": [
    {"name": "milk", "quantity": 1, "unit": "gallon", "specifications": [], "confidence": 0.85, "original_text": "milk"},
    {"name": "eggs", "quantity": 24, "unit": "pieces", "specifications": ["large"], "confidence": 0.95, "original_text": "2 dozen eggs"},
    {"name": "bread", "quantity": 1, "unit": "loaf", "specifications": [], "confidence": 0.9, "original_text": "some bread"}
  ],
  "unrecognized_text": [],
  "parsing_notes": "Quantity for milk defaulted to 1 gallon. 'Some bread' interpreted as 1 loaf."
}"""
        },
        {
            "input": "Get me 500g of chicken breast, organic if possible, also 1kg rice and tomatoes",
            "output": """{
  "items": [
    {"name": "chicken breast", "quantity": 500, "unit": "g", "specifications": ["organic preferred"], "confidence": 0.95, "original_text": "500g of chicken breast, organic if possible"},
    {"name": "rice", "quantity": 1, "unit": "kg", "specifications": [], "confidence": 0.98, "original_text": "1kg rice"},
    {"name": "tomatoes", "quantity": 1, "unit": "kg", "specifications": [], "confidence": 0.8, "original_text": "tomatoes"}
  ],
  "unrecognized_text": [],
  "parsing_notes": "Tomatoes quantity not specified, defaulted to 1kg."
}"""
        },
        {
            "input": "Apples (red ones please) x5, butter 250g, and don't forget the coffee beans",
            "output": """{
  "items": [
    {"name": "apples", "quantity": 5, "unit": "pieces", "specifications": ["red variety"], "confidence": 0.95, "original_text": "Apples (red ones please) x5"},
    {"name": "butter", "quantity": 250, "unit": "g", "specifications": [], "confidence": 0.98, "original_text": "butter 250g"},
    {"name": "coffee beans", "quantity": 1, "unit": "bag", "specifications": [], "confidence": 0.85, "original_text": "coffee beans"}
  ],
  "unrecognized_text": ["don't forget the"],
  "parsing_notes": "Coffee beans quantity defaulted to 1 bag."
}"""
        }
    ]

    @classmethod
    def get_extraction_prompt(
        cls,
        grocery_text: str,
        include_examples: bool = True
    ) -> Dict[str, str]:
        """
        Build extraction prompt with system and user messages.
        
        Args:
            grocery_text: Raw grocery list text
            include_examples: Whether to include few-shot examples
            
        Returns:
            Dict with 'system' and 'user' keys
        """
        system = cls.GROCERY_EXTRACTION_SYSTEM
        
        if include_examples:
            examples_text = "\n\nExamples:\n"
            for i, ex in enumerate(cls.EXTRACTION_EXAMPLES, 1):
                examples_text += f"\nExample {i}:\nInput: {ex['input']}\nOutput: {ex['output']}\n"
            system += examples_text
        
        user = cls.GROCERY_EXTRACTION_USER.safe_substitute(
            grocery_text=grocery_text
        )
        
        return {"system": system, "user": user}

    @classmethod
    def get_matching_prompt(
        cls,
        items_json: str,
        catalog_json: str
    ) -> Dict[str, str]:
        """
        Build product matching prompt.
        
        Args:
            items_json: JSON string of extracted items
            catalog_json: JSON string of product catalog
            
        Returns:
            Dict with 'system' and 'user' keys
        """
        user = cls.PRODUCT_MATCHING_USER.safe_substitute(
            items_json=items_json,
            catalog_json=catalog_json
        )
        
        return {"system": cls.PRODUCT_MATCHING_SYSTEM, "user": user}

    @classmethod
    def get_clarification_prompt(cls, items_json: str) -> Dict[str, str]:
        """
        Build clarification prompt for ambiguous items.
        
        Args:
            items_json: JSON string of extracted items
            
        Returns:
            Dict with 'system' and 'user' keys
        """
        user = cls.CLARIFICATION_USER.safe_substitute(items_json=items_json)
        return {"system": cls.CLARIFICATION_SYSTEM, "user": user}

    @classmethod
    def get_summarization_prompt(cls, items_json: str) -> Dict[str, str]:
        """
        Build order summarization prompt.
        
        Args:
            items_json: JSON string of order items
            
        Returns:
            Dict with 'system' and 'user' keys
        """
        user = cls.SUMMARIZATION_USER.safe_substitute(items_json=items_json)
        return {"system": cls.SUMMARIZATION_SYSTEM, "user": user}


class PromptBuilder:
    """
    Builder class for constructing complex prompts with context injection.
    
    Supports building prompts with knowledge base context, conversation
    history, and dynamic instructions.
    """
    
    def __init__(self, prompt_type: PromptType = PromptType.EXTRACTION):
        """
        Initialize prompt builder.
        
        Args:
            prompt_type: Type of prompt to build
        """
        self.prompt_type = prompt_type
        self._system_message: Optional[str] = None
        self._user_message: Optional[str] = None
        self._context_documents: List[Dict[str, Any]] = []
        self._conversation_history: List[Dict[str, str]] = []
        self._additional_instructions: List[str] = []
    
    def with_system_message(self, message: str) -> "PromptBuilder":
        """Set the system message."""
        self._system_message = message
        return self
    
    def with_user_message(self, message: str) -> "PromptBuilder":
        """Set the user message."""
        self._user_message = message
        return self
    
    def with_context_documents(
        self,
        documents: List[Dict[str, Any]]
    ) -> "PromptBuilder":
        """
        Add context documents from knowledge base.
        
        Args:
            documents: List of document dicts with 'content' and 'metadata'
        """
        self._context_documents.extend(documents)
        return self
    
    def with_conversation_history(
        self,
        history: List[Dict[str, str]]
    ) -> "PromptBuilder":
        """
        Add conversation history for multi-turn interactions.
        
        Args:
            history: List of message dicts with 'role' and 'content'
        """
        self._conversation_history.extend(history)
        return self
    
    def with_additional_instructions(
        self,
        instructions: List[str]
    ) -> "PromptBuilder":
        """Add additional instructions to the prompt."""
        self._additional_instructions.extend(instructions)
        return self
    
    def build(self) -> Dict[str, Any]:
        """
        Build the final prompt structure.
        
        Returns:
            Dict with 'system', 'messages', and optional 'context' keys
        """
        # Get base prompts based on type
        if self.prompt_type == PromptType.EXTRACTION:
            base_system = PromptTemplates.GROCERY_EXTRACTION_SYSTEM
        elif self.prompt_type == PromptType.MATCHING:
            base_system = PromptTemplates.PRODUCT_MATCHING_SYSTEM
        elif self.prompt_type == PromptType.CLARIFICATION:
            base_system = PromptTemplates.CLARIFICATION_SYSTEM
        else:
            base_system = PromptTemplates.SUMMARIZATION_SYSTEM
        
        # Override system message if provided
        system = self._system_message or base_system
        
        # Add additional instructions
        if self._additional_instructions:
            instructions_text = "\n\nAdditional Instructions:\n" + "\n".join(
                f"- {inst}" for inst in self._additional_instructions
            )
            system += instructions_text
        
        # Build messages list
        messages = []
        
        # Add conversation history
        messages.extend(self._conversation_history)
        
        # Build context injection if documents provided
        context_text = ""
        if self._context_documents:
            context_text = "\n\nRelevant Context from Product Catalog:\n"
            for i, doc in enumerate(self._context_documents[:5], 1):  # Limit to 5 docs
                content = doc.get("content", "")[:500]  # Limit content length
                metadata = doc.get("metadata", {})
                context_text += f"\n--- Document {i} ---\n"
                if metadata:
                    context_text += f"Source: {metadata.get('source', 'unknown')}\n"
                context_text += f"{content}\n"
        
        # Add user message
        if self._user_message:
            user_content = self._user_message
            if context_text:
                user_content = context_text + "\n\n" + user_content
            messages.append({"role": "user", "content": user_content})
        
        return {
            "system": system,
            "messages": messages,
            "context_documents_count": len(self._context_documents),
            "has_conversation_history": len(self._conversation_history) > 0,
        }
    
    def build_for_bedrock(self) -> Dict[str, Any]:
        """
        Build prompt in Bedrock API format.
        
        Returns:
            Dict ready for Bedrock invoke_model API
        """
        prompt_data = self.build()
        
        return {
            "system": prompt_data["system"],
            "messages": prompt_data["messages"],
        }


class AgentInstructions:
    """
    Instructions and configurations for Bedrock Agent setup.
    
    Provides agent-level instructions for agent creation in AWS.
    """
    
    AGENT_INSTRUCTION = """You are an AI-powered grocery list processing agent for a shopping application. Your primary function is to help users convert their natural language grocery lists into structured, actionable shopping orders.

## Core Responsibilities

1. **Text Understanding**: Parse and understand grocery lists in various formats including:
   - Bullet points and numbered lists
   - Free-form text descriptions
   - Voice transcription text (may contain errors)
   - Mixed language inputs

2. **Item Extraction**: Extract individual grocery items with:
   - Normalized product names
   - Quantities and units
   - Brand or quality specifications
   - Confidence scores for each extraction

3. **Product Matching**: Match extracted items against our product catalog to:
   - Find exact product matches
   - Suggest alternatives when needed
   - Calculate accurate pricing

4. **Quality Assurance**: Ensure accuracy by:
   - Flagging uncertain extractions for review
   - Identifying ambiguous items
   - Requesting clarification when needed

## Constraints

- Only process grocery and household shopping related requests
- Do not provide medical, financial, or legal advice
- Do not store or process sensitive personal information beyond what's needed for the order
- Always respond with properly formatted JSON for structured outputs
- If unable to process a request, explain why clearly

## Response Guidelines

- Be concise and accurate
- Prioritize precision over assumptions
- When uncertain, indicate low confidence rather than guessing
- Format all structured outputs as valid JSON"""

    ACTION_GROUP_DESCRIPTION = """This action group provides tools for grocery list processing:

1. extract_items: Parse natural language text and extract grocery items
2. match_products: Match extracted items against product catalog
3. get_product_details: Retrieve details for specific products
4. calculate_order_total: Calculate total price for matched items
5. check_availability: Check product availability and inventory"""

    KNOWLEDGE_BASE_DESCRIPTION = """This knowledge base contains:

1. Product Catalog: Complete list of available grocery products with:
   - Product names, descriptions, and categories
   - Pricing information
   - Availability status
   - Common synonyms and alternative names

2. Unit Conversions: Standard conversions between units (kg to lb, etc.)

3. Product Categories: Hierarchical category structure for organizing products

Use this knowledge base to:
- Match user requests to specific products
- Provide accurate product information
- Suggest alternatives for out-of-stock items"""

    @classmethod
    def get_agent_instruction(cls) -> str:
        """Get the main agent instruction."""
        return cls.AGENT_INSTRUCTION
    
    @classmethod
    def get_action_group_description(cls) -> str:
        """Get the action group description."""
        return cls.ACTION_GROUP_DESCRIPTION
    
    @classmethod
    def get_knowledge_base_description(cls) -> str:
        """Get the knowledge base description."""
        return cls.KNOWLEDGE_BASE_DESCRIPTION
