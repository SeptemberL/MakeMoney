from __future__ import annotations

import json
import logging
from typing import Any, Optional

from Managers.runtime_settings import get_setting

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    v = str(get_setting("REDIS", "enabled", "0") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _prefix() -> str:
    p = str(get_setting("REDIS", "key_prefix", "stock:") or "").strip()
    return p


def _client():
    """
    懒加载 Redis client。
    - 关闭或配置缺失时返回 None
    - 依赖 redis-py（requirements.txt 中 redis>=5）
    """
    if not _enabled():
        return None
    try:
        import redis  # type: ignore
    except Exception as e:
        logger.warning("Redis 未安装或导入失败，已忽略: %s", e)
        return None

    host = str(get_setting("REDIS", "host", "127.0.0.1") or "").strip() or "127.0.0.1"
    port_raw = get_setting("REDIS", "port", "6379")
    db_raw = get_setting("REDIS", "db", "0")
    pwd = get_setting("REDIS", "password", None)
    socket_timeout_raw = get_setting("REDIS", "socket_timeout_seconds", "0.5")
    try:
        port = int(port_raw)
    except Exception:
        port = 6379
    try:
        db = int(db_raw)
    except Exception:
        db = 0
    try:
        socket_timeout = float(socket_timeout_raw)
    except Exception:
        socket_timeout = 0.5

    try:
        r = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=(str(pwd) if pwd not in (None, "") else None),
            decode_responses=True,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
            health_check_interval=30,
        )
        return r
    except Exception as e:
        logger.warning("Redis client 初始化失败，已忽略: %s", e)
        return None


def make_key(*parts: str) -> str:
    ps = [str(p).strip() for p in parts if str(p).strip()]
    return _prefix() + ":".join(ps)


def get_json(key: str) -> Optional[Any]:
    r = _client()
    if r is None:
        return None
    try:
        s = r.get(key)
        if not s:
            return None
        return json.loads(s)
    except Exception:
        return None


def set_json(key: str, value: Any, *, ttl_seconds: int) -> bool:
    r = _client()
    if r is None:
        return False
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        ttl = int(ttl_seconds or 0)
        if ttl > 0:
            r.set(key, payload, ex=ttl)
        else:
            r.set(key, payload)
        return True
    except Exception:
        return False


def hset(name: str, key: str, value: str) -> bool:
    r = _client()
    if r is None:
        return False
    try:
        r.hset(name, key, value)
        return True
    except Exception:
        return False


def hgetall(name: str) -> dict[str, str]:
    r = _client()
    if r is None:
        return {}
    try:
        m = r.hgetall(name) or {}
        if isinstance(m, dict):
            return {str(k): str(v) for k, v in m.items()}
        return {}
    except Exception:
        return {}


def hdel(name: str, *keys: str) -> int:
    r = _client()
    if r is None:
        return 0
    try:
        ks = [str(k) for k in keys if k is not None and str(k) != ""]
        if not ks:
            return 0
        return int(r.hdel(name, *ks))
    except Exception:
        return 0

