"""
Tushare 日线（pro.daily，未复权）同步到各股票表；供 HTTP API 与定时任务共用。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from config import Config
from database.database import Database
from stock_list_manager import StockListManager

logger = logging.getLogger(__name__)

_STOCK_TABLE_RE = re.compile(r'^stock_(\d{6})_(SH|SZ)$')

try:
    # 可选：若存在则在日线写入后检查复权因子变化
    from tasks.adj_factor_sync import sync_adj_factor_for_stock_on_trade_date
except Exception:  # pragma: no cover
    sync_adj_factor_for_stock_on_trade_date = None


def _parse_db_datetime(v: Any) -> Optional[datetime]:
    """兼容 SQLite/MySQL 返回的 updated_at 形态（datetime 或 str）。"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    if not s:
        return None
    # 常见：'YYYY-MM-DD HH:MM:SS' 或带小数秒
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    # 兜底：尝试 pandas 解析（避免引入 dateutil 依赖）
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.to_pydatetime()
    except Exception:
        return None


def _already_updated_after_cutoff(
    *,
    db: Database,
    cursor,
    table_name: str,
    trade_date_fmt: str,
    cutoff_dt: datetime,
) -> bool:
    """
    判断某股票表在指定 trade_date 的行是否已在 cutoff_dt 之后更新过。
    - 仅依赖行内 updated_at 字段（SQLite 需在 upsert 时刷新）
    """
    try:
        if db.is_sqlite:
            cursor.execute(
                f"SELECT updated_at FROM {table_name} WHERE trade_date = ? LIMIT 1",
                (trade_date_fmt,),
            )
        else:
            cursor.execute(
                f"SELECT updated_at FROM {table_name} WHERE trade_date = %s LIMIT 1",
                (trade_date_fmt,),
            )
        row = cursor.fetchone()
        if not row:
            return False
        # sqlite cursor 默认返回 tuple；mysql buffered=True 返回 tuple
        updated_at = row.get("updated_at") if isinstance(row, dict) else row[0]
        dt = _parse_db_datetime(updated_at)
        return bool(dt and dt >= cutoff_dt)
    except Exception:
        # 表不存在/字段不存在/查询失败：按“未更新过”处理，避免误跳过
        return False


def get_tracked_stocks_list(manager: StockListManager) -> List[Dict[str, str]]:
    """获取已跟踪的股票列表，优先 stock_list，否则回退到扫描已有的 stock_XXXXXX_XX 表。"""
    active = manager.get_active_stocks()
    if active:
        return active

    db = Database.Create()
    try:
        if db.is_sqlite:
            rows = db.fetch_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'stock_%'")
        else:
            rows = db.fetch_all("SHOW TABLES")

        stocks = []
        for row in rows:
            name = row.get('name') if isinstance(row, dict) and 'name' in row else (list(row.values())[0] if isinstance(row, dict) else row[0])
            m = _STOCK_TABLE_RE.match(str(name))
            if m:
                stocks.append({'code': m.group(1), 'market': m.group(2)})
        if stocks:
            logger.info(f"stock_list 为空，从已有表中发现 {len(stocks)} 只股票")
        return stocks
    except Exception as e:
        logger.warning(f"扫描已有股票表失败: {e}")
        return []
    finally:
        db.close()


