import os
import numpy as np
import boto3
from botocore.exceptions import ClientError
from langchain_openai import OpenAIEmbeddings

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SOPS_TABLE_NAME = os.getenv("DYNAMODB_SOPS_TABLE", "telecom-noc-sops")

_sop_documents: list[dict] | None = None
_sop_embeddings: np.ndarray | None = None


def _get_dynamodb_table():
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return dynamodb.Table(SOPS_TABLE_NAME)


def load_sops_from_dynamodb() -> list[dict]:
    global _sop_documents
    if _sop_documents is not None:
        return _sop_documents
    print(f"   [Retriever] Loading SOPs from DynamoDB table '{SOPS_TABLE_NAME}'...")
    try:
        table = _get_dynamodb_table()
        response = table.scan()
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
        items.sort(key=lambda x: x.get("sop_id", ""))
        _sop_documents = items
        print(f"   [Retriever] Loaded {len(items)} SOP documents from DynamoDB.")
        return _sop_documents
    except ClientError as e:
        print(f"   [Retriever] ERROR loading SOPs from DynamoDB: {e}")
        raise


def _get_sop_embeddings() -> tuple[list[dict], np.ndarray]:
    global _sop_documents, _sop_embeddings
    if _sop_embeddings is not None:
        return _sop_documents, _sop_embeddings
    sops = load_sops_from_dynamodb()
    sop_texts = [sop["content"] for sop in sops]
    print(f"   [Retriever] Generating embeddings for {len(sop_texts)} SOPs (cold start)...")
    embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    embeddings_list = embedder.embed_documents(sop_texts)
    _sop_embeddings = np.array(embeddings_list, dtype=np.float32)
    print(f"   [Retriever] Embeddings cached. Shape: {_sop_embeddings.shape}")
    return _sop_documents, _sop_embeddings


def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Compute cosine similarity between two 1-D vectors."""
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


def get_query_embedding(query_text: str) -> list[float]:
    """Embed a query string with text-embedding-3-small. Patchable in tests."""
    embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    return embedder.embed_query(query_text)


def get_all_sop_embeddings() -> list[dict]:
    """
    Return all SOP documents with their embeddings.
    Each dict has keys: sop_id, content, embedding (list[float]).
    Patchable in tests.
    """
    sops, embeddings = _get_sop_embeddings()
    return [
        {
            "sop_id": sop.get("sop_id", f"DOC-{i}"),
            "content": sop.get("content", ""),
            "embedding": embeddings[i].tolist(),
        }
        for i, sop in enumerate(sops)
    ]


def retrieve_relevant_sops(query_text: str, top_k: int = 3) -> list[dict]:
    """
    Semantic search over the SOP collection.

    Args:
        query_text: Natural-language description of the network fault.
        top_k:      Number of top SOPs to return (default 3).

    Returns:
        List of SOP dicts sorted by relevance (highest first).
        Each dict contains: sop_id, content, score, and any other DynamoDB fields.
    """
    all_sops = get_all_sop_embeddings()
    if not all_sops:
        return []

    query_vec = np.array(get_query_embedding(query_text), dtype=np.float32)

    scored = []
    for sop in all_sops:
        sop_vec = np.array(sop["embedding"], dtype=np.float32)
        score = cosine_similarity(query_vec, sop_vec)
        scored.append({**sop, "score": float(score)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_k]

    for s in top:
        print(f"   [Retriever] Retrieved: {s['sop_id']} | Score: {s['score']:.4f}")

    return top


# ---------------------------------------------------------------------------
# Legacy alias — kept so existing callers (main.py) are not broken.
# ---------------------------------------------------------------------------
def retrieve_sops(query: str, k: int = 3) -> list[str]:
    """Return top-k SOP content strings (legacy interface)."""
    results = retrieve_relevant_sops(query_text=query, top_k=k)
    return [r["content"] for r in results]
