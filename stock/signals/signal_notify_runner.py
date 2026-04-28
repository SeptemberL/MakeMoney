from __future__ import annotations

import json
import logging
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple

from Managers.feishu_bot import feishu_signal_send_batch
from Managers.notify_channel import send_notify_to_group
from Managers.runtime_settings import get_signal_missing_adj_factor_policy, get_signal_price_source
from database.database import Database
from stocks.stock_basic_lookup import lookup_stock_name_from_basic
from tasks.signal_state_flush import buffer_signal_rule_state
from signals.signal_notify_system import (
    SignalConfig,
    SignalMessageTemplate,
    SendType,
    SingleType,
    create_signal_instance,
)

logger = logging.getLogger(__name__)


def _adj_factor_to_float(row: Optional[dict]) -> Optional[float]:
    if not row:
        return None
    v = row.get("adj_factor")
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _convert_raw_price_to_qfq(*, db: Database, stock_code: str, raw_price: float) -> Optional[float]:
    """
    将“未复权价”转换为前复权价。
    这里优先使用 adj_factor 最新一条（通常覆盖最近交易日/最近同步日）。
    """
    row = db.get_latest_adj_factor_row(stock_code)
    af = _adj_factor_to_float(row)
    if af is None:
        return None
    try:
        return float(raw_price) * float(af)
    except Exception:
        return None


def _eval_and_persist_rules(
    *,
    db: Database,
    rules: List[dict],
    prices: Dict[str, float],
    state_map: Dict[int, str],
    price_meta: Optional[Dict[str, dict]] = None,
) -> Tuple[int, int, List[str]]:
    """
    在内存中执行 rules 的触发计算，并持久化 state。
    返回：(scanned_rules, triggered_messages, messages)
    """
    triggered = 0
    scanned = 0
    messages: List[str] = []

    for r in rules or []:
        sc = str((r or {}).get("stock_code") or "").strip()
        if not sc or sc not in prices:
            continue

        scanned += 1
        try:
            if price_meta and sc in price_meta:
                m = price_meta.get(sc) or {}
                logger.info(
                    "signal_price_meta: stock=%s data_source=%s adjustment=%s factor_coverage=%s",
                    sc,
                    m.get("data_source"),
                    m.get("adjustment"),
                    m.get("factor_coverage"),
                )
            rule_id = int(r.get("id"))
            runtime_state = json.loads(state_map.get(rule_id, "{}") or "{}")
            stock_name = r.get("stock_name") or ""
            if not stock_name:
                try:
                    nm = lookup_stock_name_from_basic(db, sc)
                    if nm:
                        stock_name = str(nm).strip()
                        # 顺便写回规则表，后续无需重复查
                        try:
                            db.update_signal_rule(rule_id=rule_id, stock_name=stock_name)
                        except Exception:
                            pass
                except Exception:
                    stock_name = ""

            signal = create_signal_instance(
                SignalConfig(
                    stock_code=sc,
                    stock_name=stock_name,
                    group_ids=json.loads(r.get("group_ids_json") or "[]"),
                    signal_type=SingleType(
                        r.get("signal_type") or SingleType.PRICE_RANGE.value
                    ),
                    params=json.loads(r.get("params_json") or "{}"),
                    message_template=SignalMessageTemplate(
                        template=r.get("message_template") or SignalMessageTemplate().template
                    ),
                    send_type=SendType(r.get("send_type") or SendType.ON_TRIGGER.value),
                    send_interval_seconds=int(r.get("send_interval_seconds") or 0),
                    runtime_state=runtime_state,
                )
            )
            new_messages = signal.update(prices[sc])
            payloads = signal.take_trigger_payloads()
            for idx, msg in enumerate(new_messages):
                tpl_payload = payloads[idx] if idx < len(payloads) else None
                with feishu_signal_send_batch():
                    for gid in signal.config.group_ids:
                        send_notify_to_group(int(gid), msg, feishu_signal_payload=tpl_payload)
                triggered += 1
                messages.append(msg)
            state_json = json.dumps(signal.get_runtime_state(), ensure_ascii=False)
            # 可选：写入缓冲（Redis），异步批量落库；失败则回退为同步落库
            if not buffer_signal_rule_state(rule_id, state_json):
                db.upsert_signal_rule_state(rule_id=rule_id, state_json=state_json)
        except Exception as e:
            logger.warning(
                "执行 signal_rule(id=%s, stock=%s) 失败，已跳过: %s", r.get("id"), sc, e
            )

    return scanned, triggered, messages


def _is_cn_stock_trading_time(now: Optional[datetime] = None) -> bool:
    """A 股交易时段（简单版）：工作日 09:30-11:30、13:00-15:00。"""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    am = time(9, 30) <= t <= time(11, 30)
    pm = time(13, 0) <= t <= time(15, 0)
    return am or pm


