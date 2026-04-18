"""
stock_basic 名称查询工具：避免 routes 与 signals 循环 import。
"""

from __future__ import annotations

from typing import Optional

from database.database import Database
from Managers.redis_kv import get_json as _redis_get_json, set_json as _redis_set_json, make_key as _redis_key
from Managers.runtime_settings import get_setting as _rt_get_setting


def normalize_stock_code_for_basic(stock_code: str) -> str:
    """
    将业务中可能出现的股票代码规范化为 stock_basic.code 形式（通常为 A 股 6 位数字）。
    例：600000.SS / 600000.SH / 600000 -> 600000
    """
    code = (stock_code or "").strip()
    if not code:
        return ""
    if "." in code:
        code = code.split(".", 1)[0].strip()
    # 常见行情 key：sh600000 / sz000001
    if len(code) >= 8 and (code.startswith("sh") or code.startswith("sz") or code.startswith("bj")):
        tail = code[2:]
        if tail.isdigit():
            code = tail
    return code


def lookup_stock_name_from_basic(db: Database, stock_code: str) -> Optional[str]:
    """按股票代码从 stock_basic 查名称；查不到返回 None。"""
    code = normalize_stock_code_for_basic(stock_code)
    if not code:
        return None
    try:
        ttl_raw = _rt_get_setting("REDIS", "stock_name_ttl_seconds", "0")
        ttl = int(float(ttl_raw)) if ttl_raw is not None else 0
    except Exception:
        ttl = 0
    cache_key = None
    if ttl > 0:
        try:
            cache_key = _redis_key("cache", "stock_basic_name", code)
            cached = _redis_get_json(cache_key)
            if isinstance(cached, str) and cached.strip():
                return cached.strip()
        except Exception:
            cache_key = None
    try:
        row = db.fetch_one("SELECT name FROM stock_basic WHERE code=%s LIMIT 1", (code,))
        if row and row.get("name"):
            name = str(row.get("name"))
            if cache_key:
                try:
                    _redis_set_json(cache_key, name, ttl_seconds=ttl)
                except Exception:
                    pass
            return name
    except Exception:
        return None
    return None

