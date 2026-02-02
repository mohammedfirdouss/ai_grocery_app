"""
Structured Data Extraction Module for Bedrock Responses.

This module provides utilities for extracting structured data from AI responses,
including confidence scoring, uncertainty logging, and data validation.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Union
from enum import Enum
from decimal import Decimal
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger(child=True)
metrics = Metrics()


class ConfidenceLevel(str, Enum):
    """Confidence level categories."""
    HIGH = "high"       # >= 0.85
    MEDIUM = "medium"   # >= 0.7
    LOW = "low"         # >= 0.5
    VERY_LOW = "very_low"  # < 0.5


class UncertaintyReason(str, Enum):
    """Reasons for uncertainty in extraction."""
    AMBIGUOUS_QUANTITY = "ambiguous_quantity"
    AMBIGUOUS_ITEM = "ambiguous_item"
    UNCLEAR_UNIT = "unclear_unit"
    MULTIPLE_INTERPRETATIONS = "multiple_interpretations"
    INCOMPLETE_INFORMATION = "incomplete_information"
    NON_STANDARD_FORMAT = "non_standard_format"
    POSSIBLE_MISSPELLING = "possible_misspelling"
    CONTEXT_MISSING = "context_missing"


@dataclass
class ExtractedGroceryItem:
    """Structured representation of an extracted grocery item."""
    
    name: str
    quantity: float
    unit: str
    specifications: List[str] = field(default_factory=list)
    confidence: float = 0.0
    original_text: str = ""
    
    # Derived/calculated fields
    confidence_level: ConfidenceLevel = ConfidenceLevel.MEDIUM
    uncertainty_reasons: List[UncertaintyReason] = field(default_factory=list)
    
    def __post_init__(self):
        """Calculate derived fields after initialization."""
        self.confidence_level = self._calculate_confidence_level()
    
    def _calculate_confidence_level(self) -> ConfidenceLevel:
        """Calculate confidence level from score."""
        if self.confidence >= 0.85:
            return ConfidenceLevel.HIGH
        elif self.confidence >= 0.7:
            return ConfidenceLevel.MEDIUM
        elif self.confidence >= 0.5:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.VERY_LOW
    
    @property
    def is_uncertain(self) -> bool:
        """Check if item has uncertainty."""
        return self.confidence < 0.7 or len(self.uncertainty_reasons) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "quantity": self.quantity,
            "unit": self.unit,
            "specifications": self.specifications,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level.value,
            "original_text": self.original_text,
            "uncertainty_reasons": [r.value for r in self.uncertainty_reasons],
            "is_uncertain": self.is_uncertain,
        }


@dataclass
class ExtractionResult:
    """Result of grocery item extraction."""
    
    items: List[ExtractedGroceryItem]
    unrecognized_text: List[str] = field(default_factory=list)
    parsing_notes: str = ""
    raw_response: str = ""
    
    # Statistics
    total_items: int = 0
    high_confidence_count: int = 0
    low_confidence_count: int = 0
    average_confidence: float = 0.0
    
    def __post_init__(self):
        """Calculate statistics after initialization."""
        self._calculate_statistics()
    
    def _calculate_statistics(self):
        """Calculate extraction statistics."""
        self.total_items = len(self.items)
        
        if not self.items:
            return
        
        self.high_confidence_count = sum(
            1 for item in self.items
            if item.confidence_level in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)
        )
        self.low_confidence_count = sum(
            1 for item in self.items
            if item.confidence_level in (ConfidenceLevel.LOW, ConfidenceLevel.VERY_LOW)
        )
        self.average_confidence = sum(
            item.confidence for item in self.items
        ) / len(self.items)
    
    @property
    def uncertain_items(self) -> List[ExtractedGroceryItem]:
        """Get items with uncertainty."""
        return [item for item in self.items if item.is_uncertain]
    
    @property
    def has_uncertain_items(self) -> bool:
        """Check if any items have uncertainty."""
        return len(self.uncertain_items) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "items": [item.to_dict() for item in self.items],
            "unrecognized_text": self.unrecognized_text,
            "parsing_notes": self.parsing_notes,
            "statistics": {
                "total_items": self.total_items,
                "high_confidence_count": self.high_confidence_count,
                "low_confidence_count": self.low_confidence_count,
                "average_confidence": round(self.average_confidence, 3),
                "uncertain_items_count": len(self.uncertain_items),
            },
        }


class GroceryItemExtractor:
    """
    Extractor for structured grocery items from AI responses.
    
    Features:
    - JSON extraction from various response formats
    - Confidence scoring and validation
    - Uncertainty detection and logging
    - Data normalization
    """
    
    # Default values for missing fields
    DEFAULT_QUANTITY = 1.0
    DEFAULT_UNIT = "piece"
    DEFAULT_CONFIDENCE = 0.75
    
    # Unit normalization mapping
    UNIT_NORMALIZATION = {
        # Weight
        "kg": "kg", "kilogram": "kg", "kilograms": "kg", "kilo": "kg",
        "g": "g", "gram": "g", "grams": "g",
        "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
        "oz": "oz", "ounce": "oz", "ounces": "oz",
        # Volume
        "l": "liter", "liter": "liter", "liters": "liter", "litre": "liter",
        "ml": "ml", "milliliter": "ml", "milliliters": "ml",
        "gal": "gallon", "gallon": "gallon", "gallons": "gallon",
        # Count
        "pc": "piece", "pcs": "piece", "piece": "piece", "pieces": "piece",
        "unit": "piece", "units": "piece", "each": "piece",
        "dozen": "dozen", "doz": "dozen",
        "pack": "pack", "packs": "pack", "package": "pack", "packages": "pack",
        "bunch": "bunch", "bunches": "bunch",
        "bag": "bag", "bags": "bag",
        "bottle": "bottle", "bottles": "bottle",
        "can": "can", "cans": "can",
        "box": "box", "boxes": "box",
        "loaf": "loaf", "loaves": "loaf",
        "carton": "carton", "cartons": "carton",
    }
    
    def __init__(
        self,
        uncertainty_threshold: float = 0.7,
        log_uncertain_items: bool = True,
        emit_metrics: bool = True,
    ):
        """
        Initialize extractor.
        
        Args:
            uncertainty_threshold: Confidence threshold below which items are logged
            log_uncertain_items: Whether to log uncertain items
            emit_metrics: Whether to emit CloudWatch metrics
        """
        self.uncertainty_threshold = uncertainty_threshold
        self.log_uncertain_items = log_uncertain_items
        self.emit_metrics = emit_metrics
    
    def extract(self, response_text: str) -> ExtractionResult:
        """
        Extract structured grocery items from AI response.
        
        Args:
            response_text: Raw text response from Bedrock
            
        Returns:
            ExtractionResult with extracted items
        """
        # Extract JSON from response
        json_data = self._extract_json(response_text)
        
        if not json_data:
            logger.error("Failed to extract JSON from response")
            return ExtractionResult(
                items=[],
                unrecognized_text=[response_text],
                parsing_notes="Failed to parse response as JSON",
                raw_response=response_text,
            )
        
        # Parse items
        items = self._parse_items(json_data)
        
        # Analyze and score items
        for item in items:
            self._analyze_item_confidence(item)
        
        # Log uncertain items
        if self.log_uncertain_items:
            self._log_uncertain_items(items)
        
        # Emit metrics
        if self.emit_metrics:
            self._emit_extraction_metrics(items)
        
        return ExtractionResult(
            items=items,
            unrecognized_text=json_data.get("unrecognized_text", []),
            parsing_notes=json_data.get("parsing_notes", ""),
            raw_response=response_text,
        )
    
    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from text, handling various formats."""
        # Try to find JSON in code blocks first
        patterns = [
            r"```json\s*([\s\S]*?)\s*```",
            r"```\s*([\s\S]*?)\s*```",
            r"(\{[\s\S]*\})",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    json_str = match.group(1).strip()
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue
        
        # Try parsing the entire text as JSON
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        
        return None
    
    def _parse_items(self, json_data: Dict[str, Any]) -> List[ExtractedGroceryItem]:
        """Parse items from JSON data."""
        items = []
        raw_items = json_data.get("items", [])
        
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                logger.warning(f"Invalid item format: {raw_item}")
                continue
            
            try:
                item = self._parse_single_item(raw_item)
                items.append(item)
            except Exception as e:
                logger.error(f"Failed to parse item: {raw_item}", extra={"error": str(e)})
        
        return items
    
    def _parse_single_item(self, raw_item: Dict[str, Any]) -> ExtractedGroceryItem:
        """Parse a single item from raw data."""
        # Extract fields with defaults
        name = str(raw_item.get("name", "")).strip()
        if not name:
            raise ValueError("Item name is required")
        
        # Parse quantity
        quantity = self._parse_quantity(raw_item.get("quantity", self.DEFAULT_QUANTITY))
        
        # Normalize unit
        raw_unit = str(raw_item.get("unit", self.DEFAULT_UNIT)).lower().strip()
        unit = self.UNIT_NORMALIZATION.get(raw_unit, raw_unit)
        
        # Parse specifications
        specs = raw_item.get("specifications", [])
        if isinstance(specs, str):
            specs = [specs] if specs else []
        specifications = [str(s).strip() for s in specs if s]
        
        # Parse confidence
        confidence = self._parse_confidence(raw_item.get("confidence", self.DEFAULT_CONFIDENCE))
        
        # Original text
        original_text = str(raw_item.get("original_text", raw_item.get("raw_text_segment", "")))
        
        return ExtractedGroceryItem(
            name=name,
            quantity=quantity,
            unit=unit,
            specifications=specifications,
            confidence=confidence,
            original_text=original_text,
        )
    
    def _parse_quantity(self, value: Any) -> float:
        """Parse quantity from various formats."""
        if isinstance(value, (int, float)):
            return float(value)
        
        if isinstance(value, str):
            # Handle fractional notation
            if "/" in value:
                parts = value.split("/")
                if len(parts) == 2:
                    try:
                        return float(parts[0]) / float(parts[1])
                    except (ValueError, ZeroDivisionError):
                        pass
            
            # Handle mixed numbers (e.g., "1 1/2")
            match = re.match(r"(\d+)\s+(\d+)/(\d+)", value)
            if match:
                whole = int(match.group(1))
                num = int(match.group(2))
                denom = int(match.group(3))
                return whole + num / denom
            
            # Try direct conversion
            try:
                return float(value.strip())
            except ValueError:
                pass
        
        return self.DEFAULT_QUANTITY
    
    def _parse_confidence(self, value: Any) -> float:
        """Parse confidence score from various formats."""
        if isinstance(value, (int, float)):
            confidence = float(value)
        elif isinstance(value, str):
            try:
                confidence = float(value.strip())
            except ValueError:
                confidence = self.DEFAULT_CONFIDENCE
        else:
            confidence = self.DEFAULT_CONFIDENCE
        
        # Ensure it's in valid range
        return max(0.0, min(1.0, confidence))
    
    def _analyze_item_confidence(self, item: ExtractedGroceryItem) -> None:
        """Analyze item and identify reasons for uncertainty."""
        reasons = []
        
        # Check for default quantity
        if item.quantity == self.DEFAULT_QUANTITY and not item.original_text:
            reasons.append(UncertaintyReason.AMBIGUOUS_QUANTITY)
        
        # Check for generic unit
        if item.unit in ("piece", "unit"):
            # If the name suggests a bulk item
            bulk_keywords = ["rice", "flour", "sugar", "salt", "beans", "pasta"]
            if any(kw in item.name.lower() for kw in bulk_keywords):
                reasons.append(UncertaintyReason.UNCLEAR_UNIT)
        
        # Check for ambiguous names
        ambiguous_names = ["thing", "stuff", "item", "food", "something"]
        if any(name in item.name.lower() for name in ambiguous_names):
            reasons.append(UncertaintyReason.AMBIGUOUS_ITEM)
        
        # Check for very short names (might be incomplete)
        if len(item.name) < 3:
            reasons.append(UncertaintyReason.INCOMPLETE_INFORMATION)
        
        # Lower confidence if reasons identified
        if reasons and item.confidence >= 0.7:
            item.confidence = max(0.5, item.confidence - 0.1 * len(reasons))
            item.confidence_level = item._calculate_confidence_level()
        
        item.uncertainty_reasons = reasons
    
    def _log_uncertain_items(self, items: List[ExtractedGroceryItem]) -> None:
        """Log items with uncertainty for monitoring."""
        uncertain_items = [
            item for item in items
            if item.confidence < self.uncertainty_threshold
        ]
        
        if not uncertain_items:
            return
        
        logger.warning(
            f"Found {len(uncertain_items)} items with low confidence",
            extra={
                "uncertain_items": [
                    {
                        "name": item.name,
                        "confidence": item.confidence,
                        "reasons": [r.value for r in item.uncertainty_reasons],
                        "original_text": item.original_text[:100],
                    }
                    for item in uncertain_items
                ],
                "threshold": self.uncertainty_threshold,
            }
        )
    
    def _emit_extraction_metrics(self, items: List[ExtractedGroceryItem]) -> None:
        """Emit extraction metrics to CloudWatch."""
        metrics.add_metric(
            name="ExtractedItemsCount",
            unit=MetricUnit.Count,
            value=len(items)
        )
        
        if items:
            avg_confidence = sum(item.confidence for item in items) / len(items)
            metrics.add_metric(
                name="AverageExtractionConfidence",
                unit=MetricUnit.Count,
                value=int(avg_confidence * 100)
            )
        
        low_confidence_count = sum(
            1 for item in items
            if item.confidence < self.uncertainty_threshold
        )
        metrics.add_metric(
            name="LowConfidenceItemsCount",
            unit=MetricUnit.Count,
            value=low_confidence_count
        )


class ConfidenceScorer:
    """
    Calculates and manages confidence scores for extractions.
    
    Provides multi-factor confidence scoring based on:
    - Model's reported confidence
    - Extraction quality indicators
    - Contextual validation
    """
    
    # Weights for different confidence factors
    MODEL_CONFIDENCE_WEIGHT = 0.5
    COMPLETENESS_WEIGHT = 0.2
    SPECIFICITY_WEIGHT = 0.15
    CONSISTENCY_WEIGHT = 0.15
    
    def __init__(self, base_threshold: float = 0.7):
        """
        Initialize confidence scorer.
        
        Args:
            base_threshold: Base confidence threshold
        """
        self.base_threshold = base_threshold
    
    def calculate_item_confidence(
        self,
        item: ExtractedGroceryItem,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Calculate comprehensive confidence score for an item.
        
        Args:
            item: Extracted grocery item
            context: Optional context for validation
            
        Returns:
            Confidence score between 0 and 1
        """
        # Start with model's confidence
        model_confidence = item.confidence
        
        # Calculate completeness score
        completeness = self._calculate_completeness(item)
        
        # Calculate specificity score
        specificity = self._calculate_specificity(item)
        
        # Calculate consistency score
        consistency = self._calculate_consistency(item, context)
        
        # Weighted combination
        final_confidence = (
            self.MODEL_CONFIDENCE_WEIGHT * model_confidence +
            self.COMPLETENESS_WEIGHT * completeness +
            self.SPECIFICITY_WEIGHT * specificity +
            self.CONSISTENCY_WEIGHT * consistency
        )
        
        return round(final_confidence, 3)
    
    def _calculate_completeness(self, item: ExtractedGroceryItem) -> float:
        """Calculate completeness score based on field presence."""
        score = 0.0
        
        # Name present and valid
        if item.name and len(item.name) >= 2:
            score += 0.4
        
        # Quantity specified (not default)
        if item.quantity != 1.0 or item.original_text:
            score += 0.2
        
        # Unit specified (not default)
        if item.unit and item.unit != "piece":
            score += 0.2
        
        # Has specifications
        if item.specifications:
            score += 0.1
        
        # Has original text
        if item.original_text:
            score += 0.1
        
        return min(1.0, score)
    
    def _calculate_specificity(self, item: ExtractedGroceryItem) -> float:
        """Calculate specificity score based on detail level."""
        score = 0.5  # Base score
        
        # More specific names get higher scores
        name_words = item.name.split()
        if len(name_words) > 1:
            score += 0.1
        if len(name_words) > 2:
            score += 0.1
        
        # Having specifications increases specificity
        if item.specifications:
            score += 0.1 * min(len(item.specifications), 3)
        
        return min(1.0, score)
    
    def _calculate_consistency(
        self,
        item: ExtractedGroceryItem,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Calculate consistency score based on internal coherence."""
        score = 0.7  # Base consistency
        
        # Check quantity-unit consistency
        quantity = item.quantity
        unit = item.unit.lower()
        
        # Large quantities with "piece" might be suspicious
        if quantity > 100 and unit == "piece":
            score -= 0.2
        
        # Very small quantities with weight units
        if quantity < 0.01 and unit in ("kg", "lb"):
            score -= 0.2
        
        # Context-based validation (if available)
        if context:
            expected_category = context.get("expected_category")
            if expected_category:
                # Would need category matching logic here
                pass
        
        return max(0.0, min(1.0, score))
    
    def calculate_batch_confidence(
        self,
        items: List[ExtractedGroceryItem],
    ) -> Dict[str, Any]:
        """
        Calculate aggregate confidence statistics for a batch of items.
        
        Args:
            items: List of extracted items
            
        Returns:
            Dict with confidence statistics
        """
        if not items:
            return {
                "average_confidence": 0.0,
                "min_confidence": 0.0,
                "max_confidence": 0.0,
                "confidence_distribution": {},
                "low_confidence_items": [],
            }
        
        confidences = [item.confidence for item in items]
        
        # Calculate distribution
        distribution = {
            ConfidenceLevel.HIGH.value: 0,
            ConfidenceLevel.MEDIUM.value: 0,
            ConfidenceLevel.LOW.value: 0,
            ConfidenceLevel.VERY_LOW.value: 0,
        }
        
        for item in items:
            distribution[item.confidence_level.value] += 1
        
        # Find low confidence items
        low_confidence = [
            {
                "name": item.name,
                "confidence": item.confidence,
                "reasons": [r.value for r in item.uncertainty_reasons],
            }
            for item in items
            if item.confidence < self.base_threshold
        ]
        
        return {
            "average_confidence": round(sum(confidences) / len(confidences), 3),
            "min_confidence": round(min(confidences), 3),
            "max_confidence": round(max(confidences), 3),
            "confidence_distribution": distribution,
            "low_confidence_items": low_confidence,
            "total_items": len(items),
            "items_below_threshold": len(low_confidence),
        }


def extract_and_validate(
    response_text: str,
    uncertainty_threshold: float = 0.7,
) -> Tuple[ExtractionResult, Dict[str, Any]]:
    """
    Convenience function to extract items and calculate confidence statistics.
    
    Args:
        response_text: Raw AI response text
        uncertainty_threshold: Threshold for uncertainty flagging
        
    Returns:
        Tuple of (ExtractionResult, confidence_statistics)
    """
    extractor = GroceryItemExtractor(
        uncertainty_threshold=uncertainty_threshold,
        log_uncertain_items=True,
        emit_metrics=True,
    )
    
    result = extractor.extract(response_text)
    
    scorer = ConfidenceScorer(base_threshold=uncertainty_threshold)
    stats = scorer.calculate_batch_confidence(result.items)
    
    return result, stats
