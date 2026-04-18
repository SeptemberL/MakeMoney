"""
每日收盘后涨停复盘（17:00+ 离线任务）。

输出字段（最小集）：
- 连续涨停天数
- 首次涨停时间
- 最终封板时间（最后一次回到涨停后直到收盘不再打开）
- 首次涨停时换手率
- 收盘换手率

说明：
- 日线集合与收盘换手率：优先使用 Tushare（pro.daily + pro.daily_basic）。
- 分钟数据：优先使用 AkShare 分钟K（东财），若缺失则输出 partial。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LimitUpReportRow:
    trade_date: str  # YYYY-MM-DD
    code: str  # 6-digit
    name: str = ""
    consecutive_limitup_days: int = 1

    first_limitup_time: Optional[str] = None  # ISO-like string or HH:MM
    final_seal_time: Optional[str] = None

    turnover_at_first_limitup: Optional[float] = None  # %
    turnover_eod: Optional[float] = None  # %

    status: str = "ok"  # ok | partial | error
    reason: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _fmt_trade_date(s: str) -> str:
    s = (s or "").strip()
    if not s:
        raise ValueError("trade_date 不能为空")
    if "-" in s:
        # YYYY-MM-DD -> YYYYMMDD
        return s.replace("-", "")
    return s


def _fmt_trade_date_dash(s: str) -> str:
    s = _fmt_trade_date(s)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _get_tushare_pro(cfg: Config):
    try:
        import tushare as ts
    except ImportError as e:
        raise RuntimeError("tushare 未安装，请 pip install tushare") from e

    token = cfg.get("TUSHARE", "TOKEN")
    if not token or token == "your-tushare-token-here":
        raise RuntimeError("未配置 Tushare Token，请在 config.ini [TUSHARE] 中设置 TOKEN")
    return ts.pro_api(token)


def _pick_latest_trade_date(pro, *, max_back_days: int = 5) -> str:
    """返回 YYYYMMDD。"""
    today = datetime.now()
    for i in range(0, max_back_days):
        d = (today - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = pro.daily(trade_date=d)
            if df is not None and not df.empty:
                return d
        except Exception:
            continue
    raise RuntimeError("无法确定最近交易日（Tushare daily 近期无数据）")


def _limit_up_price_a_share(pre_close: float) -> float:
    # 首版按主板 10% 近似，不覆盖 ST / 科创 / 创业 / 北交所等差异制度
    return round(float(pre_close) * 1.10 + 1e-9, 2)


def _is_limit_up_close(close: float, limit_up_price: float) -> bool:
    return close >= limit_up_price - 1e-6


def compute_consecutive_limitup_days(
    pro,
    *,
    ts_code: str,
    trade_date: str,
    max_lookback_days: int = 60,
) -> int:
    """
    连板天数：按交易日向前回溯连续“收盘涨停”天数。

    trade_date: YYYYMMDD
    """
    d = _fmt_trade_date(trade_date)
    end_dt = datetime.strptime(d, "%Y%m%d")
    start_dt = end_dt - timedelta(days=max_lookback_days)
    start = start_dt.strftime("%Y%m%d")

    try:
        df = pro.daily(ts_code=ts_code, start_date=start, end_date=d)
    except Exception as e:
        logger.warning("Tushare pro.daily 回溯失败: %s %s", ts_code, e)
        return 1

    if df is None or df.empty:
        return 1

    # Tushare daily 默认按 trade_date 倒序
    df = df.copy()
    df["trade_date"] = df["trade_date"].astype(str)

    cnt = 0
    for _, r in df.iterrows():
        pre_close = float(r.get("pre_close") or 0.0)
        close = float(r.get("close") or 0.0)
        if pre_close <= 0 or close <= 0:
            break
        lup = _limit_up_price_a_share(pre_close)
        if _is_limit_up_close(close, lup):
            cnt += 1
        else:
            break

    return max(cnt, 1)


def fetch_limitup_universe_daily(
    *,
    trade_date: Optional[str] = None,
    config_obj: Optional[Config] = None,
) -> Tuple[str, pd.DataFrame]:
    """
    获取当日涨停股票集合（以收盘是否涨停为准），并补齐收盘换手率。

    Returns:
        (trade_date_yyyymmdd, df)
        df columns (minimum):
          - ts_code, close, pre_close, limit_up_price
          - turnover_rate (EOD)
    """
    cfg = config_obj or Config()

    # 1) 首选 Tushare（更稳定的“当日涨停集合”定义 + daily_basic）
    try:
        pro = _get_tushare_pro(cfg)
        d = _fmt_trade_date(trade_date) if trade_date else _pick_latest_trade_date(pro)
        daily = pro.daily(trade_date=d)
        if daily is None or daily.empty:
            raise RuntimeError(f"{d} 无日线数据")

        daily_basic = None
        try:
            daily_basic = pro.daily_basic(trade_date=d)
        except Exception as e:
            logger.warning("Tushare daily_basic 获取失败，将无法输出收盘换手率: %s", e)
            daily_basic = None

        basic_map: Dict[str, Dict[str, Any]] = {}
        if daily_basic is not None and not daily_basic.empty:
            for _, rr in daily_basic.iterrows():
                ts_code = str(rr.get("ts_code") or "").strip()
                if ts_code:
                    basic_map[ts_code] = rr.to_dict()

        rows: List[Dict[str, Any]] = []
        for _, rr in daily.iterrows():
            ts_code = str(rr.get("ts_code") or "").strip()
            if not ts_code:
                continue
            pre_close = float(rr.get("pre_close") or 0.0)
            close = float(rr.get("close") or 0.0)
            if pre_close <= 0 or close <= 0:
                continue
            lup = _limit_up_price_a_share(pre_close)
            if not _is_limit_up_close(close, lup):
                continue

            b = basic_map.get(ts_code, {})
            rows.append(
                {
                    "ts_code": ts_code,
                    "close": close,
                    "pre_close": pre_close,
                    "limit_up_price": lup,
                    "turnover_rate": (
                        float(b.get("turnover_rate")) if b.get("turnover_rate") is not None else None
                    ),
                    "float_share": (float(b.get("float_share")) if b.get("float_share") is not None else None),
                    "name": "",
                }
            )
        return d, pd.DataFrame(rows)
    except Exception as e:
        logger.warning("Tushare 不可用，降级到 AkShare（仅已跟踪股票）: %s", e)

    # 2) 降级：AkShare（只对已跟踪股票做日线判断，确保“输出验证”可跑通）
    try:
        import akshare as ak
    except ImportError as e:
        raise RuntimeError("akshare 未安装，且 tushare 不可用，无法生成涨停集合") from e

    from stock_list_manager import StockListManager

    mgr = StockListManager()
    # 降级模式下避免扫描全库表（可能非常慢且不可控），只使用显式启用/自选的股票列表。
    tracked = mgr.get_active_stocks() or []
    if not tracked:
        raise RuntimeError("无已跟踪股票（stock_list 为空），无法用 AkShare 生成涨停集合")

    max_codes = 200
    if len(tracked) > max_codes:
        tracked = tracked[:max_codes]

    # trade_date 为空时：用“今天”作为 end_date，后续以每只股票的最后一条为准，
    # 并用出现频率最高的日期作为本次 trade_date。
    end_yyyymmdd = _fmt_trade_date(trade_date) if trade_date else datetime.now().strftime("%Y%m%d")
    end_dash = _fmt_trade_date_dash(end_yyyymmdd)
    start_dash = _fmt_trade_date_dash((datetime.strptime(end_yyyymmdd, "%Y%m%d") - timedelta(days=10)).strftime("%Y%m%d"))

    per_stock_last: List[Dict[str, Any]] = []
    last_dates: List[str] = []
    for s in tracked:
        code = (s.get("code") if isinstance(s, dict) else None) or ""
        code = str(code).strip()
        if not code:
            continue
        try:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_dash.replace("-", ""), end_date=end_yyyymmdd, adjust="")
            if df is None or df.empty:
                continue
            df = df.rename(
                columns={
                    "日期": "trade_date",
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                    "成交量": "volume",
                    "成交额": "amount",
                    "换手率": "turnover_rate",
                }
            )
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.sort_values("trade_date")
            last = df.iloc[-1].to_dict()
            last_dt = pd.to_datetime(last.get("trade_date")).strftime("%Y%m%d")
            last_dates.append(last_dt)
            per_stock_last.append(
                {
                    "code": code,
                    "name": str(s.get("name") or "") if isinstance(s, dict) else "",
                    "trade_date": last_dt,
                    "close": float(last.get("close") or 0.0),
                    "pre_close": float(df.iloc[-2].get("close") if len(df) >= 2 else 0.0),
                    "turnover_rate": float(last.get("turnover_rate")) if last.get("turnover_rate") is not None else None,
                }
            )
        except Exception:
            continue

    if not per_stock_last:
        raise RuntimeError("AkShare 日线获取失败（已跟踪股票均无数据）")

    # 取出现次数最多的日期作为 trade_date
    trade_date_pick = max(set(last_dates), key=last_dates.count)

    rows: List[Dict[str, Any]] = []
    for r in per_stock_last:
        if str(r.get("trade_date")) != trade_date_pick:
            continue
        pre_close = float(r.get("pre_close") or 0.0)
        close = float(r.get("close") or 0.0)
        if pre_close <= 0 or close <= 0:
            continue
        lup = _limit_up_price_a_share(pre_close)
        if not _is_limit_up_close(close, lup):
            continue
        rows.append(
            {
                "ts_code": f"{str(r.get('code')).zfill(6)}.UNKNOWN",
                "close": close,
                "pre_close": pre_close,
                "limit_up_price": lup,
                "turnover_rate": r.get("turnover_rate"),
                "float_share": None,
                "name": r.get("name") or "",
            }
        )

    return trade_date_pick, pd.DataFrame(rows)


def _read_time_col(df: pd.DataFrame) -> Optional[str]:
    for c in ("时间", "time", "datetime", "日期时间", "date", "day"):
        if c in df.columns:
            return c
    return None


def _read_price_col(df: pd.DataFrame) -> Optional[str]:
    for c in ("收盘", "close", "最新价", "price"):
        if c in df.columns:
            return c
    return None


def _read_turnover_rate_col(df: pd.DataFrame) -> Optional[str]:
    for c in ("换手率", "turnover_rate"):
        if c in df.columns:
            return c
    return None


def _read_volume_col(df: pd.DataFrame) -> Optional[str]:
    for c in ("成交量", "volume", "vol"):
        if c in df.columns:
            return c
    return None


def fetch_minute_bars_akshare(code: str, trade_date: str) -> Optional[pd.DataFrame]:
    """
    拉取分钟K（优先东财）。返回 DataFrame 或 None。

    备注：AkShare API 在不同版本函数名/参数可能有差异，这里做多分支兜底。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare 未安装，无法获取分钟数据")
        return None

    d_dash = _fmt_trade_date_dash(trade_date)

    # 常见：stock_zh_a_hist_min_em(symbol="000001", start_date="2024-01-01", end_date="2024-01-01", period="1")
    for call in (
        ("stock_zh_a_hist_min_em", dict(symbol=code, start_date=d_dash, end_date=d_dash, period="1", adjust="")),
        ("stock_zh_a_hist_min_em", dict(symbol=code, start_date=d_dash, end_date=d_dash, period="1")),
    ):
        fn_name, kwargs = call
        fn = getattr(ak, fn_name, None)
        if not fn:
            continue
        try:
            df = fn(**kwargs)
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
        except Exception as e:
            logger.debug("akshare %s 调用失败: %s", fn_name, e)
            continue

    logger.warning("分钟数据获取失败: code=%s trade_date=%s", code, trade_date)
    return None


