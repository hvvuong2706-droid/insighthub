import unittest
from unittest.mock import patch

from pydantic import ValidationError
from support import configured, real_config

from app.core.config import Settings
from app.services.chunking import chunk_text


class ConfigTests(unittest.TestCase):
    def test_fixture_requires_both_explicit_providers(self):
        for values in (
            {"rag_mode": "fixture", "llm_provider": "gemini"},
            {"rag_mode": "real"},
            {"rag_mode": "typo"},
            {"llm_provider": "bedrock"},
            {"embedding_provider": "local"},
            {"llm_provider": "unknown"},
            {"embedding_provider": "unknown"},
            {"embedding_model": "fake-model"},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                with configured(**values):
                    pass

    def test_real_requires_credentials_explicit_model_and_endpoint(self):
        for values in (
            {"openai_api_key": ""},
            {"openai_base_url": ""},
            {"openai_base_url": "https://user:secret@host/v1"},
            {"openai_base_url": "https://host/v1?key=secret"},
            {"openai_base_url": "https://host/v1#fragment"},
            {"openai_base_url": "file:///tmp/gateway"},
            {"openai_base_url": "https://host:bad/v1"},
            {"llm_model": ""},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                with real_config(**values):
                    pass

    def test_settings_errors_hide_secrets(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValidationError) as raised:
                Settings(
                    _env_file=None, llm_provider="bad", openai_api_key="super-secret"
                )
        self.assertNotIn("super-secret", str(raised.exception))

    def test_invalid_numeric_configuration(self):
        for key, value in (
            ("chunk_size", 1),
            ("chunk_overlap", 800),
            ("embedding_dim", 0),
            ("embedding_dim", 2001),
            ("retrieval_top_k", 21),
            ("hnsw_ef_search", 0),
            ("provider_timeout_seconds", "nan"),
            ("embedding_batch_size", 0),
            ("max_upload_bytes", -1),
        ):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                with configured(**{key: value}):
                    pass

    def test_ollama_uses_dedicated_native_dimension(self):
        with real_config("ollama", embedding_provider="ollama") as settings:
            self.assertEqual(settings.resolved_embedding_model, "mxbai-embed-large")
        for values in (
            {"embedding_model": "deepseek-r1:14b"},
            {"embedding_dim": 768},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                with real_config("ollama", embedding_provider="ollama", **values):
                    pass

    def test_identity_changes_with_vector_space_but_not_chat_model_or_key(self):
        with real_config() as settings:
            baseline = settings.embedding_identity_id
        for values in (
            {"embedding_model": "other"},
            {"embedding_dim": 768},
            {"embedding_revision": "2"},
            {"openai_base_url": "https://other.example/v1"},
        ):
            with real_config(**values) as settings:
                self.assertNotEqual(baseline, settings.embedding_identity_id)
        with real_config(llm_model="other-chat", openai_api_key="rotated") as settings:
            self.assertEqual(baseline, settings.embedding_identity_id)
        with configured() as settings:
            self.assertNotEqual(baseline, settings.embedding_identity_id)

    def test_chunking_progress_overlap_and_empty(self):
        with configured(chunk_size=4, chunk_overlap=2):
            self.assertEqual(chunk_text("a b c d e f g"), ["a b c", "c d e", "e f g"])
            self.assertEqual(chunk_text(" \n "), [])
