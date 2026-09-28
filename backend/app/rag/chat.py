"""Shared chat settings for the OpenAI-compatible endpoint in .env.

GPT-OSS on Groq spends some of the token budget on reasoning. Those calls
ask for a low reasoning effort and a larger completion budget so the JSON
answer is not cut off. Other models keep the smaller limit.
"""

from __future__ import annotations

import os


def chat_model(default: str = "llama3.2") -> str:
    return (os.environ.get("OPENAI_CHAT_MODEL") or default).strip()


def chat_base_url() -> str | None:
    raw = (os.environ.get("OPENAI_BASE_URL") or "").strip()
    return raw or None


def _is_gpt_oss(model: str | None = None) -> bool:
    return "gpt-oss" in (model if model is not None else chat_model(""))


def token_budget(requested: int) -> int:
    if _is_gpt_oss():
        return max(requested, 1024)
    return requested


def completion_kwargs(max_tokens: int, default_model: str = "llama3.2") -> dict:
    model = chat_model(default_model)
    kwargs = {
        "model": model,
        "temperature": 0,
        "max_tokens": token_budget(max_tokens),
    }
    if _is_gpt_oss(model):
        kwargs["extra_body"] = {"reasoning_effort": "low"}
    return kwargs


RATE_LIMITS: list[str] = []


class ChatProblem(Exception):
    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(kind)


def call_chat(messages: list[dict], max_tokens: int, default_model: str = "llama3.2", timeout: float = 45.0) -> str:
    """Call the configured chat model. Rate limits are recorded and not retried on another model."""
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ChatProblem("missing_key")
    from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

    client = OpenAI(api_key=api_key, base_url=chat_base_url(), timeout=timeout)
    try:
        response = client.chat.completions.create(
            messages=messages,
            **completion_kwargs(max_tokens, default_model=default_model),
        )
    except RateLimitError as exc:
        RATE_LIMITS.append("rate_limit")
        raise ChatProblem("rate_limit") from exc
    except APIStatusError as exc:
        if getattr(exc, "status_code", None) == 429:
            RATE_LIMITS.append("rate_limit")
            raise ChatProblem("rate_limit") from exc
        raise
    except (APITimeoutError, APIConnectionError) as exc:
        raise ChatProblem("unavailable") from exc
    return message_text(response.choices[0].message)


def message_text(message) -> str:
    content = getattr(message, "content", None) or ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("text"):
                parts.append(block["text"])
        content = "\n".join(parts)
    return str(content).strip()
