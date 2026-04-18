from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from Managers.feishu_bot import send_feishu_image, send_feishu_text
from Managers.feishu_media_upload import feishu_obtain_tenant_access_token, feishu_upload_im_image
from Managers.feishu_oapi_client import build_client, coerce_app_config
from Managers.notify_types import FeishuGroup, NotifyConfigError, NotifySendError

logger = logging.getLogger(__name__)


def _safe(s: Optional[str]) -> str:
    return (s or "").strip()


def _mask_secret(s: str, *, keep: int = 3) -> str:
    """日志脱敏：显示前后少量字符与长度，避免泄露密钥。"""
    v = (s or "").strip()
    if not v:
        return ""
    if len(v) <= keep * 2:
        return "*" * len(v)
    return f"{v[:keep]}***{v[-keep:]}(len={len(v)})"


@dataclass(frozen=True)
class FeishuSendResult:
    ok: bool
    error: Optional[str] = None


class FeishuHttpsSender:
    def send_text(self, group: FeishuGroup, text: str) -> FeishuSendResult:
        url = _safe(group.webhook_url)
        if not url:
            return FeishuSendResult(ok=False, error=f"飞书 group_id={group.group_id} 缺少 webhook_url")
        # webhook 签名密钥仅来自 group 级配置；未提供则不带签名发送
        sign_secret = _safe(group.sign_secret)
        ok = send_feishu_text(
            url,
            text,
            timeout=10.0,
            sign_secret=sign_secret or None,
        )
        return FeishuSendResult(ok=bool(ok), error=None if ok else "飞书 HTTPS 发送失败")

    def send_image(self, group: FeishuGroup, image_key: str) -> FeishuSendResult:
        url = _safe(group.webhook_url)
        if not url:
            return FeishuSendResult(ok=False, error=f"飞书 group_id={group.group_id} 缺少 webhook_url")
        sign_secret = _safe(group.sign_secret)
        ok = send_feishu_image(
            url,
            image_key,
            timeout=15.0,
            sign_secret=sign_secret or None,
        )
        return FeishuSendResult(ok=bool(ok), error=None if ok else "飞书 HTTPS 发图失败")


class FeishuOapiSender:
    """
    使用 lark-oapi 发送消息到 chat_id。
    依赖全局 FEISHU.app_id / FEISHU.app_secret。
    """

    def send_text(self, group: FeishuGroup, text: str) -> FeishuSendResult:
        chat_id = _safe(group.chat_id)
        if not chat_id:
            return FeishuSendResult(ok=False, error=f"飞书 group_id={group.group_id} 缺少 chat_id")

        cfg = coerce_app_config(group.app_id, group.app_secret)
        if cfg is None:
            return FeishuSendResult(ok=False, error=f"飞书 group_id={group.group_id} 未配置 app_id/app_secret")

        try:
            client = build_client(cfg)
            # 延迟导入：避免未安装 lark-oapi 时影响其他通道
            from lark_oapi.api.im.v1 import (  # type: ignore
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content('{"text": "%s"}' % (str(text).replace("\\", "\\\\").replace('"', '\\"')))
                    .build()
                )
                .build()
            )
            resp = client.im.v1.message.create(req)
            if getattr(resp, "success", None):
                return FeishuSendResult(ok=True)
            # resp.code/resp.msg 通常可用
            code = getattr(resp, "code", None)
            msg = getattr(resp, "msg", None)
            return FeishuSendResult(ok=False, error=f"OAPI 发送失败 code={code} msg={msg}")
        except Exception as e:
            logger.error("飞书 OAPI 发送异常: %s", e, exc_info=True)
            return FeishuSendResult(ok=False, error=str(e))

    def send_image(self, group: FeishuGroup, image_key: str) -> FeishuSendResult:
        chat_id = _safe(group.chat_id)
        if not chat_id:
            return FeishuSendResult(ok=False, error=f"飞书 group_id={group.group_id} 缺少 chat_id")

        cfg = coerce_app_config(group.app_id, group.app_secret)
        if cfg is None:
            return FeishuSendResult(ok=False, error=f"飞书 group_id={group.group_id} 未配置 app_id/app_secret")

        key = (image_key or "").strip()
        if not key:
            return FeishuSendResult(ok=False, error="image_key 为空")

        try:
            client = build_client(cfg)
            from lark_oapi.api.im.v1 import (  # type: ignore
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            content = json.dumps({"image_key": key}, ensure_ascii=False)
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("image")
                    .content(content)
                    .build()
                )
                .build()
            )
            resp = client.im.v1.message.create(req)
            if getattr(resp, "success", None):
                return FeishuSendResult(ok=True)
            code = getattr(resp, "code", None)
            msg = getattr(resp, "msg", None)
            return FeishuSendResult(ok=False, error=f"OAPI 发图失败 code={code} msg={msg}")
        except Exception as e:
            logger.error("飞书 OAPI 发图异常: %s", e, exc_info=True)
            return FeishuSendResult(ok=False, error=str(e))