def run_signal_notify_for_stock(stock_code: str, price: float) -> List[str]:
    """按 stock_code + 最新价执行一次信号检查，并持久化触发状态。price 视为未复权价，将用 adj_factor 转为前复权。"""
    db = Database.Create()
    try:
        missing_policy = get_signal_missing_adj_factor_policy()
        qfq_price = _convert_raw_price_to_qfq(db=db, stock_code=stock_code, raw_price=float(price))
        if qfq_price is None:
            if missing_policy != "raw_fallback":
                logger.info("run_signal_notify_for_stock: skip stock=%s reason=missing_adj_factor", stock_code)
                return []
            qfq_price = float(price)
        rows = db.get_signal_rules(stock_code=stock_code, only_active=True)
        rule_ids = [int(r.get("id")) for r in (rows or []) if r.get("id") is not None]
        state_map = db.get_signal_rule_states(rule_ids)

        _, _, messages = _eval_and_persist_rules(
            db=db,
            rules=rows or [],
            prices={stock_code: float(qfq_price)},
            state_map=state_map,
            price_meta={
                stock_code: {
                    "data_source": "realtime_input",
                    "adjustment": "qfq" if missing_policy != "raw_fallback" else "raw_fallback",
                    "factor_coverage": "unknown" if missing_policy != "raw_fallback" else "missing",
                }
            },
        )
        return messages
    finally:
        db.close()


def _load_active_signal_rules() -> Tuple[List[dict], Dict[int, str]]:
    """
    只从“已注册/已启用 single(signal_rule)”收集待检测对象：
    - 返回 active_rules（行 dict 列表）
    - 返回 state_map：{rule_id: state_json_str}
    """
    db = Database.Create()
    try:
        rules = db.get_signal_rules(stock_code=None, only_active=True) or []
        rule_ids = [int(r.get("id")) for r in rules if r.get("id") is not None]
        state_map = db.get_signal_rule_states(rule_ids)
        return rules, state_map
    finally:
        db.close()


def _fetch_realtime_prices(stock_codes: List[str]) -> Dict[str, float]:
    """批量获取实时价（尽力而为）；返回 {stock_code: price}。"""
    out: Dict[str, float] = {}
    if not stock_codes:
        return out

    try:
        from stocks.stock_quote_tencent import fetch_quotes
    except Exception:
        return out

    quotes = fetch_quotes(stock_codes) or {}
    for sc in stock_codes:
        quote = None
        if sc in quotes:
            quote = quotes.get(sc)
        if quote is None:
            base = sc.split(".", 1)[0]
            for key in (
                base,
                f"sh{base}",
                f"sz{base}",
                f"bj{base}",
                f"hk{base.zfill(5)}",
            ):
                if key in quotes:
                    quote = quotes.get(key)
                    break
        if quote is None or getattr(quote, "now", None) is None:
            continue
        try:
            out[sc] = float(quote.now)
        except Exception:
            continue
    return out


def _fetch_db_latest_close_qfq_prices(stock_codes: List[str]) -> Dict[str, float]:
    """
    从数据库读取每只股票最新交易日 raw close，并使用 adj_factor 表转换为前复权价。

    缺失复权因子时：该股票不返回价格（相当于该次扫描标记为数据不足并跳过）。
    """
    out: Dict[str, float] = {}
    if not stock_codes:
        return out

    db = Database.Create()
    try:
        latest_map = db.get_latest_daily_close_map(stock_codes)
        if not latest_map:
            return out

        # 按 trade_date 分组批量查 adj_factor，减少往返
        by_date: Dict[str, List[str]] = {}
        for sc, v in latest_map.items():
            td = str(v.get("trade_date") or "").strip()
            if not td:
                continue
            by_date.setdefault(td, []).append(sc)

        for td, codes in by_date.items():
            rows = db.get_adj_factors(stock_codes=codes, start_trade_date=td, end_trade_date=td)
            factor_map: Dict[str, float] = {}
            for r in rows or []:
                sc = str(r.get("stock_code") or "").strip()
                if not sc:
                    continue
                try:
                    factor_map[sc] = float(r.get("adj_factor"))
                except Exception:
                    continue

            for sc in codes:
                base = latest_map.get(sc) or {}
                raw_close = base.get("close")
                af = factor_map.get(sc)
                if raw_close is None or af is None:
                    logger.info(
                        "signal_notify_tick: skip stock=%s reason=missing_adj_factor trade_date=%s",
                        sc,
                        td,
                    )
                    continue
                try:
                    out[sc] = float(raw_close) * float(af)
                except Exception:
                    continue

        return out
    finally:
        db.close()


