"""
复权因子（adj_factor）同步：

- 增量同步：按 stock_code 从数据库中已有的最大 trade_date 之后拉取并 upsert
- 日更检查：在某股票日线写入后，检查该 trade_date 的 adj_factor 是否变化，变化则写入

数据源优先级：
1) AKShare：通过未复权 close 与前复权/后复权 close 推导出当日 qfq_factor/hfq_factor≈(qfq|hfq)_close/raw_close
2) Tushare：直接读取 pro.adj_factor（仅 qfq_factor；hfq_factor 缺失时可为空）
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd

from config import Config
from database.database import Database
from stock_list_manager import StockListManager

logger = logging.getLogger(__name__)


def _to_ts_code(code: str, market: Optional[str]) -> str:
    c = (code or "").strip()
    m = (market or "").strip().upper()
    if not c:
        return ""
    if "." in c:
        return c
    if m not in ("SH", "SZ"):
        # 回退：按常见规则推断
        m = "SZ" if c.startswith(("00", "30")) else "SH"
    return f"{c}.{m}"


def _ensure_tushare_pro(cfg: Config):
    try:
        import tushare as ts
    except ImportError as e:
        raise ImportError("tushare 未安装，请运行 pip install tushare") from e
    token = cfg.get("TUSHARE", "TOKEN")
    if not token or token == "your-tushare-token-here":
        raise ValueError("未配置 Tushare Token，请在 config.ini [TUSHARE] 中设置 TOKEN")
    return ts.pro_api(token)


def _df_empty(df) -> bool:
    return df is None or (hasattr(df, "empty") and df.empty)


def _try_get_factors_from_akshare_on_trade_date(
    stock_code: str, trade_date: str
) -> Optional[Dict[str, float]]:
    """AKShare 单日推导：qfq_factor/hfq_factor≈(qfq|hfq)_close/raw_close；失败返回 None。"""
    try:
        import akshare as ak
    except Exception:
        return None

    code = (stock_code or "").strip()
    td = (trade_date or "").strip()
    if not code or len(td) != 10:
        return None
    td_yyyymmdd = td.replace("-", "")

    try:
        raw_df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=td_yyyymmdd,
            end_date=td_yyyymmdd,
            adjust="",
        )
        qfq_df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=td_yyyymmdd,
            end_date=td_yyyymmdd,
            adjust="qfq",
        )
        hfq_df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=td_yyyymmdd,
            end_date=td_yyyymmdd,
            adjust="hfq",
        )
    except Exception:
        return None

    if _df_empty(raw_df) or _df_empty(qfq_df) or _df_empty(hfq_df):
        return None

    try:
        raw_close = pd.to_numeric(raw_df.iloc[0].get("收盘"), errors="coerce")
        qfq_close = pd.to_numeric(qfq_df.iloc[0].get("收盘"), errors="coerce")
        hfq_close = pd.to_numeric(hfq_df.iloc[0].get("收盘"), errors="coerce")
        if pd.isna(raw_close) or pd.isna(qfq_close) or float(raw_close) == 0.0:
            return None
        if pd.isna(hfq_close):
            return None
        return {
            "qfq_factor": float(qfq_close) / float(raw_close),
            "hfq_factor": float(hfq_close) / float(raw_close),
        }
    except Exception:
        return None


def _try_fetch_factors_df_from_akshare(
    stock_code: str, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """
    AKShare 批量推导区间因子：
    返回 DataFrame[trade_date(YYYY-MM-DD), qfq_factor, hfq_factor]，失败返回 None。
    start_date/end_date: YYYYMMDD
    """
    try:
        import akshare as ak
    except Exception:
        return None

    code = (stock_code or "").strip()
    if not code:
        return None

    try:
        raw_df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
        qfq_df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        hfq_df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="hfq",
        )
    except Exception:
        return None

    if _df_empty(raw_df) or _df_empty(qfq_df) or _df_empty(hfq_df):
        return None

    try:
        a = raw_df[["日期", "收盘"]].copy()
        b = qfq_df[["日期", "收盘"]].copy()
        c = hfq_df[["日期", "收盘"]].copy()
        a.columns = ["trade_date", "raw_close"]
        b.columns = ["trade_date", "qfq_close"]
        c.columns = ["trade_date", "hfq_close"]
        a["raw_close"] = pd.to_numeric(a["raw_close"], errors="coerce")
        b["qfq_close"] = pd.to_numeric(b["qfq_close"], errors="coerce")
        c["hfq_close"] = pd.to_numeric(c["hfq_close"], errors="coerce")
        m = pd.merge(a, b, on="trade_date", how="inner")
        m = pd.merge(m, c, on="trade_date", how="inner")
        m = m.dropna(subset=["raw_close", "qfq_close"])
        m = m[m["raw_close"] != 0]
        if m.empty:
            return None
        m["qfq_factor"] = m["qfq_close"].astype(float) / m["raw_close"].astype(float)
        m["hfq_factor"] = m["hfq_close"].astype(float) / m["raw_close"].astype(float)
        m["trade_date"] = pd.to_datetime(m["trade_date"]).dt.strftime("%Y-%m-%d")
        return m[["trade_date", "qfq_factor", "hfq_factor"]]
    except Exception:
        return None

def upsert_adj_factor_if_changed(
    stock_code: str,
    trade_date: str,
    qfq_factor: float,
    hfq_factor: Optional[float] = None,
    *,
    db: Optional[Database] = None,
) -> bool:
    """
    若该股票该日的 adj_factor 与库里“最新一条”不一致，则写入。
    注意：这里以“最新一条”做变化检测，是为了减少写放大；仍然会对同日 upsert。
    """
    own_db = False
    if db is None:
        db = Database.Create()
        own_db = True
    try:
        db.ensure_adj_factor_tables()
        last = db.get_latest_adj_factor_row(stock_code)
        last_v = None
        if last and (last.get("qfq_factor") is not None or last.get("adj_factor") is not None):
            try:
                last_v = float(last.get("qfq_factor") or last.get("adj_factor"))
            except Exception:
                last_v = None
        af = float(qfq_factor)
        if last_v is not None and abs(last_v - af) < 1e-12:
            return False
        db.upsert_adj_factor(stock_code, trade_date, af, qfq_factor=af, hfq_factor=hfq_factor)
        return True
    finally:
        if own_db:
            db.close()


def sync_adj_factor_for_stock_incremental(
    stock_code: str,
    market: Optional[str] = None,
    *,
    config_obj: Optional[Config] = None,
    db: Optional[Database] = None,
    sleep_seconds: float = 0.0,
) -> Dict[str, Any]:
    """按数据库已有最大日期增量同步单只股票的 adj_factor。"""
    cfg = config_obj or Config()
    ts_code = _to_ts_code(stock_code, market)
    if not ts_code:
        return {"success": False, "message": "stock_code 为空", "inserted": 0}

    own_db = False
    if db is None:
        db = Database.Create()
        own_db = True

    try:
        db.ensure_adj_factor_tables()
        max_td = db.get_max_adj_factor_trade_date(stock_code)
        if max_td:
            start_date = (pd.Timestamp(max_td) + pd.Timedelta(days=1)).strftime("%Y%m%d")
        else:
            # 默认回溯 10 年，避免一次性过大；后续可以通过 API 传参扩展
            start_date = (datetime.now() - timedelta(days=3650)).strftime("%Y%m%d")
        end_date = datetime.now().strftime("%Y%m%d")

        # 优先 AKShare（同时拉 qfq/hfq）
        df = _try_fetch_factors_df_from_akshare(stock_code, start_date, end_date)
        source = "akshare"

        # fallback Tushare
        if _df_empty(df):
            source = "tushare"
            pro = _ensure_tushare_pro(cfg)
            for attempt in range(3):
                try:
                    df = pro.adj_factor(ts_code=ts_code, start_date=start_date, end_date=end_date)
                    break
                except Exception as e:
                    logger.warning("adj_factor 拉取失败: %s attempt=%d err=%s", ts_code, attempt + 1, e)
                    if attempt < 2:
                        time.sleep(2)
        if _df_empty(df):
            return {"success": True, "message": f"{ts_code} 无新增复权因子数据", "inserted": 0}

        inserted = 0
        if source == "akshare":
            df = df.copy()
            for _, r in df.iterrows():
                td_fmt = str(r.get("trade_date") or "").strip()[:10]
                qfq = r.get("qfq_factor")
                hfq = r.get("hfq_factor")
                if not td_fmt or qfq is None or pd.isna(qfq):
                    continue
                db.upsert_adj_factor(stock_code, td_fmt, float(qfq), qfq_factor=float(qfq), hfq_factor=None if hfq is None or pd.isna(hfq) else float(hfq))
                inserted += 1
        else:
            df = df.copy()
            # Tushare: trade_date(YYYYMMDD), adj_factor(float)
            df["trade_date"] = df["trade_date"].astype(str)
            for _, r in df.iterrows():
                td = str(r.get("trade_date") or "").strip()
                if len(td) == 8 and td.isdigit():
                    td_fmt = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                else:
                    continue
                qfq = r.get("adj_factor")
                if qfq is None or pd.isna(qfq):
                    continue
                db.upsert_adj_factor(stock_code, td_fmt, float(qfq), qfq_factor=float(qfq), hfq_factor=None)
                inserted += 1
        if sleep_seconds:
            time.sleep(float(sleep_seconds))
        return {"success": True, "message": f"{ts_code} 增量同步完成（source={source}）", "inserted": inserted}
    finally:
        if own_db:
            db.close()


def sync_adj_factor_for_stock_on_trade_date(
    stock_code: str,
    market: Optional[str],
    trade_date: str,
    *,
    config_obj: Optional[Config] = None,
    db: Optional[Database] = None,
) -> Dict[str, Any]:
    """
    拉取某股票某交易日的 adj_factor，若与库里最新值不同则写入。
    trade_date: YYYY-MM-DD
    """
    cfg = config_obj or Config()
    ts_code = _to_ts_code(stock_code, market)
    if not ts_code:
        return {"success": False, "message": "stock_code 为空", "changed": False}

    td = (trade_date or "").strip()
    if len(td) != 10:
        return {"success": False, "message": "trade_date 格式应为 YYYY-MM-DD", "changed": False}

    # 优先 AKShare
    factors = _try_get_factors_from_akshare_on_trade_date(stock_code, td)
    source = "akshare"

    # fallback Tushare
    if factors is None:
        source = "tushare"
        pro = _ensure_tushare_pro(cfg)
        td_yyyymmdd = td.replace("-", "")
        df = None
        for attempt in range(3):
            try:
                df = pro.adj_factor(ts_code=ts_code, trade_date=td_yyyymmdd)
                break
            except Exception as e:
                logger.warning("adj_factor 拉取失败: %s date=%s attempt=%d err=%s", ts_code, td, attempt + 1, e)
                if attempt < 2:
                    time.sleep(2)
        if _df_empty(df):
            return {"success": True, "message": f"{ts_code} {td} 无复权因子数据", "changed": False}

        r0 = df.iloc[0].to_dict()
        qfq = r0.get("adj_factor")
        if qfq is None or pd.isna(qfq):
            return {"success": True, "message": f"{ts_code} {td} adj_factor 为空", "changed": False}

    own_db = False
    if db is None:
        db = Database.Create()
        own_db = True
    try:
        if source == "akshare":
            changed = upsert_adj_factor_if_changed(
                stock_code,
                td,
                float(factors["qfq_factor"]),
                hfq_factor=float(factors["hfq_factor"]),
                db=db,
            )
        else:
            changed = upsert_adj_factor_if_changed(stock_code, td, float(qfq), hfq_factor=None, db=db)
        return {
            "success": True,
            "message": f"{ts_code} {td} adj_factor={'changed' if changed else 'unchanged'}（source={source}）",
            "changed": changed,
        }
    finally:
        if own_db:
            db.close()


def run_sync_all_tracked_adj_factors(
    *,
    config_obj: Optional[Config] = None,
    sleep_seconds: float = 0.0,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    增量同步当前“已跟踪股票”（stock_list status=1 或已存在 stock_表）的全部复权因子。
    """
    cfg = config_obj or Config()
    mgr = StockListManager()
    stocks = mgr.get_active_stocks() or []
    if not stocks:
        # 回退：沿用 daily_tushare_sync 的扫描逻辑（避免循环 import，这里只提示）
        return {"success": False, "message": "没有已跟踪的股票（stock_list 为空）", "total": 0, "updated": 0}

    total = len(stocks)
    if limit is not None:
        total = min(total, int(limit))
        stocks = stocks[:total]

    db = Database.Create()
    try:
        db.ensure_adj_factor_tables()
        updated = 0
        failed = 0
        for s in stocks:
            code = (s.get("code") if isinstance(s, dict) else None) or ""
            market = (s.get("market") if isinstance(s, dict) else None) or None
            if not code:
                continue
            try:
                # 全量修复：按 stock_ 表的最早/最新日期范围拉取并补齐每日因子
                table_name = Database.stock_table_name_for_code(code)
                if not db.table_exists(table_name):
                    continue
                mm = db.fetch_one(f"SELECT MIN(trade_date) AS min_d, MAX(trade_date) AS max_d FROM {table_name}") or {}
                min_d = str(mm.get("min_d") or "")[:10]
                max_d = str(mm.get("max_d") or "")[:10]
                if not min_d or not max_d:
                    continue

                # 用 AKShare 优先拉取该区间因子；fallback Tushare 仅补 qfq_factor
                start_date = min_d.replace("-", "")
                end_date = max_d.replace("-", "")

                df = _try_fetch_factors_df_from_akshare(code, start_date, end_date)
                source = "akshare"
                if _df_empty(df):
                    source = "tushare"
                    pro = _ensure_tushare_pro(cfg)
                    df = pro.adj_factor(ts_code=_to_ts_code(code, market), start_date=start_date, end_date=end_date)

                inserted = 0
                if source == "akshare":
                    df = df.copy()
                    for _, r0 in df.iterrows():
                        td_fmt = str(r0.get("trade_date") or "").strip()[:10]
                        qfq = r0.get("qfq_factor")
                        hfq = r0.get("hfq_factor")
                        if not td_fmt or qfq is None or pd.isna(qfq):
                            continue
                        db.upsert_adj_factor(
                            code,
                            td_fmt,
                            float(qfq),
                            qfq_factor=float(qfq),
                            hfq_factor=None if hfq is None or pd.isna(hfq) else float(hfq),
                        )
                        inserted += 1
                else:
                    df = df.copy()
                    df["trade_date"] = df["trade_date"].astype(str)
                    for _, r0 in df.iterrows():
                        td = str(r0.get("trade_date") or "").strip()
                        if len(td) == 8 and td.isdigit():
                            td_fmt = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                        else:
                            continue
                        qfq = r0.get("adj_factor")
                        if qfq is None or pd.isna(qfq):
                            continue
                        db.upsert_adj_factor(code, td_fmt, float(qfq), qfq_factor=float(qfq), hfq_factor=None)
                        inserted += 1

                r = {"success": True, "inserted": inserted, "message": f"{code} 全量修复完成（source={source}）"}
                if r.get("success"):
                    if int(r.get("inserted") or 0) > 0:
                        updated += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                logger.warning("增量同步复权因子失败 code=%s err=%s", code, e)
        return {"success": True, "message": "复权因子增量同步完成", "total": total, "updated": updated, "failed": failed}
    finally:
        db.close()

