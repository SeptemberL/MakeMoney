from __future__ import annotations

from typing import Any, Dict

from config import Config


def _db_value(section: str, key: str):
    db = None
    try:
        # 延迟导入：避免与 database/database.py 的循环依赖
        from database.database import Database

        db = Database.Create()
        db.ensure_system_settings_tables()
        return db.get_system_setting(section, key)
    except Exception:
        return None
    finally:
        if db:
            db.close()


def get_setting(section: str, key: str, fallback=None):
    """统一配置读取：DB 优先，缺失回退 config.ini。"""
    v = _db_value(section, key)
    if v is not None and str(v) != "":
        return v
    cfg = Config()
    ini_v = cfg.get(section, key)
    if ini_v is None or str(ini_v) == "":
        return fallback
    return ini_v


def get_notify_channel() -> str:
    v = str(get_setting("NOTIFY", "channel", "wechat") or "wechat").strip().lower()
    return v if v in ("wechat", "feishu", "wx") else "wechat"


def get_notify_message_group():
    v = get_setting("NOTIFY", "message_group", None)
    if v is None or str(v).strip() == "":
        # 兼容旧键
        v = get_setting("NOTIFY", "fallback_group_id", None)
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def get_filter_result_group_ids() -> list[int]:
    """
    股票筛选系统：筛选完成后推送结果到哪些 group_id（可多选）。
    配置来源：DB 优先，其次 config.ini
    - [NOTIFY] filter_result_group_ids = "1,2,3"
    """
    raw = get_setting("NOTIFY", "filter_result_group_ids", "") or ""
    s = str(raw).strip()
    if not s:
        return []
    out: list[int] = []
    for part in s.replace("，", ",").split(","):
        p = str(part).strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError:
            continue
    # 去重但保序
    seen = set()
    uniq: list[int] = []
    for gid in out:
        if gid in seen:
            continue
        seen.add(gid)
        uniq.append(gid)
    return uniq


def get_feishu_webhook_url():
    v = get_setting("FEISHU", "webhook_url", "")
    s = str(v or "").strip()
    return s or None


def get_feishu_sign():
    v = get_setting("FEISHU", "sign", "")
    s = str(v or "").strip()
    return s or None


def get_feishu_timeout_seconds() -> float:
    v = get_setting("FEISHU", "timeout_seconds", 10)
    try:
        iv = int(v)
        return float(iv if iv > 0 else 10)
    except Exception:
        return 10.0


def get_tushare_token():
    v = get_setting("TUSHARE", "TOKEN", "")
    s = str(v or "").strip()
    return s or None


def get_signal_price_source() -> str:
    """
    信号计算价格源：直接使用腾讯在线实时价。
    - realtime_qfq_opt_in: 使用腾讯实时价（raw），不做复权转换
    """
    # 按需求：忽略配置，固定使用腾讯实时行情
    return "realtime_qfq_opt_in"


def get_feishu_signal_send_card_image() -> bool:
    """
    是否在飞书渠道下，信号触发除文本外再发一张卡片 PNG（需飞书 message_group 配置 app_id/app_secret）。
    配置：DB 或 config.ini [SIGNAL_NOTIFY] feishu_send_card_image = 1 / true / yes / on
    """
    v = str(get_setting("SIGNAL_NOTIFY", "feishu_send_card_image", "") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def get_signal_send_text_enabled() -> bool:
    """
    信号触发是否发送“文字通知”（DB 优先）。
    - 默认开启
    - 关闭后：飞书仍可按 feishu_send_card_image 发送图片；微信/WX 通道将不再发送文本

    配置：DB 或 config.ini [SIGNAL_NOTIFY] send_text_enabled = 1 / true / yes / on
    """
    raw = get_setting("SIGNAL_NOTIFY", "send_text_enabled", "1")
    v = str(raw or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def get_signal_missing_adj_factor_policy() -> str:
    """
    缺失复权因子时策略：
    - skip: 跳过该股票/该次触发
    - raw_fallback: 回退使用未复权价参与计算（必须在输出/日志标注）
    """
    v = str(get_setting("SIGNAL_NOTIFY", "missing_adj_factor_policy", "skip") or "").strip().lower()
    if v in ("skip", "raw_fallback"):
        return v
    return "skip"


def get_all_settings_merged(defaults: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """按 defaults 的键集返回 DB 优先的配置快照。"""
    out: Dict[str, Dict[str, Any]] = {}
    for grp, kv in defaults.items():
        out[grp] = {}
        for k, dv in kv.items():
            out[grp][k] = get_setting(grp, k, dv)
    return out