def _fetch_db_latest_close_qfq_prices_with_meta(stock_codes: List[str]) -> Tuple[Dict[str, float], Dict[str, dict], Dict[str, int]]:
    """
    在 _fetch_db_latest_close_qfq_prices 基础上返回：
    - prices: {stock_code: qfq_price}
    - meta: {stock_code: {data_source, adjustment, factor_coverage}}
    - stats: {requested, prices_fetched, missing_adj_factor}
    """
    requested = len(stock_codes or [])
    prices = _fetch_db_latest_close_qfq_prices(stock_codes)
    fetched = len(prices or {})
    # 由于 _fetch_db_latest_close_qfq_prices 会直接跳过缺失因子的股票，这里用 requested-fetched 近似缺失统计
    missing = max(0, requested - fetched)
    meta: Dict[str, dict] = {}
    for sc in prices.keys():
        meta[sc] = {"data_source": "db_latest_close", "adjustment": "qfq", "factor_coverage": "complete"}
    return prices, meta, {"requested": requested, "prices_fetched": fetched, "missing_adj_factor": missing}


def run_signal_notify_tick(*, force: bool = False) -> Dict[str, int]:
    """
    执行一次“全量信号扫描”：
    - force=False：仅交易时间执行
    - force=True：忽略交易时间（用于测试手动触发/启动首轮）
    返回：扫描股票数、触发消息数等统计。
    """
    now = datetime.now()
    if not force and not _is_cn_stock_trading_time(now):
        return {"scanned": 0, "triggered": 0, "skipped_non_trading": 1}

    rules, state_map = _load_active_signal_rules()
    codes: List[str] = sorted(
        {
            str((r or {}).get("stock_code") or "").strip()
            for r in (rules or [])
            if str((r or {}).get("stock_code") or "").strip()
        }
    )
    price_source = get_signal_price_source()
    missing_policy = get_signal_missing_adj_factor_policy()
    price_meta: Dict[str, dict] = {}
    price_stats: Dict[str, int] = {"requested": len(codes), "prices_fetched": 0, "missing_adj_factor": 0}
    if price_source == "realtime_qfq_opt_in":
        # 按需求：直接使用腾讯在线实时价（raw），不做前/后复权转换
        raw_prices = _fetch_realtime_prices(codes)
        prices: Dict[str, float] = {}
        for sc, raw_p in (raw_prices or {}).items():
            try:
                prices[sc] = float(raw_p)
                price_meta[sc] = {
                    "data_source": "tencent_realtime",
                    "adjustment": "raw",
                    "factor_coverage": "n/a",
                }
            except Exception:
                continue
        price_stats["prices_fetched"] = len(prices or {})
    else:
        prices, price_meta, price_stats = _fetch_db_latest_close_qfq_prices_with_meta(codes)
        if missing_policy == "raw_fallback" and price_stats.get("missing_adj_factor"):
            # 将缺失因子的股票以 raw close 回退加入 prices（不保证与前复权可比，但用于“不中断”扫描）
            db = Database.Create()
            try:
                latest_map = db.get_latest_daily_close_map(codes)
            finally:
                db.close()
            for sc, v in (latest_map or {}).items():
                if sc in prices:
                    continue
                raw_close = v.get("close")
                if raw_close is None:
                    continue
                try:
                    prices[sc] = float(raw_close)
                    price_meta[sc] = {"data_source": "db_latest_close", "adjustment": "raw_fallback", "factor_coverage": "missing"}
                except Exception:
                    continue
            price_stats["prices_fetched"] = len(prices or {})
    triggered = 0
    scanned = 0

    type_counter: Dict[str, int] = {}
    for r in rules or []:
        st = str((r or {}).get("signal_type") or "").strip() or "unknown"
        type_counter[st] = type_counter.get(st, 0) + 1
    logger.info(
        "signal_notify_tick: active_rules=%s stocks=%s prices_fetched=%s signal_types=%s",
        len(rules or []),
        len(codes),
        len(prices or {}),
        type_counter,
    )

    if not rules or not prices:
        return {"scanned": 0, "triggered": 0, "skipped_non_trading": 0}

    db = Database.Create()
    try:
        scanned, triggered, _ = _eval_and_persist_rules(
            db=db,
            rules=rules or [],
            prices=prices,
            state_map=state_map,
            price_meta=price_meta,
        )
    finally:
        db.close()

    logger.info("signal_notify_tick: scanned=%s triggered=%s", scanned, triggered)
    return {
        "scanned": scanned,
        "triggered": triggered,
        "skipped_non_trading": 0,
        "price_source": price_source,
        "price_requested": int(price_stats.get("requested") or 0),
        "price_fetched": int(price_stats.get("prices_fetched") or 0),
        "missing_adj_factor": int(price_stats.get("missing_adj_factor") or 0),
        "missing_adj_factor_policy": missing_policy,
    }