def _normalize_time_str(v: str) -> str:
    """
    AkShare 分钟K常见格式：
    - 2026-03-30 09:31:00
    - 2026-03-30 09:31
    - 09:31:00
    - 09:31
    统一输出 HH:MM:SS（不带日期），便于展示与对齐。
    """
    s = (v or "").strip()
    if not s:
        return s
    if " " in s:
        s = s.split(" ", 1)[1].strip()
    if len(s) == 5:
        return s + ":00"
    return s


def compute_first_limitup_and_final_seal(
    minute_df: pd.DataFrame, *, limit_up_price: float
) -> Tuple[Optional[str], Optional[str]]:
    time_col = _read_time_col(minute_df)
    price_col = _read_price_col(minute_df)
    if not time_col or not price_col:
        return None, None

    s_price = pd.to_numeric(minute_df[price_col], errors="coerce").fillna(0.0)
    s_time = minute_df[time_col].astype(str)

    at_up = s_price >= (float(limit_up_price) - 1e-6)
    if not bool(at_up.any()):
        return None, None

    first_idx = at_up[at_up].index[0]
    first_time = _normalize_time_str(str(s_time.loc[first_idx]))

    # 最终封板：最后一次触板后到收盘都不再低于涨停价
    true_indices = at_up[at_up].index.tolist()
    final_seal_time = None
    for idx in reversed(true_indices):
        after = s_price.loc[idx:]
        if bool((after < (float(limit_up_price) - 1e-6)).any()):
            continue
        final_seal_time = _normalize_time_str(str(s_time.loc[idx]))
        break

    return first_time, final_seal_time


