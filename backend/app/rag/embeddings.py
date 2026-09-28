"""Local embeddings. BGE-small is the default. Qwen3-Embedding-0.6B is optional.

EMBEDDING_MODEL=bge uses BAAI/bge-small-en-v1.5 (384 dimensions) and doc_chunks.
EMBEDDING_MODEL=qwen3 uses Qwen/Qwen3-Embedding-0.6B (1024 dimensions) and
doc_chunks_qwen3. The two vector indexes are never mixed.

Qwen queries use the official sentence-transformers prompt named "query"
(Instruct + Query). Documents are embedded with no instruction. Vectors are
L2-normalized. Official model card: Qwen/Qwen3-Embedding-0.6B, dimension 1024.
"""

from __future__ import annotations

import os

BGE_MODEL = "BAAI/bge-small-en-v1.5"
QWEN_MODEL = "Qwen/Qwen3-Embedding-0.6B"
BGE_DIM = 384
QWEN_DIM = 1024
TABLES = {"bge": "doc_chunks", "qwen3": "doc_chunks_qwen3"}

_bge = None
_qwen = None


def embedding_backend() -> str:
    name = (os.environ.get("EMBEDDING_MODEL") or "bge").strip().lower()
    if name not in TABLES:
        raise ValueError("EMBEDDING_MODEL must be bge or qwen3.")
    return name


def embedding_dim() -> int:
    return QWEN_DIM if embedding_backend() == "qwen3" else BGE_DIM


def doc_table() -> str:
    return TABLES[embedding_backend()]


def get_model():
    global _bge
    if _bge is None:
        from fastembed import TextEmbedding

        _bge = TextEmbedding(model_name=BGE_MODEL)
    return _bge


def _qwen_model():
    global _qwen
    if _qwen is None:
        from sentence_transformers import SentenceTransformer

        _qwen = SentenceTransformer(QWEN_MODEL)
    return _qwen


def embed_texts(texts: list[str], query: bool = False) -> list[list[float]]:
    if embedding_backend() == "bge":
        return [vec.tolist() for vec in get_model().embed(texts)]
    model = _qwen_model()
    kwargs = {"normalize_embeddings": True}
    if query:
        kwargs["prompt_name"] = "query"
    vectors = model.encode(list(texts), **kwargs)
    rows = [vec.tolist() for vec in vectors]
    if rows and len(rows[0]) != QWEN_DIM:
        raise RuntimeError(f"Qwen3 embedding dim is {len(rows[0])}, expected {QWEN_DIM}.")
    return rows
