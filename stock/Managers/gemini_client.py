from __future__ import annotations

import os
import logging
import time
import atexit
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from config import Config

logger = logging.getLogger(__name__)

_REQ_LOCK = threading.Lock()
_REQ_TOTAL = 0


def _next_request_no() -> int:
    """
    Gemini 实际发出 HTTP 请求的全局序号（进程内）。
    注意：重试也算一次实际请求。
    """
    global _REQ_TOTAL
    with _REQ_LOCK:
        _REQ_TOTAL += 1
        return _REQ_TOTAL


def get_gemini_request_total() -> int:
    """获取当前进程内 Gemini 实际发出 HTTP request 总数。"""
    with _REQ_LOCK:
        return int(_REQ_TOTAL)


def _clip_for_log(s: Optional[str], *, limit: int = 20000) -> str:
    v = "" if s is None else str(s)
    if limit <= 0:
        return v
    if len(v) <= limit:
        return v
    return v[:limit] + f"\n...[已截断：原始长度={len(v)}，上限={limit}]"


def _log_total_at_exit() -> None:
    try:
        total = get_gemini_request_total()
        if total > 0:
            logger.info("Gemini 本进程累计 request 总数 total_requests=%s", total)
    except Exception:
        # 避免退出阶段因日志/锁问题影响进程退出
        return


atexit.register(_log_total_at_exit)


class GeminiError(RuntimeError):
    pass


class GeminiConfigError(GeminiError):
    pass


class GeminiAuthError(GeminiError):
    pass


class GeminiRequestError(GeminiError):
    """不可重试错误（通常为 4xx，或响应格式非法）。"""


class GeminiTransientError(GeminiError):
    """可重试错误（网络、超时、5xx、429 等）。"""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _mask_secret(s: Optional[str], *, keep: int = 3) -> str:
    v = (s or "").strip()
    if not v:
        return ""
    if len(v) <= keep * 2:
        return "*" * len(v)
    return f"{v[:keep]}***{v[-keep:]}(len={len(v)})"


@dataclass(frozen=True)
class GeminiCallResult:
    text: str
    raw: Dict[str, Any]


