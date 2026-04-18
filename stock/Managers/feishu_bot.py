"""
飞书自定义机器人 Webhook 文本发送（信号通知等）。
文档：POST application/json，msg_type=text，content.text 为正文。
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import logging
import time
from contextlib import contextmanager
from typing import Iterator, Optional, Set

import requests

logger = logging.getLogger(__name__)

# 飞书文本消息常见上限约 2 万字符；保守截断避免被拒
FEISHU_TEXT_MAX_LEN = 15000

_feishu_batch_texts: contextvars.ContextVar[Optional[Set[str]]] = contextvars.ContextVar(
    "_feishu_batch_texts", default=None
)


def redact_feishu_webhook(url: str) -> str:
    """日志中脱敏 Webhook（保留前缀，隐藏 hook 密钥段）。"""
    if not url:
        return ""
    s = url.strip()
    marker = "hook/"
    i = s.find(marker)
    if i != -1:
        return s[: i + len(marker)] + "***"
    return (s[:48] + "...") if len(s) > 48 else s


def feishu_gen_sign(timestamp: str, secret: str) -> str:
    """
    飞书自定义机器人「签名校验」：key = timestamp + '\\n' + 密钥，对空串做 HMAC-SHA256 再 Base64。
    与开放平台文档一致（timestamp 为秒级字符串，与服务器相差须在约 1 小时内）。
    """
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    mac = hmac.new(string_to_sign, b"", hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def _normalize_feishu_text(text: str) -> tuple[str, bool]:
    if text is None:
        return "", False
    s = str(text)
    if len(s) <= FEISHU_TEXT_MAX_LEN:
        return s, False
    logger.warning("飞书正文超过 %s 字符，已截断", FEISHU_TEXT_MAX_LEN)
    return s[:FEISHU_TEXT_MAX_LEN], True


def _feishu_webhook_post_json(
    webhook_url: str,
    payload: dict,
    *,
    timeout: float = 10.0,
    sign_secret: Optional[str] = None,
) -> bool:
    """向自定义机器人 Webhook POST JSON；成功判据与 send_feishu_text 一致。"""
    url = (webhook_url or "").strip()
    if not url:
        logger.error("飞书 Webhook URL 为空，跳过发送")
        return False

    body = dict(payload)
    sk = (sign_secret or "").strip()
    if sk:
        ts = str(int(time.time()))
        body["timestamp"] = ts
        body["sign"] = feishu_gen_sign(ts, sk)

    redacted = redact_feishu_webhook(url)
    try:
        resp = requests.post(
            url,
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        logger.error("飞书 Webhook 请求异常 [%s]: %s", redacted, e)
        return False

    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error(
            "飞书 Webhook HTTP %s [%s] body=%s",
            resp.status_code,
            redacted,
            (resp.text or "")[:500],
        )
        return False

    try:
        data = resp.json()
    except ValueError:
        logger.error("飞书 Webhook 响应非 JSON [%s]: %s", redacted, (resp.text or "")[:500])
        return False

    sc = data.get("StatusCode")
    code = data.get("code")
    if sc == 0 or code == 0:
        return True
    if isinstance(sc, int) and sc != 0:
        logger.error("飞书 Webhook 业务错误 [%s]: %s", redacted, str(data)[:500])
        return False
    if isinstance(code, int) and code != 0:
        logger.error("飞书 Webhook 业务错误 [%s]: %s", redacted, str(data)[:500])
        return False

    sm = str(data.get("StatusMessage") or data.get("msg") or "").lower()
    if sm == "success":
        return True

    logger.error("飞书 Webhook 未识别成功态 [%s]: %s", redacted, str(data)[:500])
    return False


def send_feishu_text(
    webhook_url: str,
    text: str,
    *,
    timeout: float = 10.0,
    sign_secret: Optional[str] = None,
) -> bool:
    """
    向飞书机器人 Webhook POST 一条 text 消息。
    sign_secret 非空时附带 timestamp（当前秒级时间戳字符串）与 sign（按飞书规则计算）。
    返回 True 表示 HTTP 与业务码均成功。
    """
    body, truncated = _normalize_feishu_text(text)
    if truncated:
        body = body + "\n...(截断)"
    return _feishu_webhook_post_json(
        webhook_url,
        {"msg_type": "text", "content": {"text": body}},
        timeout=timeout,
        sign_secret=sign_secret,
    )


def send_feishu_image(
    webhook_url: str,
    image_key: str,
    *,
    timeout: float = 15.0,
    sign_secret: Optional[str] = None,
) -> bool:
    """
    Webhook 发送图片消息（须先通过开放平台上传图片拿到 image_key）。
    文档：msg_type=image，content.image_key。
    """
    key = (image_key or "").strip()
    if not key:
        logger.error("飞书 image_key 为空，跳过发送图片")
        return False
    return _feishu_webhook_post_json(
        webhook_url,
        {"msg_type": "image", "content": {"image_key": key}},
        timeout=timeout,
        sign_secret=sign_secret,
    )


@contextmanager
def feishu_signal_send_batch() -> Iterator[None]:
    """
    包裹一次 signal.send_message（多 group_id 循环）：
    飞书单 Webhook 时同一条正文只 POST 一次。
    """
    s: Set[str] = set()
    token = _feishu_batch_texts.set(s)
    try:
        yield
    finally:
        _feishu_batch_texts.reset(token)


def feishu_batch_already_sent(message: str) -> bool:
    """同批次内该正文是否已成功发送过（用于多 group_id 只 POST 一次）。"""
    bucket = _feishu_batch_texts.get()
    if bucket is None:
        return False
    return str(message) in bucket


def feishu_batch_mark_sent(message: str) -> None:
    """成功送达后写入批次集合，后续 group_id 跳过。"""
    bucket = _feishu_batch_texts.get()
    if bucket is not None:
        bucket.add(str(message))
