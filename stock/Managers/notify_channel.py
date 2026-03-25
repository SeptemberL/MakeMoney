"""
统一通知通道：根据 config.ini [NOTIFY] channel 选择飞书 Webhook 或微信（WXGroupManager + wxauto）。
供信号、NGA、LOF、批量更新等所有「发文本到群」场景复用。
"""

from __future__ import annotations

import logging
import platform
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


def _coerce_message(messages: Union[str, List[str], None]) -> str:
    if messages is None:
        return ""
    if isinstance(messages, list):
        return "\n".join(str(m) for m in messages if m is not None)
    return str(messages)


def _ensure_wx_for_notify():
    """尽量返回可用微信实例；Windows 下可延迟创建并写回 stockGlobal.wx。"""
    from stocks.stock_global import stockGlobal

    wx = getattr(stockGlobal, "wx", None)
    if wx is not None:
        return wx
    if platform.system() == "Windows":
        try:
            import wxauto

            wx = wxauto.WeChat()
            stockGlobal.wx = wx
            logger.info("微信实例已延迟创建（通知通道）")
            return wx
        except Exception as e:
            logger.warning("微信实例延迟创建失败: %s", e)
    return None


def send_notify_to_group(group_id: int, message: str) -> None:
    """
    按群组 ID 发送文本：飞书走全局 Webhook；微信走库中 message_group 映射。
    与 feishu_signal_send_batch 配合时，飞书同批次同正文只发一次。
    """
    from config import Config
    from Managers.feishu_bot import (
        feishu_batch_already_sent,
        feishu_batch_mark_sent,
        send_feishu_text,
    )
    from Managers.wx_group_manager import WXGroupManager
    from stocks.stock_global import stockGlobal

    text = _coerce_message(message).strip()
    if not text:
        return

    cfg = Config()
    channel = cfg.get_notify_channel()

    if channel == "feishu":
        if feishu_batch_already_sent(text):
            logger.debug("飞书通道：同批次已成功发送该正文，跳过 group_id=%s", group_id)
            return
        webhook = cfg.get_feishu_webhook_url()
        if not webhook:
            logger.error("NOTIFY.channel=feishu 但未配置 FEISHU.webhook_url，消息未发送")
            return
        timeout = cfg.get_feishu_timeout_seconds()
        sign_secret = cfg.get_feishu_sign_secret()
        if send_feishu_text(
            webhook, text, timeout=timeout, sign_secret=sign_secret
        ):
            feishu_batch_mark_sent(text)
        return

    wx = _ensure_wx_for_notify()
    if wx is None:
        wx = getattr(stockGlobal, "wx", None)
    if wx is None:
        logger.info("通知(模拟) group_id=%s, message=%s", group_id, text[:500])
        return

    chat_list = WXGroupManager().find_wx_group(group_id) or []
    if not chat_list:
        logger.warning("group_id=%s 未配置 chat_list，消息未发送", group_id)
        return
    for chat_name in chat_list:
        try:
            wx.SendMsg(text, chat_name)
        except Exception as e:
            logger.error("发送到 %s 失败: %s", chat_name, e)


def send_notify_fallback(message: Union[str, List[str], None]) -> None:
    """
    无明确 group_id 时的批量/汇总通知：
    - 飞书：整段文本 POST 一次到全局 Webhook
    - 微信：优先 [NOTIFY] fallback_group_id 对应群列表；未配置则用 [WX] TestImageSendTo 作为会话名
    """
    from config import Config
    from Managers.feishu_bot import send_feishu_text
    from Managers.wx_group_manager import WXGroupManager
    from stocks.stock_global import stockGlobal

    text = _coerce_message(message).strip()
    if not text:
        return

    cfg = Config()
    if cfg.get_notify_channel() == "feishu":
        webhook = cfg.get_feishu_webhook_url()
        if not webhook:
            logger.error("NOTIFY.channel=feishu 但未配置 FEISHU.webhook_url，fallback 消息未发送")
            return
        send_feishu_text(
            webhook,
            text,
            timeout=cfg.get_feishu_timeout_seconds(),
            sign_secret=cfg.get_feishu_sign_secret(),
        )
        return

    wx = _ensure_wx_for_notify()
    if wx is None:
        wx = getattr(stockGlobal, "wx", None)
    if wx is None:
        logger.info("通知(模拟) fallback: %s", text[:500])
        return

    fg = cfg.get_notify_fallback_group_id()
    if fg is not None:
        chat_list = WXGroupManager().find_wx_group(fg) or []
        if chat_list:
            for chat_name in chat_list:
                try:
                    wx.SendMsg(text, chat_name)
                except Exception as e:
                    logger.error("fallback 发送到 %s 失败: %s", chat_name, e)
            return
        logger.warning("fallback_group_id=%s 未配置 chat_list，改用 TestImageSendTo", fg)

    who = (cfg.get("WX", "TestImageSendTo") or "光影相生").strip()
    try:
        wx.SendMsg(text, who)
    except Exception as e:
        logger.error("fallback 发送到 %s 失败: %s", who, e)