def derive_turnover_rate_from_volume(
    minute_df: pd.DataFrame, *, float_share_10k: Optional[float]
) -> Optional[pd.Series]:
    """
    由分钟累计成交量推导换手率序列（%）。
    tushare daily_basic.float_share 单位：万股（常见约定）。
    """
    if not float_share_10k or float_share_10k <= 0:
        return None
    vol_col = _read_volume_col(minute_df)
    if not vol_col:
        return None
    vol = pd.to_numeric(minute_df[vol_col], errors="coerce")
    if vol is None:
        return None

    # 常见分钟成交量单位不统一：这里按“股”处理会有偏差；但在缺失分钟换手率时提供可用近似。
    # float_share_10k（万股）-> 股
    float_shares = float(float_share_10k) * 10000.0
    cum = vol.cumsum().fillna(method="ffill").fillna(0.0)
    return (cum / float_shares) * 100.0


def compute_limitup_report_for_date(
    *,
    trade_date: Optional[str] = None,
    config_obj: Optional[Config] = None,
) -> Dict[str, Any]:
    cfg = config_obj or Config()
    pro = None
    try:
        pro = _get_tushare_pro(cfg)
    except Exception:
        pro = None

    d, universe = fetch_limitup_universe_daily(trade_date=trade_date, config_obj=cfg)
    d_dash = _fmt_trade_date_dash(d)

    generated_at = datetime.now().isoformat(timespec="seconds")
    rows: List[LimitUpReportRow] = []

    for _, r in universe.iterrows():
        ts_code = str(r.get("ts_code") or "").strip()
        code = ts_code.split(".")[0] if ts_code else ""
        if not code:
            continue

        limit_up_price = float(r.get("limit_up_price") or 0.0)
        turnover_eod = r.get("turnover_rate")
        float_share = r.get("float_share")
        consecutive_days = 1
        if pro is not None and ts_code and "." in ts_code:
            consecutive_days = compute_consecutive_limitup_days(pro, ts_code=ts_code, trade_date=d)

        minute_df = fetch_minute_bars_akshare(code, d)
        if minute_df is None or minute_df.empty:
            rows.append(
                LimitUpReportRow(
                    trade_date=d_dash,
                    code=code,
                    name=str(r.get("name") or ""),
                    consecutive_limitup_days=consecutive_days,
                    first_limitup_time=None,
                    final_seal_time=None,
                    turnover_at_first_limitup=None,
                    turnover_eod=float(turnover_eod) if turnover_eod is not None else None,
                    status="partial",
                    reason="missing_minute_data",
                    generated_at=generated_at,
                )
            )
            continue

        first_time, final_time = compute_first_limitup_and_final_seal(minute_df, limit_up_price=limit_up_price)

        tr_col = _read_turnover_rate_col(minute_df)
        derived = None
        if not tr_col:
            derived = derive_turnover_rate_from_volume(minute_df, float_share_10k=float(float_share) if float_share is not None else None)

        turnover_first = None
        if first_time:
            time_col = _read_time_col(minute_df)
            if time_col:
                t_series = minute_df[time_col].astype(str).map(_normalize_time_str)
                mask = t_series == str(first_time)
                if bool(mask.any()):
                    idx = minute_df.index[mask][0]
                    if tr_col:
                        try:
                            turnover_first = float(minute_df.loc[idx, tr_col])
                        except Exception:
                            turnover_first = None
                    elif derived is not None:
                        try:
                            turnover_first = float(derived.loc[idx])
                        except Exception:
                            turnover_first = None

        rows.append(
            LimitUpReportRow(
                trade_date=d_dash,
                code=code,
                name=str(r.get("name") or ""),
                consecutive_limitup_days=consecutive_days,
                first_limitup_time=first_time,
                final_seal_time=final_time,
                turnover_at_first_limitup=turnover_first,
                turnover_eod=float(turnover_eod) if turnover_eod is not None else None,
                status="ok" if (first_time and final_time) else "partial",
                reason="" if (first_time and final_time) else "incomplete_intraday_metrics",
                generated_at=generated_at,
            )
        )

    return {
        "success": True,
        "trade_date": d_dash,
        "generated_at": generated_at,
        "count": len(rows),
        "rows": [x.to_dict() for x in rows],
    }


def write_report_json(result: Dict[str, Any], *, base_dir: Optional[Path] = None) -> str:
    bd = base_dir or Path(__file__).resolve().parent.parent / "outputs" / "daily_limitup_report"
    trade_date = (result.get("trade_date") or "").strip() or "unknown-date"
    out_dir = bd / trade_date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(out_path)


def run_daily_limitup_report(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """
    APScheduler 任务入口。
    - trade_date: YYYY-MM-DD 或 YYYYMMDD，可空（默认最近交易日）
    """
    try:
        result = compute_limitup_report_for_date(trade_date=trade_date)
        out_path = write_report_json(result)
        result["output_path"] = out_path
        logger.info("daily_limitup_report 完成: %s rows=%s", result.get("trade_date"), result.get("count"))
        return result
    except Exception as e:
        logger.error("daily_limitup_report 失败: %s", e, exc_info=True)
        return {"success": False, "message": str(e)}

