"""
统一通知通道：根据 config.ini [NOTIFY] channel 选择飞书 Webhook 或微信（WXGroupManager + wxauto）。
供信号、NGA、LOF、批量更新等所有「发文本到群」场景复用。
"""

from __future__ import annotations

import logging
import platform
from typing import Any, Dict, List, Optional, Union

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


def send_notify_to_group(
    group_id: int,
    message: str,
    *,
    feishu_signal_payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    按群组 ID 发送文本：
    - 全局渠道为飞书：从 DB 的飞书 group（list_type=feishu）解析并按 send_mode 发送（OAPI/HTTPS）
    - 全局渠道为微信：从 DB 的微信 group（list_type=weixin）解析并发送到 chat_list

    feishu_signal_payload：可选，为 SignalMessageTemplate 所用的 payload 字典；
    当 NOTIFY.channel=feishu 且 [SIGNAL_NOTIFY] feishu_send_card_image 开启时，在文本之后尝试再发一张卡片图。
    """
    from Managers.feishu_group_manager import FeishuGroupManager
    from Managers.feishu_senders import send_feishu_group_text, try_send_feishu_signal_card_png
    from Managers.runtime_settings import (
        get_feishu_signal_send_card_image,
        get_notify_channel,
        get_signal_send_text_enabled,
    )
    from Managers.wx_group_manager import WXGroupManager
    from stocks.stock_global import stockGlobal

    text = _coerce_message(message).strip()
    if not text:
        return

    channel = get_notify_channel()
    send_text = bool(get_signal_send_text_enabled())

    if channel == "feishu":
        try:
            grp = FeishuGroupManager().require(int(group_id))
            if send_text:
                send_feishu_group_text(grp, text)
            if feishu_signal_payload and get_feishu_signal_send_card_image():
                r = try_send_feishu_signal_card_png(grp, feishu_signal_payload)
                if not r.ok:
                    logger.warning(
                        "飞书信号卡片图未发送 group_id=%s: %s",
                        group_id,
                        r.error or "unknown",
                    )
        except Exception as e:
            logger.error("飞书发送失败 group_id=%s: %s", group_id, e)
        return

    # 非飞书通道（微信/WX）仅支持文本；若关闭文字通知则直接返回
    if not send_text:
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
    - 飞书：发送到 [NOTIFY] message_group（同一个 group_id），并按该飞书 group 的 send_mode 路由
    - 微信：优先 [NOTIFY] fallback_group_id 对应群列表；未配置则用 [WX] TestImageSendTo 作为会话名
    """
    from Managers.runtime_settings import (
        get_notify_channel,
        get_notify_message_group,
        get_setting,
    )
    from Managers.wx_group_manager import WXGroupManager
    from stocks.stock_global import stockGlobal

    text = _coerce_message(message).strip()
    if not text:
        return

    if get_notify_channel() == "feishu":
        fg = get_notify_message_group()
        if fg is None:
            logger.error("NOTIFY.channel=feishu 但未配置 NOTIFY.message_group，fallback 消息未发送")
            return
        send_notify_to_group(int(fg), text)
        return

    wx = _ensure_wx_for_notify()
    if wx is None:
        wx = getattr(stockGlobal, "wx", None)
    if wx is None:
        logger.info("通知(模拟) fallback: %s", text[:500])
        return

    fg = get_notify_message_group()
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

    who = str(get_setting("WX", "TestImageSendTo", "光影相生") or "光影相生").strip()
    try:
        wx.SendMsg(text, who)
    except Exception as e:
        logger.error("fallback 发送到 %s 失败: %s", who, e)
