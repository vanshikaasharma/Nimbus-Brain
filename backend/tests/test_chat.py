"""Chat settings for Groq GPT-OSS. No network call."""

from __future__ import annotations

import os
import unittest

from app.rag.chat import chat_base_url, completion_kwargs, token_budget


class ChatSettingsTests(unittest.TestCase):
    def test_base_url_strips_whitespace(self):
        previous = os.environ.get("OPENAI_BASE_URL")
        os.environ["OPENAI_BASE_URL"] = " https://api.groq.com/openai/v1 "
        try:
            self.assertEqual(chat_base_url(), "https://api.groq.com/openai/v1")
        finally:
            if previous is None:
                os.environ.pop("OPENAI_BASE_URL", None)
            else:
                os.environ["OPENAI_BASE_URL"] = previous

    def test_gpt_oss_gets_a_low_reasoning_budget(self):
        previous_model = os.environ.get("OPENAI_CHAT_MODEL")
        os.environ["OPENAI_CHAT_MODEL"] = "openai/gpt-oss-120b"
        try:
            kwargs = completion_kwargs(80)
            self.assertEqual(kwargs["model"], "openai/gpt-oss-120b")
            self.assertGreaterEqual(kwargs["max_tokens"], 1024)
            self.assertEqual(kwargs["extra_body"], {"reasoning_effort": "low"})
            self.assertGreaterEqual(token_budget(80), 1024)
        finally:
            if previous_model is None:
                os.environ.pop("OPENAI_CHAT_MODEL", None)
            else:
                os.environ["OPENAI_CHAT_MODEL"] = previous_model

    def test_other_models_keep_the_small_limit(self):
        previous_model = os.environ.get("OPENAI_CHAT_MODEL")
        os.environ["OPENAI_CHAT_MODEL"] = "llama3.2"
        try:
            kwargs = completion_kwargs(80)
            self.assertEqual(kwargs["max_tokens"], 80)
            self.assertNotIn("extra_body", kwargs)
        finally:
            if previous_model is None:
                os.environ.pop("OPENAI_CHAT_MODEL", None)
            else:
                os.environ["OPENAI_CHAT_MODEL"] = previous_model


if __name__ == "__main__":
    unittest.main()
