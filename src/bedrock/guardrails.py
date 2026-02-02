"""
Amazon Bedrock Guardrails Module.

This module provides guardrail configuration and enforcement for content filtering,
ensuring safe and appropriate AI responses for the grocery app use case.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from aws_lambda_powertools import Logger

logger = Logger(child=True)


class GuardrailAction(str, Enum):
    """Actions that can be taken by guardrails."""
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    ANONYMIZE = "ANONYMIZE"
    LOG = "LOG"


class ViolationType(str, Enum):
    """Types of guardrail violations."""
    CONTENT_FILTER = "CONTENT_FILTER"
    TOPIC_POLICY = "TOPIC_POLICY"
    WORD_POLICY = "WORD_POLICY"
    PII_DETECTED = "PII_DETECTED"
    MALFORMED_INPUT = "MALFORMED_INPUT"
    INJECTION_ATTEMPT = "INJECTION_ATTEMPT"


@dataclass
class GuardrailViolation:
    """Represents a guardrail violation."""
    violation_type: ViolationType
    severity: str
    message: str
    matched_content: Optional[str] = None
    action_taken: GuardrailAction = GuardrailAction.LOG
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "violation_type": self.violation_type.value,
            "severity": self.severity,
            "message": self.message,
            "matched_content": self.matched_content[:50] if self.matched_content else None,
            "action_taken": self.action_taken.value,
        }


@dataclass
class GuardrailResult:
    """Result of guardrail evaluation."""
    is_allowed: bool
    violations: List[GuardrailViolation] = field(default_factory=list)
    sanitized_input: Optional[str] = None
    original_input: Optional[str] = None
    
    @property
    def has_violations(self) -> bool:
        """Check if any violations were detected."""
        return len(self.violations) > 0
    
    @property
    def blocking_violations(self) -> List[GuardrailViolation]:
        """Get violations that resulted in blocking."""
        return [v for v in self.violations if v.action_taken == GuardrailAction.BLOCK]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "is_allowed": self.is_allowed,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "input_modified": self.sanitized_input != self.original_input,
        }


class InputGuardrails:
    """
    Client-side input guardrails for pre-processing before Bedrock API calls.
    
    Provides local content filtering and validation to reduce API calls
    for clearly inappropriate content and to sanitize inputs.
    """
    
    # Patterns for potentially harmful content
    INJECTION_PATTERNS = [
        r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|commands?)",
        r"(?i)system\s*:\s*",
        r"(?i)assistant\s*:\s*",
        r"(?i)human\s*:\s*",
        r"(?i)pretend\s+(you\s+are|to\s+be)",
        r"(?i)act\s+as\s+(if\s+)?you",
        r"(?i)disregard\s+(all\s+)?(safety|guidelines|rules)",
        r"(?i)new\s+instruction",
        r"(?i)jailbreak",
        r"(?i)bypass\s+(filter|guardrail|safety)",
    ]
    
    # Non-grocery topics to filter
    NON_GROCERY_PATTERNS = [
        r"(?i)\b(bitcoin|crypto|cryptocurrency|forex|stock\s+market)\b",
        r"(?i)\b(password|login|credential|api\s+key|secret\s+key)\b",
        r"(?i)\b(hack|exploit|malware|virus|phishing)\b",
        r"(?i)\b(weapon|ammunition|explosive|bomb)\b",
        r"(?i)\b(prescription|medication|pharmacy)\b(?!.*grocery)",
    ]
    
    # PII patterns for detection
    PII_PATTERNS = {
        "credit_card": r"\b(?:\d{4}[- ]?){3}\d{4}\b",
        "ssn": r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b",
        "phone": r"\b(?:\+?1[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b",
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    }
    
    # Maximum input length
    MAX_INPUT_LENGTH = 10000
    MIN_INPUT_LENGTH = 3
    
    def __init__(
        self,
        block_injections: bool = True,
        block_non_grocery: bool = True,
        anonymize_pii: bool = True,
        max_input_length: int = MAX_INPUT_LENGTH,
    ):
        """
        Initialize input guardrails.
        
        Args:
            block_injections: Block prompt injection attempts
            block_non_grocery: Block non-grocery related content
            anonymize_pii: Anonymize detected PII
            max_input_length: Maximum allowed input length
        """
        self.block_injections = block_injections
        self.block_non_grocery = block_non_grocery
        self.anonymize_pii = anonymize_pii
        self.max_input_length = max_input_length
        
        # Compile patterns for efficiency
        self._injection_regexes = [re.compile(p) for p in self.INJECTION_PATTERNS]
        self._non_grocery_regexes = [re.compile(p) for p in self.NON_GROCERY_PATTERNS]
        self._pii_regexes = {k: re.compile(v) for k, v in self.PII_PATTERNS.items()}
    
    def evaluate(self, text: str) -> GuardrailResult:
        """
        Evaluate input text against guardrails.
        
        Args:
            text: Input text to evaluate
            
        Returns:
            GuardrailResult with evaluation outcome
        """
        violations: List[GuardrailViolation] = []
        sanitized_text = text
        
        # Check for empty or None input
        if not text or not text.strip():
            violations.append(GuardrailViolation(
                violation_type=ViolationType.MALFORMED_INPUT,
                severity="HIGH",
                message="Empty or null input provided",
                action_taken=GuardrailAction.BLOCK,
            ))
            return GuardrailResult(
                is_allowed=False,
                violations=violations,
                original_input=text,
                sanitized_input=text,
            )
        
        # Check input length
        if len(text) > self.max_input_length:
            violations.append(GuardrailViolation(
                violation_type=ViolationType.MALFORMED_INPUT,
                severity="MEDIUM",
                message=f"Input exceeds maximum length of {self.max_input_length}",
                action_taken=GuardrailAction.BLOCK,
            ))
            return GuardrailResult(
                is_allowed=False,
                violations=violations,
                original_input=text,
                sanitized_input=text,
            )
        
        if len(text.strip()) < self.MIN_INPUT_LENGTH:
            violations.append(GuardrailViolation(
                violation_type=ViolationType.MALFORMED_INPUT,
                severity="MEDIUM",
                message=f"Input below minimum length of {self.MIN_INPUT_LENGTH}",
                action_taken=GuardrailAction.BLOCK,
            ))
            return GuardrailResult(
                is_allowed=False,
                violations=violations,
                original_input=text,
                sanitized_input=text,
            )
        
        # Check for injection attempts
        if self.block_injections:
            injection_violations = self._check_injections(text)
            if injection_violations:
                violations.extend(injection_violations)
                # Block on injection attempts
                return GuardrailResult(
                    is_allowed=False,
                    violations=violations,
                    original_input=text,
                    sanitized_input=text,
                )
        
        # Check for non-grocery content
        if self.block_non_grocery:
            non_grocery_violations = self._check_non_grocery(text)
            violations.extend(non_grocery_violations)
            # Log but don't block for non-grocery - let the model handle it
        
        # Anonymize PII
        if self.anonymize_pii:
            sanitized_text, pii_violations = self._anonymize_pii(text)
            violations.extend(pii_violations)
        
        # Determine if request should be allowed
        blocking_violations = [v for v in violations if v.action_taken == GuardrailAction.BLOCK]
        is_allowed = len(blocking_violations) == 0
        
        result = GuardrailResult(
            is_allowed=is_allowed,
            violations=violations,
            original_input=text,
            sanitized_input=sanitized_text,
        )
        
        if violations:
            logger.warning(
                "Guardrail violations detected",
                extra={"guardrail_result": result.to_dict()}
            )
        
        return result
    
    def _check_injections(self, text: str) -> List[GuardrailViolation]:
        """Check for prompt injection attempts."""
        violations = []
        
        for regex in self._injection_regexes:
            match = regex.search(text)
            if match:
                violations.append(GuardrailViolation(
                    violation_type=ViolationType.INJECTION_ATTEMPT,
                    severity="CRITICAL",
                    message="Potential prompt injection detected",
                    matched_content=match.group(),
                    action_taken=GuardrailAction.BLOCK,
                ))
                logger.error(
                    "Prompt injection attempt blocked",
                    extra={"pattern_matched": match.group()[:50]}
                )
        
        return violations
    
    def _check_non_grocery(self, text: str) -> List[GuardrailViolation]:
        """Check for non-grocery related content."""
        violations = []
        
        for regex in self._non_grocery_regexes:
            match = regex.search(text)
            if match:
                violations.append(GuardrailViolation(
                    violation_type=ViolationType.TOPIC_POLICY,
                    severity="LOW",
                    message="Non-grocery content detected",
                    matched_content=match.group(),
                    action_taken=GuardrailAction.LOG,  # Log but don't block
                ))
        
        return violations
    
    def _anonymize_pii(self, text: str) -> Tuple[str, List[GuardrailViolation]]:
        """Anonymize PII in text and return violations."""
        violations = []
        anonymized_text = text
        
        pii_replacements = {
            "credit_card": "[CREDIT_CARD]",
            "ssn": "[SSN]",
            "phone": "[PHONE]",
            "email": "[EMAIL]",
        }
        
        for pii_type, regex in self._pii_regexes.items():
            matches = list(regex.finditer(anonymized_text))
            if matches:
                for match in matches:
                    violations.append(GuardrailViolation(
                        violation_type=ViolationType.PII_DETECTED,
                        severity="MEDIUM",
                        message=f"PII detected: {pii_type}",
                        matched_content=match.group(),
                        action_taken=GuardrailAction.ANONYMIZE,
                    ))
                
                anonymized_text = regex.sub(pii_replacements[pii_type], anonymized_text)
        
        return anonymized_text, violations


class OutputGuardrails:
    """
    Guardrails for validating and sanitizing model outputs.
    
    Ensures AI responses are appropriate, properly formatted,
    and contain only expected content.
    """
    
    def __init__(
        self,
        validate_json: bool = True,
        check_confidence_threshold: float = 0.5,
        max_items: int = 100,
    ):
        """
        Initialize output guardrails.
        
        Args:
            validate_json: Validate JSON format of responses
            check_confidence_threshold: Minimum acceptable confidence
            max_items: Maximum number of items in response
        """
        self.validate_json = validate_json
        self.check_confidence_threshold = check_confidence_threshold
        self.max_items = max_items
    
    def evaluate(self, response: str, expected_format: str = "json") -> GuardrailResult:
        """
        Evaluate model response against output guardrails.
        
        Args:
            response: Model response text
            expected_format: Expected response format (json, text)
            
        Returns:
            GuardrailResult with evaluation outcome
        """
        violations: List[GuardrailViolation] = []
        
        if not response or not response.strip():
            violations.append(GuardrailViolation(
                violation_type=ViolationType.MALFORMED_INPUT,
                severity="HIGH",
                message="Empty response from model",
                action_taken=GuardrailAction.BLOCK,
            ))
            return GuardrailResult(
                is_allowed=False,
                violations=violations,
                original_input=response,
                sanitized_input=response,
            )
        
        if expected_format == "json" and self.validate_json:
            json_violations = self._validate_json_response(response)
            violations.extend(json_violations)
        
        # Check for blocking violations
        blocking_violations = [v for v in violations if v.action_taken == GuardrailAction.BLOCK]
        is_allowed = len(blocking_violations) == 0
        
        return GuardrailResult(
            is_allowed=is_allowed,
            violations=violations,
            original_input=response,
            sanitized_input=response,
        )
    
    def _validate_json_response(self, response: str) -> List[GuardrailViolation]:
        """Validate JSON format of response."""
        violations = []
        
        # Try to extract JSON from response
        json_text = self._extract_json(response)
        
        if not json_text:
            violations.append(GuardrailViolation(
                violation_type=ViolationType.MALFORMED_INPUT,
                severity="HIGH",
                message="No valid JSON found in response",
                action_taken=GuardrailAction.BLOCK,
            ))
            return violations
        
        try:
            parsed = json.loads(json_text)
            
            # Check if it has expected structure
            if isinstance(parsed, dict) and "items" in parsed:
                items = parsed.get("items", [])
                
                if len(items) > self.max_items:
                    violations.append(GuardrailViolation(
                        violation_type=ViolationType.MALFORMED_INPUT,
                        severity="MEDIUM",
                        message=f"Response contains too many items: {len(items)}",
                        action_taken=GuardrailAction.LOG,
                    ))
                
                # Check item structure
                for i, item in enumerate(items):
                    if not isinstance(item, dict):
                        violations.append(GuardrailViolation(
                            violation_type=ViolationType.MALFORMED_INPUT,
                            severity="MEDIUM",
                            message=f"Item {i} is not a valid object",
                            action_taken=GuardrailAction.LOG,
                        ))
                        continue
                    
                    # Check confidence scores
                    confidence = item.get("confidence", 0)
                    if confidence < self.check_confidence_threshold:
                        violations.append(GuardrailViolation(
                            violation_type=ViolationType.MALFORMED_INPUT,
                            severity="LOW",
                            message=f"Low confidence item: {item.get('name', 'unknown')} ({confidence})",
                            action_taken=GuardrailAction.LOG,
                        ))
        
        except json.JSONDecodeError as e:
            violations.append(GuardrailViolation(
                violation_type=ViolationType.MALFORMED_INPUT,
                severity="HIGH",
                message=f"Invalid JSON: {str(e)}",
                action_taken=GuardrailAction.BLOCK,
            ))
        
        return violations
    
    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON from text, handling markdown code blocks."""
        # Try to find JSON in code blocks first
        code_block_pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
        match = re.search(code_block_pattern, text)
        if match:
            return match.group(1)
        
        # Try to find raw JSON
        json_pattern = r"(\{[\s\S]*\})"
        match = re.search(json_pattern, text)
        if match:
            return match.group(1)
        
        return None


