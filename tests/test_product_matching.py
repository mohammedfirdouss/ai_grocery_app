"""
Tests for product matching algorithms.

Tests Levenshtein distance matching, category-based matching,
and ML embedding integration.
"""

import pytest
from decimal import Decimal
from src.lambdas.product_matcher.matching import (
    LevenshteinMatcher,
    CategoryMatcher,
    ProductMatcher,
    MatchResult,
)


class TestLevenshteinMatcher:
    """Tests for Levenshtein distance matching."""
    
    def test_exact_match(self):
        """Test exact string matching."""
        matcher = LevenshteinMatcher(threshold=0.75)
        score = matcher.similarity_score("apple", "apple")
        assert score == 1.0
    
    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        matcher = LevenshteinMatcher(threshold=0.75)
        score = matcher.similarity_score("APPLE", "apple")
        assert score == 1.0
    
    def test_close_match(self):
        """Test close string matching."""
        matcher = LevenshteinMatcher(threshold=0.75)
        score = matcher.similarity_score("tomato", "tomatos")
        assert score > 0.75
    
    def test_distant_match(self):
        """Test distant string matching."""
        matcher = LevenshteinMatcher(threshold=0.75)
        score = matcher.similarity_score("apple", "orange")
        assert score < 0.5
    
    def test_levenshtein_distance_calculation(self):
        """Test Levenshtein distance calculation."""
        assert LevenshteinMatcher.levenshtein_distance("kitten", "sitting") == 3
        assert LevenshteinMatcher.levenshtein_distance("", "hello") == 5
        assert LevenshteinMatcher.levenshtein_distance("same", "same") == 0
    
    def test_find_best_match(self):
        """Test finding best match from product list."""
        matcher = LevenshteinMatcher(threshold=0.75)
        products = [
            {"product_id": "1", "name": "red apple"},
            {"product_id": "2", "name": "green apple"},
            {"product_id": "3", "name": "orange"},
        ]
        
        result = matcher.find_best_match("aple", products)
        assert result is not None
        assert "apple" in result.product["name"]
        assert result.match_type == "fuzzy_levenshtein"
        assert result.confidence > 0.75
    
    def test_no_match_below_threshold(self):
        """Test no match when below threshold."""
        matcher = LevenshteinMatcher(threshold=0.9)
        products = [
            {"product_id": "1", "name": "apple"},
            {"product_id": "2", "name": "banana"},
        ]
        
        result = matcher.find_best_match("xyz", products)
        assert result is None


class TestCategoryMatcher:
    """Tests for category-based matching."""
    
    def test_find_by_category_exact(self):
        """Test finding products by exact category."""
        matcher = CategoryMatcher()
        products = [
            {"product_id": "1", "name": "apple", "category": "fruits"},
            {"product_id": "2", "name": "banana", "category": "fruits"},
            {"product_id": "3", "name": "carrot", "category": "vegetables"},
        ]
        
        results = matcher.find_by_category("fruits", products)
        assert len(results) == 2
        assert all(p["category"] == "fruits" for p in results)
    
    def test_find_by_category_case_insensitive(self):
        """Test case-insensitive category matching."""
        matcher = CategoryMatcher()
        products = [
            {"product_id": "1", "name": "apple", "category": "Fruits"},
            {"product_id": "2", "name": "banana", "category": "FRUITS"},
        ]
        
        results = matcher.find_by_category("fruits", products)
        assert len(results) == 2
    
    def test_cosine_similarity(self):
        """Test cosine similarity calculation."""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [1.0, 2.0, 3.0]
        similarity = CategoryMatcher.cosine_similarity(vec1, vec2)
        assert similarity == pytest.approx(1.0)
        
        vec3 = [1.0, 0.0, 0.0]
        vec4 = [0.0, 1.0, 0.0]
        similarity = CategoryMatcher.cosine_similarity(vec3, vec4)
        assert similarity == pytest.approx(0.0)
    
    def test_cosine_similarity_edge_cases(self):
        """Test cosine similarity edge cases."""
        # Empty vectors
        assert CategoryMatcher.cosine_similarity([], []) == 0.0
        
        # Zero vectors
        assert CategoryMatcher.cosine_similarity([0, 0, 0], [0, 0, 0]) == 0.0
        
        # Different length vectors
        assert CategoryMatcher.cosine_similarity([1, 2], [1, 2, 3]) == 0.0


