import unittest
from unittest.mock import MagicMock, patch

import requests

from Managers.gemini_client import (
    GeminiAuthError,
    GeminiClient,
    GeminiConfigError,
    GeminiRequestError,
    GeminiTransientError,
)


class _Resp:
    def __init__(self, status_code: int, json_obj=None):
        self.status_code = status_code
        self._json_obj = json_obj

    def json(self):
        if isinstance(self._json_obj, Exception):
            raise self._json_obj
        return self._json_obj


class TestGeminiClient(unittest.TestCase):
    def test_missing_api_key_raises(self):
        with self.assertRaises(GeminiConfigError):
            GeminiClient(api_key="", model="m", timeout_seconds=1)

    def test_auth_error_no_retry(self):
        c = GeminiClient(api_key="k", model="m", timeout_seconds=1, max_retries=5)
        with patch("Managers.gemini_client.requests.post", return_value=_Resp(401, {})) as post:
            with self.assertRaises(GeminiAuthError):
                c.generate_text("hi")
            self.assertEqual(post.call_count, 1)

    def test_5xx_retries_then_success(self):
        c = GeminiClient(api_key="k", model="m", timeout_seconds=1, max_retries=2)
        seq = [
            _Resp(500, {"error": "x"}),
            _Resp(
                200,
                {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            ),
        ]
        with patch("Managers.gemini_client.time.sleep", return_value=None):
            with patch("Managers.gemini_client.requests.post", side_effect=seq) as post:
                out = c.generate_text("hi")
                self.assertEqual(out, "ok")
                self.assertEqual(post.call_count, 2)

    def test_4xx_non_auth_no_retry(self):
        c = GeminiClient(api_key="k", model="m", timeout_seconds=1, max_retries=3)
        with patch("Managers.gemini_client.requests.post", return_value=_Resp(400, {"error": "bad"})) as post:
            with self.assertRaises(GeminiRequestError):
                c.generate_text("hi")
            self.assertEqual(post.call_count, 1)

    def test_timeout_becomes_transient(self):
        c = GeminiClient(api_key="k", model="m", timeout_seconds=0.01, max_retries=0)
        with patch("Managers.gemini_client.requests.post", side_effect=requests.Timeout("timeout")):
            with self.assertRaises(GeminiTransientError):
                c.generate_text("hi")


if __name__ == "__main__":
    unittest.main()

