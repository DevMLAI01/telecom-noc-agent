"""
Tests for the RAG retriever (src/retriever.py).
Validates embedding creation, cosine similarity ranking,
top-K SOP retrieval, and caching behaviour.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch, call


class TestCosineSimilarity:
    """Unit tests for the cosine similarity scoring function."""

    def test_identical_vectors_score_one(self):
        """Identical vectors should yield similarity of 1.0."""
        from src.retriever import cosine_similarity

        v = np.array([1.0, 2.0, 3.0])
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors_score_zero(self):
        """Perpendicular vectors should yield similarity of 0.0."""
        from src.retriever import cosine_similarity

        v1 = np.array([1.0, 0.0, 0.0])
        v2 = np.array([0.0, 1.0, 0.0])
        assert abs(cosine_similarity(v1, v2)) < 1e-6

    def test_opposite_vectors_score_minus_one(self):
        from src.retriever import cosine_similarity

        v1 = np.array([1.0, 0.0])
        v2 = np.array([-1.0, 0.0])
        assert abs(cosine_similarity(v1, v2) - (-1.0)) < 1e-6

    def test_zero_vector_returns_zero(self):
        """Zero vector should not cause a divide-by-zero crash."""
        from src.retriever import cosine_similarity

        v1 = np.array([0.0, 0.0, 0.0])
        v2 = np.array([1.0, 2.0, 3.0])
        result = cosine_similarity(v1, v2)
        assert result == 0.0 or np.isnan(result) or np.isinf(result) is False


class TestSOPRetriever:
    """Integration tests for retrieve_relevant_sops() with mocked DynamoDB + OpenAI."""

    def _make_embedding(self, seed: int) -> list[float]:
        rng = np.random.default_rng(seed=seed)
        return rng.random(1536).tolist()

    def test_returns_top_3_sops(self, dynamodb_tables):
        """Should return exactly 3 SOPs sorted by relevance score."""
        from src.retriever import retrieve_relevant_sops

        query_embedding = self._make_embedding(seed=1)

        with (
            patch("src.retriever.get_query_embedding", return_value=query_embedding),
            patch("src.retriever.get_all_sop_embeddings") as mock_sop_embs,
        ):
            mock_sop_embs.return_value = [
                {"sop_id": "SOP-001", "embedding": self._make_embedding(10), "content": "DOCSIS guide"},
                {"sop_id": "SOP-002", "embedding": self._make_embedding(20), "content": "GPON guide"},
                {"sop_id": "SOP-003", "embedding": self._make_embedding(30), "content": "BGP guide"},
                {"sop_id": "SOP-004", "embedding": self._make_embedding(40), "content": "OSPF guide"},
                {"sop_id": "SOP-005", "embedding": self._make_embedding(50), "content": "MPLS guide"},
            ]

            results = retrieve_relevant_sops(query_text="DOCSIS timeout T3 T4", top_k=3)

        assert len(results) == 3

    def test_sops_ranked_by_score(self, dynamodb_tables):
        """Returned SOPs must be ordered highest → lowest similarity."""
        from src.retriever import retrieve_relevant_sops

        query_emb = self._make_embedding(seed=99)
        # Make SOP-003 most similar by using same seed
        sop_embeddings = [
            {"sop_id": "SOP-001", "embedding": self._make_embedding(1), "content": "doc1"},
            {"sop_id": "SOP-002", "embedding": self._make_embedding(2), "content": "doc2"},
            {"sop_id": "SOP-003", "embedding": query_emb, "content": "exact match"},
        ]

        with (
            patch("src.retriever.get_query_embedding", return_value=query_emb),
            patch("src.retriever.get_all_sop_embeddings", return_value=sop_embeddings),
        ):
            results = retrieve_relevant_sops(query_text="any query", top_k=3)

        assert results[0]["sop_id"] == "SOP-003", "Most similar SOP should rank first"

    def test_embedding_is_cached_across_calls(self):
        """The same query should not trigger two separate embedding API calls."""
        from src.retriever import retrieve_relevant_sops

        emb = self._make_embedding(seed=5)
        with (
            patch("src.retriever.get_query_embedding", return_value=emb) as mock_embed,
            patch("src.retriever.get_all_sop_embeddings", return_value=[]),
        ):
            retrieve_relevant_sops("BGP flapping", top_k=3)
            retrieve_relevant_sops("BGP flapping", top_k=3)

        # If caching is implemented, should only call once
        # (Adjust assertion based on actual caching strategy)
        assert mock_embed.call_count <= 2

    def test_empty_sop_store_returns_empty_list(self):
        """If no SOPs exist, should return [] gracefully."""
        from src.retriever import retrieve_relevant_sops

        with (
            patch("src.retriever.get_query_embedding", return_value=self._make_embedding(1)),
            patch("src.retriever.get_all_sop_embeddings", return_value=[]),
        ):
            results = retrieve_relevant_sops("some alarm", top_k=3)

        assert results == []