class BedrockGuardrailsManager:
    """
    Manager for coordinating input and output guardrails.
    
    Provides unified interface for guardrail evaluation and
    handles Bedrock-native guardrail responses.
    """
    
    def __init__(
        self,
        input_guardrails: Optional[InputGuardrails] = None,
        output_guardrails: Optional[OutputGuardrails] = None,
    ):
        """
        Initialize guardrails manager.
        
        Args:
            input_guardrails: Input guardrails instance
            output_guardrails: Output guardrails instance
        """
        self.input_guardrails = input_guardrails or InputGuardrails()
        self.output_guardrails = output_guardrails or OutputGuardrails()
    
    def evaluate_input(self, text: str) -> GuardrailResult:
        """Evaluate input text against guardrails."""
        return self.input_guardrails.evaluate(text)
    
    def evaluate_output(self, response: str, expected_format: str = "json") -> GuardrailResult:
        """Evaluate model output against guardrails."""
        return self.output_guardrails.evaluate(response, expected_format)
    
    def process_bedrock_guardrail_response(
        self,
        response: Dict[str, Any]
    ) -> Tuple[bool, List[GuardrailViolation]]:
        """
        Process guardrail response from Bedrock API.
        
        Args:
            response: Bedrock API response with guardrail data
            
        Returns:
            Tuple of (is_blocked, violations)
        """
        violations = []
        
        # Check for guardrail action
        guardrail_result = response.get("amazon-bedrock-guardrailAction")
        if guardrail_result == "BLOCKED":
            violations.append(GuardrailViolation(
                violation_type=ViolationType.CONTENT_FILTER,
                severity="HIGH",
                message="Request blocked by Bedrock Guardrails",
                action_taken=GuardrailAction.BLOCK,
            ))
            return True, violations
        
        # Check for content filter results
        trace = response.get("amazon-bedrock-trace", {})
        guardrail_trace = trace.get("guardrail", {})
        
        if guardrail_trace.get("inputAssessment"):
            input_assessment = guardrail_trace["inputAssessment"]
            
            # Check content policy
            for filter_result in input_assessment.get("contentPolicy", {}).get("filters", []):
                if filter_result.get("action") == "BLOCKED":
                    violations.append(GuardrailViolation(
                        violation_type=ViolationType.CONTENT_FILTER,
                        severity="HIGH",
                        message=f"Content blocked: {filter_result.get('type')}",
                        action_taken=GuardrailAction.BLOCK,
                    ))
            
            # Check topic policy
            for topic in input_assessment.get("topicPolicy", {}).get("topics", []):
                if topic.get("action") == "BLOCKED":
                    violations.append(GuardrailViolation(
                        violation_type=ViolationType.TOPIC_POLICY,
                        severity="MEDIUM",
                        message=f"Topic blocked: {topic.get('name')}",
                        action_taken=GuardrailAction.BLOCK,
                    ))
        
        is_blocked = any(v.action_taken == GuardrailAction.BLOCK for v in violations)
        return is_blocked, violations