def _ts_float(val: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(val):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def run_daily_tushare_sync(
    stock_list_manager: Optional[StockListManager] = None,
    config_obj: Optional[Config] = None,
) -> Dict[str, Any]:
    """
    使用 Tushare pro.daily 拉取当日（或回溯）日线，更新已跟踪股票表。

    Returns:
        供 jsonify 的字典；含可选 ``status_code``（非 200 时 API 层使用）。
    """
    mgr = stock_list_manager or StockListManager()
    cfg = config_obj or Config()

    try:
        import tushare as ts
    except ImportError:
        return {
            'success': False,
            'message': 'tushare 未安装，请运行 pip install tushare',
            'updated_count': 0,
            'total': 0,
            'skipped': 0,
            'failed_count': 0,
            'status_code': 500,
        }

    token = cfg.get('TUSHARE', 'TOKEN')
    if not token or token == 'your-tushare-token-here':
        logger.warning('Tushare 定时/同步跳过：未配置 [TUSHARE] TOKEN')
        return {
            'success': False,
            'message': '未配置 Tushare Token，请在 config.ini [TUSHARE] 中设置 TOKEN',
            'updated_count': 0,
            'total': 0,
            'skipped': 0,
            'failed_count': 0,
            'status_code': 400,
        }

    try:
        pro = ts.pro_api(token)
        now = datetime.now()
        today = now.strftime('%Y%m%d')

        logger.info(f"使用 Tushare 拉取 {today} 日线行情...")

        daily_df = None
        for attempt in range(3):
            try:
                daily_df = pro.daily(trade_date=today)
                break
            except Exception as fetch_err:
                logger.warning(f"Tushare 第 {attempt+1} 次请求失败: {fetch_err}")
                if attempt < 2:
                    time.sleep(2)

        display_date = today
        if daily_df is None or daily_df.empty:
            for days_back in range(1, 5):
                prev = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
                try:
                    daily_df = pro.daily(trade_date=prev)
                    if daily_df is not None and not daily_df.empty:
                        display_date = prev
                        break
                except Exception:
                    continue

        if daily_df is None or daily_df.empty:
            return {
                'success': False,
                'message': f'{today} 暂无行情数据（可能未开盘或数据未更新）',
                'updated_count': 0,
                'total': 0,
                'skipped': 0,
                'failed_count': 0,
            }

        spot_map: Dict[str, Any] = {}
        for _, r in daily_df.iterrows():
            code = str(r['ts_code']).split('.')[0]
            spot_map[code] = r
        logger.info(f"Tushare 获取到 {len(spot_map)} 条日线数据")

        active_stocks = get_tracked_stocks_list(mgr)
        if not active_stocks:
            return {
                'success': False,
                'message': '没有已跟踪的股票，请先点击「获取所有股票数据」',
                'updated_count': 0,
                'total': 0,
                'skipped': 0,
                'failed_count': 0,
            }

        trade_date_fmt = f"{display_date[:4]}-{display_date[4:6]}-{display_date[6:8]}"
        # 规则：仅对“今天”的更新做 15:00 后已更新跳过；回溯日期不跳过
        cutoff_dt = None
        if display_date == today:
            cutoff_dt = now.replace(hour=15, minute=0, second=0, microsecond=0)
        updated = 0
        skipped = 0
        failed_list: List[str] = []
        af_changed = 0
        total = len(active_stocks)

        db = Database.Create()
        cursor = None
        try:
            conn = db.get_connection()
            if db.is_sqlite:
                cursor = conn.cursor()
            else:
                cursor = conn.cursor(buffered=True)

            for stock in active_stocks:
                t0 = time.perf_counter()
                code = stock['code'] if isinstance(stock, dict) else stock[0]
                market = stock.get('market') if isinstance(stock, dict) else None
                if code not in spot_map:
                    skipped += 1
                    logger.info(
                        "Tushare 日线更新: %s %s status=skipped reason=no_data elapsed_ms=%.2f",
                        code,
                        trade_date_fmt,
                        (time.perf_counter() - t0) * 1000,
                    )
                    continue

                row = spot_map[code]
                table_name = mgr._get_stock_table_name(code)

                pre_close = _ts_float(row.get('pre_close'))
                high = _ts_float(row.get('high'))
                low = _ts_float(row.get('low'))
                amplitude = round((high - low) / pre_close * 100, 2) if pre_close else 0.0

                params = (
                    trade_date_fmt, code,
                    _ts_float(row.get('open')),
                    high, low,
                    _ts_float(row.get('close')),
                    int(_ts_float(row.get('vol')) * 100),
                    round(_ts_float(row.get('amount')) * 1000, 2),
                    amplitude,
                    _ts_float(row.get('pct_chg')),
                    _ts_float(row.get('change')),
                    0.0,
                )

                try:
                    if db.is_sqlite:
                        cursor.execute(f"""CREATE TABLE IF NOT EXISTS {table_name} (
                            trade_date DATE PRIMARY KEY,
                            code TEXT NOT NULL,
                            open REAL, high REAL, low REAL, close REAL,
                            volume INTEGER, amount REAL,
                            amplitude REAL, pct_change REAL, p_change REAL, turnover_rate REAL,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )""")
                        # 15 点后：若今天该行已更新过则跳过
                        if cutoff_dt is not None and now >= cutoff_dt:
                            if _already_updated_after_cutoff(
                                db=db,
                                cursor=cursor,
                                table_name=table_name,
                                trade_date_fmt=trade_date_fmt,
                                cutoff_dt=cutoff_dt,
                            ):
                                skipped += 1
                                logger.info(
                                    "Tushare 日线更新: %s %s status=skipped reason=already_updated_after_15 elapsed_ms=%.2f",
                                    code,
                                    trade_date_fmt,
                                    (time.perf_counter() - t0) * 1000,
                                )
                                continue
                        cursor.execute(f"""
                            INSERT INTO {table_name}
                                (trade_date, code, open, high, low, close, volume, amount,
                                 amplitude, pct_change, p_change, turnover_rate)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(trade_date) DO UPDATE SET
                                code=excluded.code, open=excluded.open, high=excluded.high,
                                low=excluded.low, close=excluded.close, volume=excluded.volume,
                                amount=excluded.amount, amplitude=excluded.amplitude,
                                pct_change=excluded.pct_change, p_change=excluded.p_change,
                                turnover_rate=excluded.turnover_rate,
                                updated_at=CURRENT_TIMESTAMP
                        """, params)
                    else:
                        cursor.execute(f"""CREATE TABLE IF NOT EXISTS {table_name} (
                            trade_date DATE PRIMARY KEY,
                            code VARCHAR(10) NOT NULL,
                            open DECIMAL(10,2), high DECIMAL(10,2), low DECIMAL(10,2), close DECIMAL(10,2),
                            volume BIGINT, amount DECIMAL(20,2),
                            amplitude DECIMAL(10,2), pct_change DECIMAL(10,2),
                            p_change DECIMAL(10,2), turnover_rate DECIMAL(10,2),
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
                        # 15 点后：若今天该行已更新过则跳过
                        if cutoff_dt is not None and now >= cutoff_dt:
                            if _already_updated_after_cutoff(
                                db=db,
                                cursor=cursor,
                                table_name=table_name,
                                trade_date_fmt=trade_date_fmt,
                                cutoff_dt=cutoff_dt,
                            ):
                                skipped += 1
                                logger.info(
                                    "Tushare 日线更新: %s %s status=skipped reason=already_updated_after_15 elapsed_ms=%.2f",
                                    code,
                                    trade_date_fmt,
                                    (time.perf_counter() - t0) * 1000,
                                )
                                continue
                        cursor.execute(f"""
                            INSERT INTO {table_name}
                                (trade_date, code, open, high, low, close, volume, amount,
                                 amplitude, pct_change, p_change, turnover_rate)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON DUPLICATE KEY UPDATE
                                code=VALUES(code), open=VALUES(open), high=VALUES(high),
                                low=VALUES(low), close=VALUES(close), volume=VALUES(volume),
                                amount=VALUES(amount), amplitude=VALUES(amplitude),
                                pct_change=VALUES(pct_change), p_change=VALUES(p_change),
                                turnover_rate=VALUES(turnover_rate)
                        """, params)
                    updated += 1
                    # 日线写入成功后，检查该交易日复权因子是否变化（变化则写入）
                    if sync_adj_factor_for_stock_on_trade_date is not None:
                        try:
                            r = sync_adj_factor_for_stock_on_trade_date(
                                code,
                                market,
                                trade_date_fmt,
                                config_obj=cfg,
                                db=db,
                            )
                            if r.get("changed"):
                                af_changed += 1
                        except Exception as e:
                            # 不阻断日线主流程
                            logger.debug("复权因子检查失败（已忽略）code=%s date=%s err=%s", code, trade_date_fmt, e)
                    logger.info(
                        "Tushare 日线更新: %s %s status=updated table=%s elapsed_ms=%.2f",
                        code,
                        trade_date_fmt,
                        table_name,
                        (time.perf_counter() - t0) * 1000,
                    )
                except Exception as e:
                    failed_list.append(code)
                    logger.error(
                        "Tushare 日线更新: %s %s status=failed table=%s err=%s elapsed_ms=%.2f",
                        code,
                        trade_date_fmt,
                        table_name,
                        e,
                        (time.perf_counter() - t0) * 1000,
                    )

            conn.commit()
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            db.close()

        msg = f'Tushare: 成功更新 {updated}/{total} 只股票的 {trade_date_fmt} 行情'
        if skipped:
            msg += f'，{skipped} 只无数据'
        if failed_list:
            msg += f'，{len(failed_list)} 只失败'
        if af_changed:
            msg += f'，{af_changed} 只复权因子有变化'

        logger.info(msg)
        return {
            'success': True,
            'message': msg,
            'updated_count': updated,
            'total': total,
            'skipped': skipped,
            'failed_count': len(failed_list),
            'adj_factor_changed': af_changed,
        }
    except Exception as e:
        logger.error(f"Tushare 拉取行情失败: {e}", exc_info=True)
        return {
            'success': False,
            'message': f'Tushare 拉取失败: {str(e)}',
            'updated_count': 0,
            'total': 0,
            'skipped': 0,
            'failed_count': 0,
            'status_code': 500,
        }
