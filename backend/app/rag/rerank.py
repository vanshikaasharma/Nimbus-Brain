"""Rescore hybrid hits with a local cross-encoder.

The fusion list is only a shortlist. This model reads the question and each
chunk together and keeps the top three.
"""

from __future__ import annotations

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
TOP_K = 3

_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder

        _model = CrossEncoder(MODEL_NAME)
    return _model


def rerank(question: str, hits: list[dict]) -> list[dict]:
    if not hits:
        return []
    pairs = [(question, hit["body"]) for hit in hits]
    scores = get_model().predict(pairs)
    ordered = sorted(zip(hits, scores), key=lambda item: float(item[1]), reverse=True)
    kept = []
    for hit, score in ordered[:TOP_K]:
        copy = dict(hit)
        copy["score"] = float(score)
        kept.append(copy)
    return kept
