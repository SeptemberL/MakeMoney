from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

from Managers.notify_types import FeishuGroup, FeishuSendMode, NotifyConfigError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeishuGroupConfigRow:
    group_id: int
    name: str
    send_mode: FeishuSendMode
    chat_id: Optional[str]
    webhook_url: Optional[str]
    sign_secret: Optional[str]
    app_id: Optional[str]
    app_secret: Optional[str]

    def to_group(self) -> FeishuGroup:
        return FeishuGroup(
            group_id=int(self.group_id),
            name=str(self.name or "").strip(),
            send_mode=self.send_mode,
            chat_id=(str(self.chat_id).strip() if self.chat_id else None),
            webhook_url=(str(self.webhook_url).strip() if self.webhook_url else None),
            sign_secret=(str(self.sign_secret).strip() if self.sign_secret else None),
            app_id=(str(self.app_id).strip() if self.app_id else None),
            app_secret=(str(self.app_secret).strip() if self.app_secret else None),
        )


class FeishuGroupManager:
    """
    从 DB 的 message_group 表加载飞书 group 配置（list_type=feishu）。
    这一层只负责“读取与基础校验”，不负责发送。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}
            cls._instance.reload()
        return cls._instance

    def reload(self) -> bool:
        try:
            from database.database import Database

            db = Database.Create()
            db.ensure_message_group_tables()
            rows = db.get_all_message_groups(list_type="feishu") or []
            db.close()

            cache: Dict[int, FeishuGroup] = {}
            for r in rows:
                gid = r.get("group_id")
                try:
                    igid = int(gid)
                except Exception:
                    continue
                name = str(r.get("name") or "").strip()
                mode_raw = str(r.get("send_mode") or "").strip().lower()
                if mode_raw not in ("oapi", "https"):
                    # 允许存在但不可用；发送时会给出明确错误
                    continue
                cache[igid] = FeishuGroup(
                    group_id=igid,
                    name=name or str(igid),
                    send_mode=mode_raw,  # type: ignore[assignment]
                    chat_id=(str(r.get("chat_id") or "").strip() or None),
                    webhook_url=(str(r.get("webhook_url") or "").strip() or None),
                    sign_secret=(str(r.get("sign_secret") or "").strip() or None),
                    app_id=(str(r.get("app_id") or "").strip() or None),
                    app_secret=(str(r.get("app_secret") or "").strip() or None),
                )

            self._cache = cache
            logger.info("从数据库加载了 %s 个飞书 group 配置", len(cache))
            return True
        except Exception as e:
            logger.warning("加载飞书 group 配置失败: %s", e, exc_info=True)
            self._cache = {}
            return False

    def get(self, group_id: int) -> Optional[FeishuGroup]:
        try:
            gid = int(group_id)
        except Exception:
            return None
        return self._cache.get(gid)

    def require(self, group_id: int) -> FeishuGroup:
        g = self.get(group_id)
        if g is None:
            raise NotifyConfigError(f"飞书 group_id={group_id} 未配置")
        return g