def send_feishu_group_text(group: FeishuGroup, text: str) -> None:
    """
    根据 group.send_mode 路由发送。
    失败抛出 NotifySendError；配置缺失抛出 NotifyConfigError。
    """

    mode = (group.send_mode or "").strip().lower()
    if mode == "https":
        r = FeishuHttpsSender().send_text(group, text)
    elif mode == "oapi":
        r = FeishuOapiSender().send_text(group, text)
    else:
        raise NotifyConfigError(f"飞书 group_id={group.group_id} send_mode 非法: {group.send_mode}")
    if not r.ok:
        raise NotifySendError(r.error or "飞书发送失败")


def send_feishu_group_image(group: FeishuGroup, image_key: str) -> FeishuSendResult:
    mode = (group.send_mode or "").strip().lower()
    if mode == "https":
        return FeishuHttpsSender().send_image(group, image_key)
    if mode == "oapi":
        return FeishuOapiSender().send_image(group, image_key)
    return FeishuSendResult(ok=False, error=f"飞书 group_id={group.group_id} send_mode 非法: {group.send_mode}")


def try_send_feishu_signal_card_png(group: FeishuGroup, signal_template_payload: Dict[str, Any]) -> FeishuSendResult:
    """
    将模板 payload 渲染为 PNG，经开放平台上传后按 group 的 send_mode 发图片消息。
    须在飞书应用开启机器人与上传图片权限；message_group 行内需配置 app_id/app_secret。
    """
    from signals.signal_notify_card_png import render_notify_card_png

    aid = _safe(group.app_id)
    sec = _safe(group.app_secret)
    logger.info(
        "feishu_card_png: group_id=%s send_mode=%s app_id=%s app_secret=%s",
        group.group_id,
        group.send_mode,
        _mask_secret(aid, keep=4),
        _mask_secret(sec, keep=2),
    )
    if not aid or not sec:
        return FeishuSendResult(
            ok=False,
            error="飞书发图需在对应飞书 message_group 配置 app_id 与 app_secret（用于 tenant_token 上传图片）",
        )

    try:
        png = render_notify_card_png({"signal_payload": signal_template_payload})
    except Exception as e:
        logger.error("渲染信号卡片 PNG 失败: %s", e, exc_info=True)
        return FeishuSendResult(ok=False, error=f"渲染 PNG 失败: {e}")

    token = feishu_obtain_tenant_access_token(aid, sec)
    if not token:
        return FeishuSendResult(ok=False, error="获取 tenant_access_token 失败")

    image_key = feishu_upload_im_image(token, png, filename="signal_notify_card.png")
    if not image_key:
        return FeishuSendResult(ok=False, error="上传图片到飞书失败")

    return send_feishu_group_image(group, image_key)

