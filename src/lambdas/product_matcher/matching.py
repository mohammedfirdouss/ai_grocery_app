"""
Product matching algorithms for AI Grocery App.

This module implements various product matching strategies including:
- Exact name matching
- Fuzzy string matching with Levenshtein distance
- Category-based matching with ML embeddings
- Fallback handling for unmatched items
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal
import json
import boto3
from aws_lambda_powertools import Logger

logger = Logger(child=True)


@dataclass
class MatchResult:
    """Result of a product matching operation."""
    product: Dict[str, Any]
    confidence: float
    match_type: str
    similarity_score: float = 0.0


class LevenshteinMatcher:
    """Fuzzy string matching using Levenshtein distance algorithm."""
    
    def __init__(self, threshold: float = 0.75):
        """
        Initialize Levenshtein matcher.
        
        Args:
            threshold: Minimum similarity score (0-1) to consider a match
        """
        self.threshold = threshold
    
    @staticmethod
    def levenshtein_distance(s1: str, s2: str) -> int:
        """
        Calculate Levenshtein distance between two strings.
        
        Args:
            s1: First string
            s2: Second string
            
        Returns:
            Levenshtein distance (number of edits needed)
        """
        if len(s1) < len(s2):
            return LevenshteinMatcher.levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                # Cost of insertions, deletions, or substitutions
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def similarity_score(self, s1: str, s2: str) -> float:
        """
        Calculate similarity score between two strings (0-1).
        
        Args:
            s1: First string
            s2: Second string
            
        Returns:
            Similarity score (1.0 = identical, 0.0 = completely different)
        """
        s1_lower = s1.lower().strip()
        s2_lower = s2.lower().strip()
        
        if s1_lower == s2_lower:
            return 1.0
        
        distance = self.levenshtein_distance(s1_lower, s2_lower)
        max_len = max(len(s1_lower), len(s2_lower))
        
        if max_len == 0:
            return 1.0
        
        return 1.0 - (distance / max_len)
    
    def find_best_match(
        self,
        query: str,
        products: List[Dict[str, Any]],
        name_field: str = "name"
    ) -> Optional[MatchResult]:
        """
        Find best matching product using Levenshtein distance.
        
        Args:
            query: Query string to match
            products: List of product dictionaries
            name_field: Field name containing product name
            
        Returns:
            MatchResult if match found above threshold, None otherwise
        """
        best_match = None
        best_score = 0.0
        
        for product in products:
            product_name = product.get(name_field, "")
            score = self.similarity_score(query, product_name)
            
            if score > best_score and score >= self.threshold:
                best_score = score
                best_match = product
        
        if best_match:
            logger.debug(
                "Levenshtein match found",
                extra={
                    "query": query,
                    "match": best_match.get(name_field),
                    "score": best_score
                }
            )
            return MatchResult(
                product=best_match,
                confidence=best_score,
                match_type="fuzzy_levenshtein",
                similarity_score=best_score
            )
        
        return None


class CategoryMatcher:
    """Category-based matching with ML embeddings support."""
    
    def __init__(self, bedrock_client=None, embedding_model: str = "amazon.titan-embed-text-v1"):
        """
        Initialize category matcher.
        
        Args:
            bedrock_client: Optional Bedrock client for embeddings
            embedding_model: Model ID for generating embeddings
        """
        self.bedrock_client = bedrock_client
        self.embedding_model = embedding_model
        self._embedding_cache = {}
    
    def get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Get ML embedding for text using Amazon Bedrock.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector or None if unavailable
        """
        if not self.bedrock_client:
            logger.warning("Bedrock client not available for embeddings")
            return None
        
        # Check cache
        if text in self._embedding_cache:
            return self._embedding_cache[text]
        
        try:
            response = self.bedrock_client.invoke_model(
                modelId=self.embedding_model,
                body=json.dumps({"inputText": text})
            )
            
            result = json.loads(response['body'].read())
            embedding = result.get('embedding', [])
            
            # Cache the result
            self._embedding_cache[text] = embedding
            return embedding
            
        except Exception as e:
            logger.warning(
                "Failed to get embedding",
                extra={"text": text, "error": str(e)}
            )
            return None
    
    @staticmethod
    def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector
            vec2: Second vector
            
        Returns:
            Cosine similarity score (0-1)
        """
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        
        return dot_product / (magnitude1 * magnitude2)
    
    def find_by_category(
        self,
        item_category: str,
        products: List[Dict[str, Any]],
        category_field: str = "category"
    ) -> List[Dict[str, Any]]:
        """
        Find products matching a category.
        
        Args:
            item_category: Category to match
            products: List of product dictionaries
            category_field: Field name containing product category
            
        Returns:
            List of matching products
        """
        matching_products = []
        
        for product in products:
            product_category = product.get(category_field, "").lower()
            if item_category.lower() == product_category:
                matching_products.append(product)
        
        return matching_products
    
    def find_by_embedding(
        self,
        query: str,
        products: List[Dict[str, Any]],
        threshold: float = 0.8,
        name_field: str = "name"
    ) -> Optional[MatchResult]:
        """
        Find best matching product using ML embeddings.
        
        Args:
            query: Query string to match
            products: List of product dictionaries
            threshold: Minimum similarity threshold
            name_field: Field name containing product name
            
        Returns:
            MatchResult if match found, None otherwise
        """
        query_embedding = self.get_embedding(query)
        if not query_embedding:
            logger.debug("Cannot use embedding matching - embeddings unavailable")
            return None
        
        best_match = None
        best_score = 0.0
        
        for product in products:
            product_name = product.get(name_field, "")
            product_embedding = self.get_embedding(product_name)
            
            if not product_embedding:
                continue
            
            score = self.cosine_similarity(query_embedding, product_embedding)
            
            if score > best_score and score >= threshold:
                best_score = score
                best_match = product
        
        if best_match:
            logger.debug(
                "Embedding match found",
                extra={
                    "query": query,
                    "match": best_match.get(name_field),
                    "score": best_score
                }
            )
            return MatchResult(
                product=best_match,
                confidence=best_score,
                match_type="category_embedding",
                similarity_score=best_score
            )
        
        return None


class ProductMatcher:
    """
    Comprehensive product matcher with multiple strategies.
    
    Implements a waterfall matching approach:
    1. Exact name match
    2. Fuzzy match with Levenshtein distance
    3. Category-based match with ML embeddings
    4. Fallback handling for unmatched items
    """
    
    def __init__(
        self,
        levenshtein_threshold: float = 0.75,
        embedding_threshold: float = 0.8,
        bedrock_client=None
    ):
        """
        Initialize product matcher.
        
        Args:
            levenshtein_threshold: Threshold for Levenshtein matching
            embedding_threshold: Threshold for embedding matching
            bedrock_client: Optional Bedrock client for embeddings
        """
        self.levenshtein_matcher = LevenshteinMatcher(threshold=levenshtein_threshold)
        self.category_matcher = CategoryMatcher(bedrock_client=bedrock_client)
        self.embedding_threshold = embedding_threshold
    
    def match_product(
        self,
        item_name: str,
        products: List[Dict[str, Any]],
        category: Optional[str] = None,
        name_field: str = "name"
    ) -> Optional[MatchResult]:
        """
        Match an item against product catalog using multiple strategies.
        
        Args:
            item_name: Name of item to match
            products: List of available products
            category: Optional category hint
            name_field: Field name for product name
            
        Returns:
            MatchResult if match found, None otherwise
        """
        if not products:
            return None
        
        item_name_lower = item_name.lower().strip()
        
        # Strategy 1: Exact match
        for product in products:
            product_name = product.get(name_field, "").lower().strip()
            if item_name_lower == product_name:
                logger.debug(
                    "Exact match found",
                    extra={"item": item_name, "product": product.get(name_field)}
                )
                return MatchResult(
                    product=product,
                    confidence=1.0,
                    match_type="exact",
                    similarity_score=1.0
                )
        
        # Strategy 2: Fuzzy match with Levenshtein distance
        levenshtein_result = self.levenshtein_matcher.find_best_match(
            item_name,
            products,
            name_field
        )
        if levenshtein_result:
            return levenshtein_result
        
        # Strategy 3: Category-based matching
        if category:
            category_products = self.category_matcher.find_by_category(
                category,
                products
            )
            
            if category_products:
                # Try Levenshtein within category
                category_result = self.levenshtein_matcher.find_best_match(
                    item_name,
                    category_products,
                    name_field
                )
                if category_result:
                    category_result.match_type = "category_levenshtein"
                    return category_result
        
        # Strategy 4: ML embedding-based matching
        embedding_result = self.category_matcher.find_by_embedding(
            item_name,
            products,
            threshold=self.embedding_threshold,
            name_field=name_field
        )
        if embedding_result:
            return embedding_result
        
        # No match found
        logger.warning(
            "No product match found",
            extra={"item": item_name, "strategies_tried": 4}
        )
        return None
    
    def find_alternatives(
        self,
        item_name: str,
        products: List[Dict[str, Any]],
        category: Optional[str] = None,
        max_alternatives: int = 3,
        name_field: str = "name"
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Find alternative products for an item.
        
        Args:
            item_name: Name of item
            products: List of available products
            category: Optional category hint
            max_alternatives: Maximum number of alternatives
            name_field: Field name for product name
            
        Returns:
            List of (product, score) tuples
        """
        alternatives = []
        
        # Filter by category if provided
        search_products = products
        if category:
            search_products = self.category_matcher.find_by_category(
                category,
                products
            )
            # Fallback to all products if no category matches
            if not search_products:
                search_products = products
        
        # Calculate similarity scores for all products
        for product in search_products:
            product_name = product.get(name_field, "")
            score = self.levenshtein_matcher.similarity_score(item_name, product_name)
            alternatives.append((product, score))
        
        # Sort by score and take top N
        alternatives.sort(key=lambda x: x[1], reverse=True)
        return alternatives[:max_alternatives]
