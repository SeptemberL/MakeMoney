from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


NotifyChannel = Literal["wechat", "wx", "feishu"]
FeishuSendMode = Literal["oapi", "https"]


@dataclass(frozen=True)
class FeishuGroup:
    """
    DB `message_group` 中 list_type=feishu 的一条配置。
    group_id 仍为业务侧使用的数值 ID（与现有规则/接口一致）。
    """

    group_id: int
    name: str
    send_mode: FeishuSendMode
    chat_id: Optional[str] = None
    webhook_url: Optional[str] = None
    sign_secret: Optional[str] = None
    app_id: Optional[str] = None
    app_secret: Optional[str] = None


class NotifyConfigError(ValueError):
    pass


class NotifySendError(RuntimeError):
    pass

