# =============================================================================
# src/retriever.py
# =============================================================================
# Purpose: Loads SOP documents from DynamoDB and performs semantic similarity
# search using OpenAI embeddings + numpy cosine similarity.
#
# Architecture:
#   - On first call, scans the DynamoDB 'telecom-noc-sops' table to load all SOPs.
#   - Generates embeddings for all SOPs once per Lambda container lifecycle
#     (module-level cache avoids redundant OpenAI API calls on warm invocations).
#   - retrieve_sops() embeds the query and returns top-k SOPs by cosine similarity.
#
# No local vector database is used. With 5 SOP documents, numpy brute-force
# cosine similarity is faster than any DB overhead and costs fractions of a cent.
#
# In production, replace DYNAMODB_SOPS_TABLE items with real SOP documents
# loaded from Confluence, SharePoint, or PDF manuals via seed_dynamodb.py.
# =============================================================================

import os
import numpy as np
import boto3
from botocore.exceptions import ClientError
from langchain_openai import OpenAIEmbeddings

# ---------------------------------------------------------------------------
# Configuration — read from environment variables
# ---------------------------------------------------------------------------
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SOPS_TABLE_NAME = os.getenv("DYNAMODB_SOPS_TABLE", "telecom-noc-sops")

# ---------------------------------------------------------------------------
# Module-level caches — populated once per Lambda container lifecycle.
# On warm invocations these are already populated, so DynamoDB and OpenAI
# are NOT called again, keeping latency and cost minimal.
# ---------------------------------------------------------------------------
_sop_documents: list[dict] | None = None  # Raw SOP items from DynamoDB
_sop_embeddings: np.ndarray | None = None  # Shape: (num_sops, embedding_dim)


def _get_dynamodb_table():
    """Returns a boto3 DynamoDB Table resource for the SOPs table."""
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return dynamodb.Table(SOPS_TABLE_NAME)


def load_sops_from_dynamodb() -> list[dict]:
    """
    Scans the DynamoDB SOPs table and returns all SOP items.

    Returns:
        List of dicts, each with keys: sop_id, content, source, category, alarm_type.
    """
    global _sop_documents

    if _sop_documents is not None:
        return _sop_documents

    print(f"   [Retriever] Loading SOPs from DynamoDB table '{SOPS_TABLE_NAME}'...")
    try:
        table = _get_dynamodb_table()
        response = table.scan()
        items = response.get("Items", [])

        # Handle DynamoDB pagination (unlikely with 5 docs, but correct to handle)
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        # Sort by sop_id for deterministic ordering
        items.sort(key=lambda x: x.get("sop_id", ""))
        _sop_documents = items
        print(f"   [Retriever] Loaded {len(items)} SOP documents from DynamoDB.")
        return _sop_documents

    except ClientError as e:
        print(f"   [Retriever] ERROR loading SOPs from DynamoDB: {e}")
        raise


def _get_sop_embeddings() -> tuple[list[dict], np.ndarray]:
    """
    Returns SOP documents and their embeddings, using the module-level cache.

    On the first call (cold start), fetches SOPs from DynamoDB and generates
    embeddings via OpenAI text-embedding-3-small. Subsequent calls (warm
    invocations) return the cached values immediately.

    Returns:
        Tuple of (sop_documents list, embeddings numpy array of shape (n, dim)).
    """
    global _sop_documents, _sop_embeddings

    if _sop_embeddings is not None:
        return _sop_documents, _sop_embeddings

    # Load SOPs from DynamoDB
    sops = load_sops_from_dynamodb()
    sop_texts = [sop["content"] for sop in sops]

    # Generate embeddings for all SOPs using OpenAI
    print(f"   [Retriever] Generating embeddings for {len(sop_texts)} SOPs (cold start)...")
    embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    embeddings_list = embedder.embed_documents(sop_texts)

    _sop_embeddings = np.array(embeddings_list, dtype=np.float32)
    print(f"   [Retriever] Embeddings cached. Shape: {_sop_embeddings.shape}")

    return _sop_documents, _sop_embeddings


def _cosine_similarity(query_vec: np.ndarray, doc_matrix: np.ndarray) -> np.ndarray:
    """
    Computes cosine similarity between a query vector and a matrix of doc vectors.

    Args:
        query_vec:  1-D numpy array of shape (dim,)
        doc_matrix: 2-D numpy array of shape (num_docs, dim)

    Returns:
        1-D numpy array of cosine similarity scores, shape (num_docs,)
    """
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    doc_norms = doc_matrix / (np.linalg.norm(doc_matrix, axis=1, keepdims=True) + 1e-10)
    return doc_norms @ query_norm


def retrieve_sops(query: str, k: int = 3) -> list[str]:
    """
    Performs semantic similarity search against the DynamoDB SOP collection.

    Takes a natural-language query (derived from the alarm error message and
    telemetry data) and returns the top-k most semantically similar SOP text
    chunks using OpenAI embeddings and numpy cosine similarity.

    This is the public interface consumed by Node 2 (get_manuals) in nodes.py.
    The return type is identical to the previous ChromaDB implementation.

    Args:
        query: A natural language description of the network fault to search for.
               Example: "DOCSIS T3 timeout upstream noise ingress Arris CMTS"
        k:     Number of top SOP documents to return (default: 3).

    Returns:
        A list of SOP content strings ordered by semantic relevance (most relevant first).
    """
    sops, embeddings = _get_sop_embeddings()

    # Embed the query
    embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    query_vec = np.array(embedder.embed_query(query), dtype=np.float32)

    # Compute cosine similarity scores
    scores = _cosine_similarity(query_vec, embeddings)

    # Get indices of top-k most similar SOPs
    top_k_indices = np.argsort(scores)[::-1][:k]

    sop_texts = []
    for idx in top_k_indices:
        sop = sops[idx]
        sop_id = sop.get("sop_id", f"DOC-{idx}")
        source = sop.get("source", "Unknown")
        print(f"   [Retriever] Retrieved: {sop_id} | Source: {source} | Score: {scores[idx]:.4f}")
        sop_texts.append(sop["content"])

    return sop_texts
