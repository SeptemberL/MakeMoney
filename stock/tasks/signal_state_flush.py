from __future__ import annotations

import logging
from typing import Dict

from Managers.redis_kv import hdel, hgetall, hset, make_key
from Managers.runtime_settings import get_setting
from database.database import Database

logger = logging.getLogger(__name__)


_PENDING_HASH = None


def _pending_hash_key() -> str:
    global _PENDING_HASH
    if _PENDING_HASH is None:
        _PENDING_HASH = make_key("buffer", "signal_rule_state")
    return _PENDING_HASH


def buffer_signal_rule_state(rule_id: int, state_json: str) -> bool:
    """
    将信号规则状态写入 Redis 缓冲（Hash：rule_id -> state_json）。
    - 适用于大量小写入、且允许最终一致
    - 若 Redis 不可用，返回 False，调用方可回退为同步落库
    """
    try:
        return hset(_pending_hash_key(), str(int(rule_id)), str(state_json or "{}"))
    except Exception:
        return False


def flush_signal_rule_states_once() -> Dict[str, int]:
    """
    从 Redis 缓冲取出一批 signal_rule_state 并批量落库。
    返回 stats：{scanned, flushed, deleted, failed}
    """
    v = str(get_setting("REDIS", "signal_state_buffer_enabled", "0") or "").strip().lower()
    if v not in ("1", "true", "yes", "on"):
        return {"scanned": 0, "flushed": 0, "deleted": 0, "failed": 0, "disabled": 1}

    try:
        bs_raw = get_setting("REDIS", "signal_state_flush_batch_size", "500")
        batch_size = int(float(bs_raw)) if bs_raw is not None else 500
    except Exception:
        batch_size = 500
    if batch_size <= 0:
        batch_size = 500

    pending = hgetall(_pending_hash_key())
    if not pending:
        return {"scanned": 0, "flushed": 0, "deleted": 0, "failed": 0}

    items = list(pending.items())[:batch_size]
    db = Database.Create()
    flushed = 0
    failed = 0
    keys_to_delete = []
    try:
        for k, state_json in items:
            try:
                rid = int(str(k))
                db.upsert_signal_rule_state(rule_id=rid, state_json=str(state_json or "{}"))
                flushed += 1
                keys_to_delete.append(str(k))
            except Exception:
                failed += 1
        # 成功落库的字段再删除（失败的保留以便下次重试）
        deleted = hdel(_pending_hash_key(), *keys_to_delete) if keys_to_delete else 0
        return {
            "scanned": len(items),
            "flushed": flushed,
            "deleted": int(deleted),
            "failed": failed,
            "remain": max(0, len(pending) - int(deleted)),
        }
    finally:
        db.close()


def run_signal_state_flush_job():
    """
    APScheduler 任务入口。
    注意：这里不抛异常，避免任务失败导致调度器噪音。
    """
    try:
        st = flush_signal_rule_states_once()
        if st.get("flushed"):
            logger.info("signal_state_flush: %s", st)
        return st
    except Exception as e:
        logger.warning("signal_state_flush failed: %s", e)
        return {"scanned": 0, "flushed": 0, "deleted": 0, "failed": 1, "error": str(e)}

