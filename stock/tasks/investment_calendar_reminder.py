from __future__ import annotations

import logging
from datetime import datetime, timedelta, time as dtime, date as ddate
from typing import Dict, List, Tuple

from database.database import Database
from Managers.notify_channel import send_notify_fallback, send_notify_to_group

logger = logging.getLogger(__name__)


def _parse_hhmm(s: str) -> dtime:
    raw = (s or "").strip()
    if len(raw) >= 8 and raw[2] == ":":
        raw = raw[:5]
    try:
        return datetime.strptime(raw or "09:00", "%H:%M").time()
    except ValueError:
        return dtime(9, 0)


def _compute_remind_times_for_item(item: dict) -> List[datetime]:
    """
    计算某条日历项的当次提醒时间点列表。
    规则：
    - anchor_dt = date + anchor_time
    - first = anchor_dt - advance_minutes
    - i-th = first + interval_minutes * i
    """
    d_raw = str(item.get("date") or "")[:10]
    try:
        day = datetime.strptime(d_raw, "%Y-%m-%d").date()
    except ValueError:
        return []

    anchor_t = _parse_hhmm(str(item.get("remind_anchor_time") or "09:00"))
    anchor_dt = datetime.combine(day, anchor_t)

    adv = int(item.get("remind_advance_minutes") or 0)
    if adv < 0:
        adv = 0
    if adv > 4320:
        adv = 4320

    cnt = int(item.get("remind_count_per_day") or 1)
    if cnt < 1:
        cnt = 1
    if cnt > 24:
        cnt = 24

    interval = int(item.get("remind_interval_minutes") or 60)
    if interval < 5:
        interval = 5
    if interval > 1440:
        interval = 1440

    first = anchor_dt - timedelta(minutes=adv)
    out: List[datetime] = []
    for i in range(cnt):
        out.append(first + timedelta(minutes=interval * i))
    return out


def _pick_group_id(reminder_group: str) -> int | None:
    """
    当前实现：若 reminder_group 可解析为整数，视为 group_id；
    否则返回 None 走 fallback。
    """
    g = (reminder_group or "").strip()
    if not g:
        return None
    try:
        return int(g)
    except Exception:
        return None


def run_investment_calendar_reminder_job(
    *,
    lookback_seconds: int = 90,
    ahead_seconds: int = 5,
) -> Dict[str, int]:
    """
    定时扫描投资日历提醒并触发发送。

    - lookback_seconds：回看窗口（防止调度抖动错过）
    - ahead_seconds：提前窗口（容忍轻微延迟）
    """
    now = datetime.now()
    win_start = now - timedelta(seconds=int(lookback_seconds))
    win_end = now + timedelta(seconds=int(ahead_seconds))

    # advance 最大 72h，因此至少覆盖 [now-3d, now+3d]
    start_day: ddate = (now - timedelta(days=3)).date()
    end_day: ddate = (now + timedelta(days=3)).date()

    db = Database.Create()
    try:
        db.ensure_investment_calendar_reminder_log_tables()

        # 找出涉及的 user_id 列表（避免全表扫描过大，但这里先用范围查询再在内存分组）
        rows = db.fetch_all(
            '''SELECT id, user_id, date, content, reminder_group, reminder_message,
                      remind_anchor_time, remind_advance_minutes, remind_count_per_day, remind_interval_minutes
               FROM investment_calendar_item
               WHERE date >= %s AND date <= %s
               ORDER BY date ASC, id ASC''',
            (start_day.isoformat(), end_day.isoformat()),
        ) or []

        sent = 0
        due = 0
        skipped = 0

        for it in rows:
            times = _compute_remind_times_for_item(it)
            if not times:
                continue
            for t in times:
                if t < win_start or t > win_end:
                    continue
                due += 1
                remind_at = t.strftime("%Y-%m-%d %H:%M:%S")
                uid = int(it.get("user_id"))
                iid = int(it.get("id"))
                if db.has_investment_calendar_reminded(uid, iid, remind_at):
                    skipped += 1
                    continue

                msg_lines: List[str] = []
                msg_lines.append("【投资日历提醒】")
                msg_lines.append(f"日期：{str(it.get('date') or '')[:10]}")
                msg_lines.append(f"提醒时间：{remind_at}")
                content = str(it.get("content") or "").strip()
                if content:
                    msg_lines.append(f"内容：{content}")
                rg = str(it.get("reminder_group") or "").strip()
                rm = str(it.get("reminder_message") or "").strip()
                if rm:
                    msg_lines.append(f"提醒：{rm}")
                text = "\n".join(msg_lines)

                gid = _pick_group_id(rg)
                try:
                    if gid is None:
                        send_notify_fallback(text)
                    else:
                        send_notify_to_group(gid, text)
                except Exception as e:
                    # 发送失败也记录日志会导致“吞掉一次提醒”；这里选择不落库，等待下次重试
                    logger.error("投资日历提醒发送失败 item_id=%s remind_at=%s: %s", iid, remind_at, e, exc_info=True)
                    continue

                db.mark_investment_calendar_reminded(uid, iid, remind_at)
                sent += 1

        return {"due": due, "sent": sent, "skipped": skipped}
    finally:
        db.close()

