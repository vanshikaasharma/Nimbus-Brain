"""Rescore hybrid hits. MiniLM is the default. Qwen3-Reranker-0.6B is optional.

RERANKER=minilm uses cross-encoder/ms-marco-MiniLM-L-6-v2.
RERANKER=qwen3 scores yes/no next-token logits the way the Qwen3-Reranker
model card does. It is not a MiniLM cross-encoder.
"""

from __future__ import annotations

import os

MINILM = "cross-encoder/ms-marco-MiniLM-L-6-v2"
QWEN_RERANKER = "Qwen/Qwen3-Reranker-0.6B"
TOP_K = 3
QWEN_MAX_LENGTH = 2048
TASK = "Given a web search query, retrieve relevant passages that answer the query"

_minilm = None
_qwen = None


def reranker_name() -> str:
    name = (os.environ.get("RERANKER") or "minilm").strip().lower()
    if name not in {"minilm", "qwen3"}:
        raise ValueError("RERANKER must be minilm or qwen3.")
    return name


def get_model():
    global _minilm
    if _minilm is None:
        from sentence_transformers import CrossEncoder

        _minilm = CrossEncoder(MINILM)
    return _minilm


def _qwen_reranker():
    global _qwen
    if _qwen is None:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(QWEN_RERANKER, padding_side="left")
        model = AutoModelForCausalLM.from_pretrained(QWEN_RERANKER)
        model.eval()
        _qwen = (tokenizer, model)
    return _qwen


def _qwen_scores(question: str, bodies: list[str]) -> list[float]:
    """Official yes/no log-softmax score from the Qwen3-Reranker card."""
    import torch

    tokenizer, model = _qwen_reranker()
    token_true = tokenizer.convert_tokens_to_ids("yes")
    token_false = tokenizer.convert_tokens_to_ids("no")
    prefix = (
        "<|im_start|>system\nJudge whether the Document meets the requirements "
        'based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".'
        "<|im_end|>\n<|im_start|>user\n"
    )
    suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    prefix_tokens = tokenizer.encode(prefix, add_special_tokens=False)
    suffix_tokens = tokenizer.encode(suffix, add_special_tokens=False)
    pairs = [
        f"<Instruct>: {TASK}\n<Query>: {question}\n<Document>: {body[:1500]}"
        for body in bodies
    ]
    room = QWEN_MAX_LENGTH - len(prefix_tokens) - len(suffix_tokens)
    encoded = tokenizer(pairs, padding=False, truncation="longest_first", return_attention_mask=False, max_length=room)
    for index, ids in enumerate(encoded["input_ids"]):
        encoded["input_ids"][index] = prefix_tokens + ids + suffix_tokens
    inputs = tokenizer.pad(encoded, padding=True, return_tensors="pt", max_length=QWEN_MAX_LENGTH)
    with torch.no_grad():
        logits = model(**inputs).logits[:, -1, :]
        stacked = torch.stack([logits[:, token_false], logits[:, token_true]], dim=1)
        scores = torch.nn.functional.log_softmax(stacked, dim=1)[:, 1].exp()
    return [float(score) for score in scores.tolist()]


def _keep(hits: list[dict], scores) -> list[dict]:
    ordered = sorted(zip(hits, scores), key=lambda item: float(item[1]), reverse=True)
    kept = []
    for hit, score in ordered[:TOP_K]:
        copy = dict(hit)
        copy["score"] = float(score)
        kept.append(copy)
    return kept


def rerank(question: str, hits: list[dict]) -> list[dict]:
    if not hits:
        return []
    if reranker_name() == "qwen3":
        return _keep(hits, _qwen_scores(question, [hit["body"] for hit in hits]))
    pairs = [(question, hit["body"]) for hit in hits]
    return _keep(hits, get_model().predict(pairs))