class GeminiClient:
    """
    Gemini 统一调用封装。

    注意：本封装只用于服务端；严禁把 API Key 下发到浏览器。
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int = 2,
    ):
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._timeout_seconds = float(timeout_seconds)
        self._max_retries = int(max_retries)

        if not self._api_key:
            raise GeminiConfigError("Gemini API key 未配置（请设置环境变量 GEMINI_API_KEY 或 GOOGLE_API_KEY）")
        if not self._model:
            raise GeminiConfigError("Gemini model 未配置")
        if self._timeout_seconds <= 0:
            raise GeminiConfigError("Gemini timeout_seconds 非法（必须 > 0）")
        if self._max_retries < 0:
            raise GeminiConfigError("Gemini max_retries 非法（必须 >= 0）")

    @staticmethod
    def from_config(cfg: Optional[Config] = None) -> "GeminiClient":
        c = cfg or Config()
        api_key = c.get_gemini_api_key()
        if not api_key:
            raise GeminiConfigError("Gemini API key 未配置（请设置环境变量 GEMINI_API_KEY 或 GOOGLE_API_KEY）")
        model = c.get_gemini_model()
        timeout = c.get_gemini_timeout_seconds()
        return GeminiClient(api_key=api_key, model=model, timeout_seconds=timeout)

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        """
        最简文本生成：入参为 prompt，返回模型拼接后的纯文本。
        """
        return self.generate(prompt, system_instruction=system_instruction, temperature=temperature, top_p=top_p, top_k=top_k, max_output_tokens=max_output_tokens).text

    def generate(
        self,
        prompt: str,
        *,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> GeminiCallResult:
        text = (prompt or "").strip()
        if not text:
            raise GeminiRequestError("prompt 为空")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        params = {"key": self._api_key}

        contents = [{"role": "user", "parts": [{"text": text}]}]
        payload: Dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": str(system_instruction)}]}

        gen_cfg: Dict[str, Any] = {}
        if temperature is not None:
            gen_cfg["temperature"] = float(temperature)
        if top_p is not None:
            gen_cfg["topP"] = float(top_p)
        if top_k is not None:
            gen_cfg["topK"] = int(top_k)
        if max_output_tokens is not None:
            gen_cfg["maxOutputTokens"] = int(max_output_tokens)
        if gen_cfg:
            payload["generationConfig"] = gen_cfg

        attempt = 0
        start = time.time()
        while True:
            attempt += 1
            req_no = _next_request_no()
            try:
                resp = requests.post(
                    url,
                    params=params,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            except requests.Timeout as e:
                if attempt <= (self._max_retries + 1):
                    self._sleep_backoff(attempt)
                    if attempt <= (self._max_retries + 1):
                        continue
                logger.warning(
                    "Gemini 请求超时 model=%s attempt=%s/%s req_no=%s total_requests=%s",
                    self._model,
                    attempt,
                    self._max_retries + 1,
                    req_no,
                    get_gemini_request_total(),
                )
                raise GeminiTransientError("Gemini 请求超时") from e
            except requests.RequestException as e:
                if attempt <= (self._max_retries + 1):
                    self._sleep_backoff(attempt)
                    if attempt <= (self._max_retries + 1):
                        continue
                logger.warning(
                    "Gemini 网络请求失败 model=%s attempt=%s/%s err=%s req_no=%s total_requests=%s",
                    self._model,
                    attempt,
                    self._max_retries + 1,
                    type(e).__name__,
                    req_no,
                    get_gemini_request_total(),
                )
                raise GeminiTransientError(f"Gemini 网络请求失败: {type(e).__name__}") from e

            status = int(getattr(resp, "status_code", 0) or 0)
            elapsed_ms = int((time.time() - start) * 1000)

            if status in (401, 403):
                logger.warning(
                    "Gemini 鉴权失败 status=%s model=%s api_key=%s elapsed_ms=%s req_no=%s total_requests=%s",
                    status,
                    self._model,
                    _mask_secret(self._api_key),
                    elapsed_ms,
                    req_no,
                    get_gemini_request_total(),
                )
                raise GeminiAuthError(f"Gemini 鉴权失败 status={status}")

            if status == 429 or status >= 500:
                if status == 429:
                    logger.warning(
                        "Gemini 命中 429（限流）：请复制下方内容到 AI 手动执行\n"
                        "model=%s attempt=%s/%s elapsed_ms=%s req_no=%s total_requests=%s\n"
                        "----- system_instruction -----\n%s\n"
                        "----- prompt -----\n%s\n"
                        "------------------------------",
                        self._model,
                        attempt,
                        self._max_retries + 1,
                        elapsed_ms,
                        req_no,
                        get_gemini_request_total(),
                        _clip_for_log(system_instruction),
                        _clip_for_log(text),
                    )
                if attempt <= (self._max_retries + 1):
                    logger.info(
                        "Gemini 可重试错误 status=%s model=%s attempt=%s/%s elapsed_ms=%s req_no=%s total_requests=%s",
                        status,
                        self._model,
                        attempt,
                        self._max_retries + 1,
                        elapsed_ms,
                        req_no,
                        get_gemini_request_total(),
                    )
                    self._sleep_backoff(attempt)
                    continue
                raise GeminiTransientError(f"Gemini 服务端错误 status={status}", status_code=status)

            if status and status >= 400:
                logger.info(
                    "Gemini 请求失败 status=%s model=%s elapsed_ms=%s req_no=%s total_requests=%s",
                    status,
                    self._model,
                    elapsed_ms,
                    req_no,
                    get_gemini_request_total(),
                )
                raise GeminiRequestError(f"Gemini 请求失败 status={status}")

            try:
                data = resp.json()
            except Exception as e:
                raise GeminiRequestError("Gemini 响应不是合法 JSON") from e

            out = _extract_text(data)
            logger.info(
                "Gemini 调用成功 model=%s elapsed_ms=%s req_no=%s total_requests=%s",
                self._model,
                elapsed_ms,
                req_no,
                get_gemini_request_total(),
            )
            return GeminiCallResult(text=out, raw=data)

    def _sleep_backoff(self, attempt: int) -> None:
        # attempt=1 表示首次请求；重试时 attempt>=2
        if attempt <= 1:
            return
        # 0.5, 1.0, 2.0 ... capped
        delay = min(4.0, 0.5 * (2 ** (attempt - 2)))
        time.sleep(delay)


def _extract_text(resp_json: Dict[str, Any]) -> str:
    """
    从 Gemini generateContent 响应中提取拼接后的文本。
    https://ai.google.dev/api/rest/v1beta/models/generateContent
    """
    candidates = resp_json.get("candidates") or []
    if not candidates:
        raise GeminiRequestError("Gemini 响应缺少 candidates")
    content = (candidates[0] or {}).get("content") or {}
    parts = content.get("parts") or []
    texts = []
    for p in parts:
        t = (p or {}).get("text")
        if t:
            texts.append(str(t))
    if not texts:
        # 兼容部分返回：可能被安全策略拦截等
        raise GeminiRequestError("Gemini 响应不包含 text parts")
    return "".join(texts).strip()


def _smoke_main() -> int:
    """
    本地冒烟：仅当显式提供环境变量时才会发起真实请求。
    - GEMINI_API_KEY / GOOGLE_API_KEY：密钥
    - GEMINI_SMOKE_PROMPT：要发送的 prompt（为空则不执行）
    """
    prompt = (os.getenv("GEMINI_SMOKE_PROMPT") or "").strip()
    if not prompt:
        return 0
    try:
        c = GeminiClient.from_config()
        out = c.generate_text(prompt)
        print(out)
        return 0
    except Exception as e:
        print(f"[gemini_smoke] failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(_smoke_main())

