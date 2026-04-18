"""
股票信号通知卡片：将结构化字段渲染为与 TestScripts/stock_notify_card.html 同风格的 HTML。
供 HTTP 接口与推送侧拼接链接使用。
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List, Optional, Tuple

# 与前端卡片一致的行样式白名单
_ROW_STYLES = frozenset({"default", "mono", "highlight", "alert", "accent"})
_BADGE_STYLES = frozenset({"success", "warn", "neutral"})

_SIGNAL_TYPE_LABEL = {
    "price_range": "股价区间",
    "fibonacci_retrace": "斐波那契回撤",
    "price_level_interval": "到价提醒",
}

_MAX_PAYLOAD_BYTES = 12_000


def _fmt_price(v: Any) -> str:
    try:
        x = float(v)
        s = f"{x:.4f}".rstrip("0").rstrip(".")
        return s or "0"
    except (TypeError, ValueError):
        return str(v) if v is not None and v != "" else "—"


def rows_from_signal_payload(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    根据信号模板 render 所用的 payload（见 SignalMessageTemplate.render 的键）生成默认展示行。
    """
    st = str(p.get("signal_type") or "").strip()
    type_cn = _SIGNAL_TYPE_LABEL.get(st, st or "—")
    rows: List[Dict[str, Any]] = [{"label": "采用策略", "value": type_cn}]

    rows.append({"label": "当前价格", "value": _fmt_price(p.get("price")), "style": "mono"})

    if st == "price_range":
        lo, hi = p.get("lower"), p.get("upper")
        rows.append(
            {
                "label": "监控区间",
                "value": f"[ {_fmt_price(lo)} , {_fmt_price(hi)} ]",
                "style": "mono",
            }
        )
        b = str(p.get("boundary") or "")
        rows.append({"label": "触发边界", "value": b or "—"})
    elif st == "price_level_interval":
        rows.append(
            {
                "label": "目标价",
                "value": _fmt_price(p.get("target_price")),
                "style": "highlight",
            }
        )
        cond = str(p.get("mode_label") or p.get("mode") or "").strip()
        rows.append({"label": "触发条件", "value": cond or "—"})
    elif st == "fibonacci_retrace":
        z = str(p.get("zone_label") or p.get("boundary") or "").strip()
        rows.append({"label": "区域", "value": z or "—"})
        rows.append(
            {
                "label": "382 / 500 / 618",
                "value": f"{_fmt_price(p.get('level_382'))} / {_fmt_price(p.get('level_500'))} / {_fmt_price(p.get('level_618'))}",
                "style": "mono",
            }
        )

    return rows


def _clean_rows(raw: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        value = item.get("value")
        val_s = "" if value is None else str(value)
        style = str(item.get("style") or "default").strip()
        if style not in _ROW_STYLES:
            style = "default"
        if not label and not val_s:
            continue
        out.append({"label": label, "value": val_s, "style": style})
    return out


def normalize_notify_card_input(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    校验并归一化 API / 查询参数中的卡片配置。
    若提供 signal_payload 且未提供 rows，则用 rows_from_signal_payload 填充。
    """
    d = dict(data or {})

    logo = str(d.get("logoEmoji") or "📊")[:8]
    title = str(d.get("title") or "检测到价")[:80]
    subtitle = str(d.get("subtitle") or "Stock signal notify")[:120]
    badge_text = str(d.get("badgeText") or "信号")[:40]
    badge_style = str(d.get("badgeStyle") or "success").strip()
    if badge_style not in _BADGE_STYLES:
        badge_style = "success"

    stock_name = str(d.get("stockName") or d.get("stock_name") or "")[:80]
    stock_code = str(d.get("stockCode") or d.get("stock_code") or "")[:32]

    sp = d.get("signal_payload")
    rows_in = d.get("rows")
    if isinstance(rows_in, list) and len(rows_in) > 0:
        rows = _clean_rows(rows_in)
    elif isinstance(sp, dict):
        rows = _clean_rows(rows_from_signal_payload(sp))
        if not stock_name:
            stock_name = str(sp.get("stock_name") or "")[:80]
        if not stock_code:
            stock_code = str(sp.get("stock_code") or "")[:32]
    else:
        rows = _clean_rows(rows_in)

    if not rows:
        rows = [
            {"label": "采用策略", "value": "—", "style": "default"},
            {"label": "当前价格", "value": "—", "style": "mono"},
        ]

    remark = str(d.get("remark") or "")[:2000]
    ts = str(d.get("timestamp") or d.get("time") or "")[:40]
    if not ts and isinstance(sp, dict):
        ts = str(sp.get("time") or "")[:40]

    return {
        "logoEmoji": logo,
        "title": title,
        "subtitle": subtitle,
        "badgeText": badge_text,
        "badgeStyle": badge_style,
        "stockName": stock_name or "—",
        "stockCode": stock_code or "—",
        "rows": rows,
        "remark": remark,
        "timestamp": ts,
    }


def notify_card_context_for_template(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """供 Jinja 使用；字符串由模板引擎 autoescape 转义。"""
    n = normalize_notify_card_input(data)
    rows_out: List[Dict[str, str]] = []
    for r in n["rows"]:
        rows_out.append(
            {
                "label": r["label"],
                "value": r["value"],
                "style": r.get("style") or "default",
            }
        )
    return {
        "logo_emoji": n["logoEmoji"],
        "title": n["title"],
        "subtitle": n["subtitle"],
        "badge_text": n["badgeText"],
        "badge_style": n["badgeStyle"],
        "stock_name": n["stockName"],
        "stock_code": n["stockCode"],
        "rows": rows_out,
        "remark": n["remark"],
        "timestamp": n["timestamp"],
    }


def encode_notify_card_payload(data: Dict[str, Any]) -> str:
    """URL 查询用 urlsafe base64（无填充变体与标准互解码）。"""
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > _MAX_PAYLOAD_BYTES:
        raise ValueError("payload 过大")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_notify_card_payload(token: str) -> Dict[str, Any]:
    t = (token or "").strip()
    if not t:
        return {}
    pad = "=" * ((4 - len(t) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(t + pad)
    except Exception as e:
        raise ValueError("payload 解码失败") from e
    if len(raw) > _MAX_PAYLOAD_BYTES:
        raise ValueError("payload 过大")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ValueError("payload 非合法 JSON") from e
    if not isinstance(obj, dict):
        raise ValueError("payload 须为 JSON 对象")
    return obj


_RE_BASE_URL = re.compile(r"^https?://[^/]+", re.I)


def build_public_card_url(*, base_url: str, data: Dict[str, Any]) -> Tuple[str, str]:
    """
    返回 (path_with_query, absolute_url)。
    base_url 示例：https://example.com/ 或 request.url_root
    """
    token = encode_notify_card_payload(normalize_notify_card_input(data))
    path = f"/signal_notify/notify_card?payload={token}"
    root = (base_url or "").rstrip("/")
    if _RE_BASE_URL.match(root):
        abs_url = f"{root}{path}"
    else:
        abs_url = path
    return path, abs_url