class TestProductMatcher:
    """Tests for comprehensive product matching."""
    
    @pytest.fixture
    def sample_products(self):
        """Sample product catalog."""
        return [
            {
                "product_id": "1",
                "name": "red apple",
                "category": "fruits",
                "unit_price": 5.0,
            },
            {
                "product_id": "2",
                "name": "green apple",
                "category": "fruits",
                "unit_price": 4.5,
            },
            {
                "product_id": "3",
                "name": "banana",
                "category": "fruits",
                "unit_price": 3.0,
            },
            {
                "product_id": "4",
                "name": "carrot",
                "category": "vegetables",
                "unit_price": 2.0,
            },
        ]
    
    def test_exact_match(self, sample_products):
        """Test exact product matching."""
        matcher = ProductMatcher()
        result = matcher.match_product("red apple", sample_products)
        
        assert result is not None
        assert result.product["product_id"] == "1"
        assert result.match_type == "exact"
        assert result.confidence == 1.0
    
    def test_fuzzy_match(self, sample_products):
        """Test fuzzy product matching."""
        matcher = ProductMatcher(levenshtein_threshold=0.7)
        result = matcher.match_product("aple", sample_products)
        
        assert result is not None
        assert "apple" in result.product["name"]
        assert result.match_type == "fuzzy_levenshtein"
        assert result.confidence > 0.7
    
    def test_category_match(self, sample_products):
        """Test category-based matching."""
        matcher = ProductMatcher(levenshtein_threshold=0.7)
        result = matcher.match_product(
            "aple",
            sample_products,
            category="fruits"
        )
        
        assert result is not None
        assert result.product["category"] == "fruits"
    
    def test_no_match(self, sample_products):
        """Test no match scenario."""
        matcher = ProductMatcher(levenshtein_threshold=0.9)
        result = matcher.match_product("xyz123", sample_products)
        
        assert result is None
    
    def test_find_alternatives(self, sample_products):
        """Test finding alternative products."""
        matcher = ProductMatcher()
        alternatives = matcher.find_alternatives(
            "aple",
            sample_products,
            max_alternatives=2
        )
        
        assert len(alternatives) <= 2
        assert all(isinstance(alt, tuple) for alt in alternatives)
        assert all(len(alt) == 2 for alt in alternatives)
        # Alternatives should be sorted by score
        if len(alternatives) > 1:
            assert alternatives[0][1] >= alternatives[1][1]
    
    def test_find_alternatives_by_category(self, sample_products):
        """Test finding alternatives within category."""
        matcher = ProductMatcher()
        alternatives = matcher.find_alternatives(
            "aple",
            sample_products,
            category="fruits",
            max_alternatives=3
        )
        
        assert len(alternatives) <= 3
        # All should be from fruits category
        for product, score in alternatives:
            assert product["category"] == "fruits"
    
    def test_case_insensitive_matching(self, sample_products):
        """Test case-insensitive product matching."""
        matcher = ProductMatcher()
        result = matcher.match_product("RED APPLE", sample_products)
        
        assert result is not None
        assert result.product["product_id"] == "1"
        assert result.match_type == "exact"
    
    def test_empty_product_list(self):
        """Test matching with empty product list."""
        matcher = ProductMatcher()
        result = matcher.match_product("apple", [])
        
        assert result is None
    
    def test_whitespace_handling(self, sample_products):
        """Test handling of extra whitespace."""
        matcher = ProductMatcher()
        result = matcher.match_product("  red apple  ", sample_products)
        
        assert result is not None
        assert result.product["product_id"] == "1"
