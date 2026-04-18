"""
飞书开放平台 OAPI 发送封装（基于 lark-oapi）。

注意：这里只提供最小可用的导入与客户端构建入口；具体发送逻辑在后续 sender 中实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FeishuAppConfig:
    app_id: str
    app_secret: str


def build_client(cfg: FeishuAppConfig) -> lark.Client:
    """构建 lark-oapi Client（不做网络调用）。"""
    import lark_oapi as lark

    return lark.Client.builder().app_id(cfg.app_id).app_secret(cfg.app_secret).build()


def coerce_app_config(app_id: Optional[str], app_secret: Optional[str]) -> Optional[FeishuAppConfig]:
    aid = (app_id or "").strip()
    sec = (app_secret or "").strip()
    if not aid or not sec:
        return None
    return FeishuAppConfig(app_id=aid, app_secret=sec)

