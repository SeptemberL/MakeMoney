from flask import (Blueprint,
                   render_template,
                   jsonify,
                   request,
                   session,
                   Response,
                   stream_with_context)
from stocks.stock_fetcher import StockFetcher
from stocks.stock_analyzer import StockAnalyzer
from database.database import Database
from indicator_manager import IndicatorManager
import logging
import json
import pandas as pd
import numpy as np
from datetime import datetime
import os
import subprocess
import schedule
import time
import threading
import platform
if platform.system() == 'Windows':
    import wxauto
    from wxauto import *
from config import Config
import check_signal
from stock_list_manager import StockListManager
from signals.signal_boll3 import Signal_BOLL3
from stocks.stock_global import stockGlobal
from stocks.stock_filter import StockFilger
from Managers.ScanManager import ScanManager
from stock_gatter.stockgetter_btc import StockGetter_BTC
import csv
import tempfile
import sys
import re
from pathlib import Path

# 保证 TestScripts 可被导入（nga_format）
_route_dir = Path(__file__).resolve().parent
_test_scripts = _route_dir / 'TestScripts'
if str(_test_scripts) not in sys.path:
    sys.path.insert(0, str(_test_scripts))

try:
    from nga_spider import nga_db as nga_db
    from nga_spider.nga_crawler import NGACrawler
    from nga_spider import nga_parser as nga_parser
    from nga_spider.nga_monitor import load_config as load_nga_config
except Exception:
    nga_db = None



# 创建蓝图
bp = Blueprint('main', __name__)



# 初始化组件
fetcher = StockFetcher()
analyzer = StockAnalyzer()
indicator_manager = IndicatorManager()
manager = StockListManager()

# 设置日志
logger = logging.getLogger(__name__)

# 全局变量
sendAllMessage = ""
config = Config()

_STOCK_TABLE_RE = re.compile(r'^stock_(\d{6})_(SH|SZ)$')

def _get_tracked_stocks():
    """获取已跟踪的股票列表，优先 stock_list，否则回退到扫描已有的 stock_XXXXXX_XX 表"""
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


@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/quant')
def quant():
    """量化功能专用页面"""
    return render_template('quant.html')

@bp.route('/market_open_score')
def market_open_score():
    """今日大盘开盘评分"""
    return render_template('market_open_score.html')

@bp.route('/api/stocks', methods=['GET'])
def get_stocks():
    """获取所有股票列表"""
    try:
        print("get_stocks")
        stocks = fetcher.get_stock_list()
        return jsonify(stocks)
    except Exception as e:
        logger.error(f"获取股票列表失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@bp.route('/api/stocks', methods=['POST'])
def add_stock():
    """添加新股票"""
    try:
        data = request.get_json()
        code = data.get('code')
        name = data.get('name')
        
        if not code:
            return jsonify({'error': '股票代码不能为空'}), 400
            
        if fetcher.add_stock(code, name):
            return jsonify({'success': True})
        else:
            return jsonify({'error': '添加股票失败'}), 500
            
    except Exception as e:
        logger.error(f"添加股票失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@bp.route('/api/stocks/<code>', methods=['DELETE'])
def delete_stock(code):
    """删除股票"""
    try:
        if fetcher.delete_stock(code):
            return jsonify({'success': True})
        else:
            return jsonify({'error': '删除股票失败'}), 500
            
    except Exception as e:
        logger.error(f"删除股票失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@bp.route('/api/stock_data/<stock_code>')
def get_stock_data(stock_code):
    try:
        # 优先尝试增量更新该股票的历史数据
        try:
            manager.update_stock_history(stock_code)
        except Exception as e:
            logger.warning(f"更新股票 {stock_code} 历史数据失败，将尝试直接读取: {e}")

        df = manager.get_stock_data(stock_code, 365)
        if df is None or df.empty:
            return jsonify({'error': '没有找到数据'}), 404

        # 规范数据类型
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        numeric_columns = [
            'open', 'close', 'high', 'low',
            'volume', 'amount', 'p_change', 'turnover_rate'
        ]
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 计算技术指标
        df = analyzer.calculate_indicators(df)

        # 收集信号：单股策略信号 + BOLL 条件检查
        signals_list = []
        try:
            signal_msg = check_signal.CheckSingle(stock_code, manager)
            if signal_msg:
                logger.info(f"单股信号 - {stock_code}: {signal_msg}")
                signals_list.append({
                    'type': '策略信号',
                    'message': signal_msg,
                    'signal': 'BUY',
                    'strength': '-'
                })
        except Exception as e:
            logger.error(f"执行单股信号检查失败 ({stock_code}): {e}", exc_info=True)

        try:
            boll_msg = check_signal_conditions(df, stock_code)
            if boll_msg:
                signals_list.append({
                    'type': 'BOLL',
                    'message': boll_msg,
                    'signal': 'BUY',
                    'strength': '-'
                })
        except Exception as e:
            logger.error(f"检查信号条件失败 ({stock_code}): {e}", exc_info=True)

        # 振幅统计（供前端展示）
        amplitude_info = None
        try:
            amplitude_info = calculate_amplitude(df)
        except Exception as e:
            logger.debug(f"计算振幅跳过 ({stock_code}): {e}")

        # 组装返回数据，统一为 JSON 结构
        data = df.replace({np.nan: None}).to_dict('records')
        response_data = {
            'data': data,
            'probabilities': {},       # 预留：analyzer.calculate_probability(df)
            'signals': signals_list,
            'amplitude': amplitude_info
        }
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"获取股票数据失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/update_all_stocks', methods=['POST'])
def update_all_stocks_api():
    try:
        updated_count, failed_stocks, signalMessages = update_all_stocks(True)
        stockGlobal.wx.SendSignalMessages(signalMessages)
        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'failed_stocks': failed_stocks,
            'message': f'成功更新 {updated_count} 只股票'
        })
    except Exception as e:
        logger.error(f"更新所有股票时出错: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/list_manager')
def list_manager():
    return render_template('list_manager.html')

@bp.route('/api/items', methods=['GET'])
def get_items():
    try:
        db = Database.Create()
        cursor = db.cursor()
        query = "CREATE TABLE IF NOT EXISTS items (item TEXT PRIMARY KEY, status INTEGER DEFAULT 1)"
        cursor.execute(query)
        
        cursor.execute('SELECT item, status FROM items ORDER BY item')
        items = [{'item': row[0], 'status': bool(row[1])} for row in cursor.fetchall()]
        
        db.close()
        return jsonify(items)
        
    except Exception as e:
        logger.error(f"获取项目列表失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@bp.route('/api/items', methods=['POST'])
def add_item():
    try:
        db = Database.Create()
        data = request.get_json()
        item = data.get('item')
        status = data.get('status', True)
        
        if not item:
            return jsonify({'error': '内容不能为空'}), 400
            
        cursor = db.cursor()
        
        cursor.execute('INSERT OR REPLACE INTO items (item, status) VALUES (?, ?)', 
                      (item, 1 if status else 0))
        
        db.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"添加项目失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@bp.route('/api/items/<item>/toggle', methods=['POST'])
def toggle_item_status(item):
    try:
        db = Database.Create()
        cursor = db.cursor()
        
        cursor.execute('''
            UPDATE items 
            SET status = CASE WHEN status = 1 THEN 0 ELSE 1 END 
            WHERE item = ?
        ''', (item,))
                
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"切换项目状态失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@bp.route('/chat_groups')
def chat_groups_page():
    return render_template('chat_groups.html')


@bp.route('/api/chat_groups', methods=['GET'])
def get_chat_groups():
    try:
        db = Database.Create()
        db.ensure_message_group_tables()
        groups = db.get_all_message_groups()
        db.close()
        return jsonify({'success': True, 'groups': groups})
    except Exception as e:
        logger.error(f"获取聊天群列表失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/chat_groups', methods=['POST'])
def create_chat_group():
    try:
        data = request.get_json() or {}
        group_id = data.get('group_id')
        if group_id is None:
            return jsonify({'success': False, 'message': '缺少 group_id'}), 400
        try:
            group_id = int(group_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'group_id 须为整数'}), 400
        list_type = (data.get('list_type') or 'weixin').strip() or 'weixin'
        chat_list = data.get('chat_list')
        if not isinstance(chat_list, list):
            chat_list = []
        db = Database.Create()
        ok, result = db.create_message_group(group_id=group_id, list_type=list_type, chat_list=chat_list)
        db.close()
        if ok:
            return jsonify({'success': True, 'id': result})
        return jsonify({'success': False, 'message': result or '创建失败'}), 400
    except Exception as e:
        logger.error(f"创建聊天群组失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/chat_groups/<int:pk_id>', methods=['PUT'])
def update_chat_group(pk_id):
    try:
        data = request.get_json() or {}
        group_id = data.get('group_id')
        list_type = data.get('list_type')
        chat_list = data.get('chat_list')
        db = Database.Create()
        if group_id is not None:
            try:
                group_id = int(group_id)
            except (TypeError, ValueError):
                db.close()
                return jsonify({'success': False, 'message': 'group_id 须为整数'}), 400
        ok, err = db.update_message_group(pk_id, group_id=group_id, list_type=list_type, chat_list=chat_list)
        db.close()
        if ok:
            return jsonify({'success': True})
        return jsonify({'success': False, 'message': err or '更新失败'}), 400
    except Exception as e:
        logger.error(f"更新聊天群组失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/chat_groups/<int:pk_id>', methods=['DELETE'])
def delete_chat_group(pk_id):
    try:
        db = Database.Create()
        ok = db.delete_message_group(pk_id)
        db.close()
        if ok:
            return jsonify({'success': True})
        return jsonify({'success': False, 'message': '删除失败'}), 400
    except Exception as e:
        logger.error(f"删除聊天群组失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/update_stock_list', methods=['POST'])
def update_stock_list_api():
    sendAllMessage = ""
    success, sendAllMessage = manager.update_stock_list(False, None)
    if platform.system() == 'Windows' and stockGlobal.wx:
        stockGlobal.wx.SendSignalMessages(sendAllMessage)
    if success:
        if platform.system() == 'Windows' and stockGlobal.wx:
            SendAllMessages()
        return jsonify({
            'success': True, 
            'message': '股票列表更新成功'
        })
    else:
        if platform.system() == 'Windows' and stockGlobal.wx:
            SendAllMessages()
        return jsonify({
            'success': False,
            'message': '股票列表更新失败'
        }), 500

@bp.route('/api/fetch_today_stocks', methods=['POST'])
def fetch_today_stocks_api():
    """使用 AKShare 批量拉取当天全市场实时行情，更新到已跟踪的各股票表中"""
    try:
        import akshare as ak

        def _safe_float(val, default=0.0):
            try:
                if pd.isna(val) or val == '-':
                    return default
                return float(val)
            except (ValueError, TypeError):
                return default

        def _safe_int(val, default=0):
            try:
                if pd.isna(val) or val == '-':
                    return default
                return int(float(val))
            except (ValueError, TypeError):
                return default

        logger.info("开始拉取当天股票实时行情...")
        spot_df = None
        for attempt in range(3):
            try:
                spot_df = ak.stock_zh_a_spot_em()
                break
            except Exception as fetch_err:
                logger.warning(f"拉取实时行情第 {attempt+1} 次失败: {fetch_err}")
                if attempt < 2:
                    time.sleep(2)
        if spot_df is None or spot_df.empty:
            return jsonify({'success': False, 'message': '拉取实时行情失败，请稍后重试'}), 500
        spot_df['代码'] = spot_df['代码'].astype(str)
        spot_map = {}
        for _, r in spot_df.iterrows():
            spot_map[r['代码']] = r
        logger.info(f"获取到 {len(spot_map)} 条实时行情")

        active_stocks = _get_tracked_stocks()
        if not active_stocks:
            return jsonify({'success': False, 'message': '没有已跟踪的股票，请先点击「获取所有股票数据」'})

        today = datetime.now().strftime('%Y-%m-%d')
        updated = 0
        skipped = 0
        failed_list = []
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
                code = stock['code'] if isinstance(stock, dict) else stock[0]
                if code not in spot_map:
                    skipped += 1
                    continue

                row = spot_map[code]
                table_name = manager._get_stock_table_name(code)
                params = (
                    today, code,
                    _safe_float(row.get('今开')),
                    _safe_float(row.get('最高')),
                    _safe_float(row.get('最低')),
                    _safe_float(row.get('最新价')),
                    _safe_int(row.get('成交量')),
                    _safe_float(row.get('成交额')),
                    _safe_float(row.get('振幅')),
                    _safe_float(row.get('涨跌幅')),
                    _safe_float(row.get('涨跌额')),
                    _safe_float(row.get('换手率')),
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
                                turnover_rate=excluded.turnover_rate
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
                except Exception as e:
                    failed_list.append(code)
                    logger.error(f"更新 {code} 当日数据失败: {e}")

            conn.commit()
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            db.close()

        msg = f'成功更新 {updated}/{total} 只股票的当天数据'
        if skipped:
            msg += f'，{skipped} 只无行情数据'
        if failed_list:
            msg += f'，{len(failed_list)} 只失败'

        logger.info(msg)
        return jsonify({
            'success': True,
            'message': msg,
            'updated_count': updated,
            'total': total,
            'skipped': skipped,
            'failed_count': len(failed_list)
        })
    except Exception as e:
        logger.error(f"拉取当天股票数据失败: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'拉取失败: {str(e)}'}), 500


@bp.route('/api/fetch_today_tushare', methods=['POST'])
def fetch_today_tushare_api():
    """使用 Tushare 拉取当天日线行情，更新到已跟踪的各股票表中"""
    try:
        import tushare as ts

        token = config.get('TUSHARE', 'TOKEN')
        if not token or token == 'your-tushare-token-here':
            return jsonify({'success': False, 'message': '未配置 Tushare Token，请在 config.ini [TUSHARE] 中设置 TOKEN'}), 400

        pro = ts.pro_api(token)
        today = datetime.now().strftime('%Y%m%d')

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
            from datetime import timedelta
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
            return jsonify({'success': False, 'message': f'{today} 暂无行情数据（可能未开盘或数据未更新）'})

        spot_map = {}
        for _, r in daily_df.iterrows():
            code = str(r['ts_code']).split('.')[0]
            spot_map[code] = r
        logger.info(f"Tushare 获取到 {len(spot_map)} 条日线数据")

        active_stocks = _get_tracked_stocks()
        if not active_stocks:
            return jsonify({'success': False, 'message': '没有已跟踪的股票，请先点击「获取所有股票数据」'})

        trade_date_fmt = f"{display_date[:4]}-{display_date[4:6]}-{display_date[6:8]}"
        updated = 0
        skipped = 0
        failed_list = []
        total = len(active_stocks)

        def _ts_float(val, default=0.0):
            try:
                if pd.isna(val):
                    return default
                return float(val)
            except (ValueError, TypeError):
                return default

        db = Database.Create()
        cursor = None
        try:
            conn = db.get_connection()
            if db.is_sqlite:
                cursor = conn.cursor()
            else:
                cursor = conn.cursor(buffered=True)

            for stock in active_stocks:
                code = stock['code'] if isinstance(stock, dict) else stock[0]
                if code not in spot_map:
                    skipped += 1
                    continue

                row = spot_map[code]
                table_name = manager._get_stock_table_name(code)

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
                                turnover_rate=excluded.turnover_rate
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
                except Exception as e:
                    failed_list.append(code)
                    logger.error(f"Tushare 更新 {code} 失败: {e}")

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

        logger.info(msg)
        return jsonify({
            'success': True,
            'message': msg,
            'updated_count': updated,
            'total': total,
            'skipped': skipped,
            'failed_count': len(failed_list)
        })
    except ImportError:
        return jsonify({'success': False, 'message': 'tushare 未安装，请运行 pip install tushare'}), 500
    except Exception as e:
        logger.error(f"Tushare 拉取行情失败: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Tushare 拉取失败: {str(e)}'}), 500


@bp.route('/api/macd_settings', methods=['POST'])
def update_macd_settings():
    """更新MACD参数设置"""
    try:
        data = request.get_json()
        ema_short = data.get('ema_short')
        ema_long = data.get('ema_long')
        dea_period = data.get('dea_period')
        
        if not all(isinstance(x, int) and x > 0 for x in [ema_short, ema_long, dea_period]):
            return jsonify({'error': '参数必须是正整数'}), 400
            
        analyzer.update_macd_params(ema_short, ema_long, dea_period)
        
        return jsonify({
            'success': True,
            'message': 'MACD参数更新成功',
            'params': {
                'ema_short': ema_short,
                'ema_long': ema_long,
                'dea_period': dea_period
            }
        })
        
    except Exception as e:
        logger.error(f"更新MACD参数失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@bp.route('/api/register', methods=['POST'])
def register():
    """用户注册。需 POST JSON: username, password, email(可选)。成功 201，参数错误 400，重复 409，服务器错误 500。"""
    try:
        data = request.get_json() or {}
        username = (data.get('username') or '').strip()
        password = data.get('password')
        email = (data.get('email') or '').strip() or None

        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400

        db = Database.Create()
        db.init_database()  # 确保 users 表存在（CREATE TABLE IF NOT EXISTS）
        ok, reason = db.create_user(username, password, email)
        if ok:
            return jsonify({'success': True, 'message': '注册成功'}), 201
        if reason == 'duplicate':
            return jsonify({'success': False, 'message': '用户名或邮箱已存在'}), 409
        return jsonify({'success': False, 'message': '注册失败，请稍后重试'}), 400
    except Exception as e:
        logger.error(f"用户注册失败: {e}", exc_info=True)
        return jsonify({'success': False, 'message': '注册失败，请稍后重试'}), 500

@bp.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'})
    db = Database.Create()
    result = db.verify_user(username, password)
    if result['success']:
        session['user_id'] = result['user_id']
        session['username'] = result['username']
        db.close()
        return jsonify({
            'success': True,
            'message': '登录成功',
            'user': {
                'id': result['user_id'],
                'username': result['username'],
                'settings': result['settings']
            }
        })
    else:
        db.close()
        return jsonify({'success': False, 'message': result['message']})

@bp.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True, 'message': '已退出登录'})

@bp.route('/api/user/settings', methods=['GET'])
def get_user_settings():
    """获取用户设置"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '请先登录'})
        db = Database.Create()
        settings = db.get_user_settings(session['user_id'])
        db.close()
        return jsonify({'success': True, 'settings': settings}) 
    except Exception as e:
        logger.error(f"获取用户设置失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})
            

@bp.route('/api/user/settings', methods=['POST'])
def update_user_settings():
    """更新用户设置"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '请先登录'})
    
    try:
        data = request.get_json()
        db = Database.Create()
        if db.update_user_settings(session['user_id'], data):
            return jsonify({'success': True, 'message': '设置已更新'})
        else:
            return jsonify({'success': False, 'message': '更新设置失败'})
    except Exception as e:
        logger.error(f"更新用户设置失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@bp.route('/indicator_manager')
def indicator_manager_page():
    return render_template('indicator_manager.html')

@bp.route('/api/indicators', methods=['GET'])
def get_indicators():
    try:
        indicators = indicator_manager.get_all_indicators()
        return jsonify({
            'success': True,
            'indicators': indicators
        })
    except Exception as e:
        logging.error(f"获取指标列表失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators/<int:id>', methods=['GET'])
def get_indicator(id):
    try:
        indicators = indicator_manager.get_all_indicators()
        indicator = next((i for i in indicators if i['id'] == id), None)
        if indicator:
            return jsonify({
                'success': True,
                'indicator': indicator
            })
        else:
            return jsonify({
                'success': False,
                'message': '指标不存在'
            })
    except Exception as e:
        logging.error(f"获取指标详情失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators', methods=['POST'])
def add_indicator():
    try:
        data = request.get_json()
        name = data.get('name')
        view_number = data.get('view_number')
        class_name = data.get('class_name')
        
        if not all([name, view_number, class_name]):
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            })
            
        indicator_manager.add_indicator(name, view_number, class_name)
        return jsonify({
            'success': True,
            'message': '添加指标成功'
        })
    except Exception as e:
        logging.error(f"添加指标失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators/<int:id>', methods=['PUT'])
def update_indicator(id):
    try:
        data = request.get_json()
        name = data.get('name')
        view_number = data.get('view_number')
        class_name = data.get('class_name')
        
        if not all([name, view_number, class_name]):
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            })
            
        indicator_manager.update_indicator(id, name, view_number, class_name)
        return jsonify({
            'success': True,
            'message': '更新指标成功'
        })
    except Exception as e:
        logging.error(f"更新指标失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators/<int:id>', methods=['DELETE'])
def delete_indicator(id):
    try:
        indicator_manager.delete_indicator(id)
        return jsonify({
            'success': True,
            'message': '删除指标成功'
        })
    except Exception as e:
        logging.error(f"删除指标失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators/<int:id>/toggle', methods=['POST'])
def toggle_indicator(id):
    try:
        data = request.get_json()
        is_enabled = data.get('is_enabled')
        
        if is_enabled is None:
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            })
            
        indicator_manager.toggle_indicator(id, is_enabled)
        return jsonify({
            'success': True,
            'message': '切换指标状态成功'
        })
    except Exception as e:
        logging.error(f"切换指标状态失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

# ─────────────────────────── NGA 监控任务 ────────────────────────────────────

@bp.route('/nga_monitor')
def nga_monitor_page():
    """NGA 监控任务状态与开关页面"""
    return render_template('nga_monitor.html')


@bp.route('/nga_floors/<int:tid>')
def nga_floors_page(tid: int):
    """
    某个帖子已抓取楼层列表页面（含已发送 / 未发送），从 NGA 监控页跳转。
    """
    if nga_db is None:
        return render_template('nga_floors.html', tid=tid, thread=None, error="NGA 模块未加载")
    try:
        thread = nga_db.get_thread_config(tid)
        if not thread:
            return render_template('nga_floors.html', tid=tid, thread=None, error="帖子配置不存在，请先在 NGA 监控页面添加。")
        return render_template('nga_floors.html', tid=tid, thread=thread, error=None)
    except Exception as e:
        logger.error(f"加载 NGA 楼层页面失败: {str(e)}", exc_info=True)
        return render_template('nga_floors.html', tid=tid, thread=None, error=str(e))

@bp.route('/api/nga_tasks', methods=['GET'])
def get_nga_tasks():
    """获取所有 NGA 监控任务（含运行状态）"""
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        tasks = nga_db.get_thread_configs(only_auto_run=False)
        return jsonify({'success': True, 'tasks': tasks})
    except Exception as e:
        logger.error(f"获取 NGA 任务列表失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_floors/<int:tid>', methods=['GET'])
def get_nga_floors(tid: int):
    """
    获取某个帖子的已抓取楼层列表，包含在当前群组下是否已发送。
    前端按行展示，并提供手动发送按钮。
    """
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        thread = nga_db.get_thread_config(tid)
        if not thread:
            return jsonify({'success': False, 'message': '帖子配置不存在'}), 404
        group_id = thread.get('message_group_id')
        if group_id is None or group_id == 0 or group_id == '0':
            return jsonify({'success': True, 'thread': thread, 'floors': [], 'message': '该帖子未配置消息群组，无法发送，仅展示已抓取楼层。'})

        # 默认拉取最近 200 条楼层
        floors = nga_db.get_floors_with_sent_for_group(tid, group_id, limit=200, offset=0)
        return jsonify({'success': True, 'thread': thread, 'floors': floors})
    except Exception as e:
        logger.error(f"获取 NGA 楼层列表失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_floors/<int:tid>/<int:pid>/send', methods=['POST'])
def send_nga_floor(tid: int, pid: int):
    """
    手动发送某一楼内容到配置的群组。
    不再检查 watch_author_ids 和是否已发送（允许手动重发），但仍会在 sent_log 中做去重。
    """
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        thread = nga_db.get_thread_config(tid)
        if not thread:
            return jsonify({'success': False, 'message': '帖子配置不存在'}), 404

        group_id = thread.get('message_group_id')
        if group_id is None or group_id == 0 or group_id == '0':
            return jsonify({'success': False, 'message': '该帖子未配置消息群组，无法发送'}), 400

        floor = nga_db.get_floor_by_tid_pid(tid, pid)
        if not floor:
            return jsonify({'success': False, 'message': '楼层不存在'}), 404

        # 读取 NGA 基本配置（auth / settings）
        try:
            cfg = load_nga_config()
        except Exception as e:
            logger.error(f"加载 NGA 配置失败: {e}", exc_info=True)
            return jsonify({'success': False, 'message': '加载 NGA 配置失败'}), 500

        auth_cfg = cfg.get('auth', {}) if isinstance(cfg, dict) else {}
        settings = cfg.get('settings', {}) if isinstance(cfg, dict) else {}
        user_agent = settings.get('user_agent') or None

        # 构造爬虫实例，仅复用其 _send_wx 方法
        thread_cfg = {
            'name': thread.get('name') or str(tid),
            'watch_author_ids': thread.get('watch_author_ids') or [],
            'message_group_id': group_id,
        }

        wx_instance = None
        try:
            if getattr(stockGlobal, 'wx', None):
                wx_instance = stockGlobal.wx
        except Exception:
            wx_instance = None

        crawler = NGACrawler(tid=tid, thread_cfg=thread_cfg, auth_cfg=auth_cfg, wx=wx_instance, user_agent=user_agent)

        # 生成与自动推送一致的消息内容
        msg = nga_parser.build_wx_message(
            tid=tid,
            floor_num=floor['floor_num'],
            pid=floor['pid'],
            author_name=floor['author_name'],
            post_date=floor.get('post_date', ''),
            content_text=floor.get('content_text', ''),
            quote_text=floor.get('quote_text'),
            quote_name=None,
            images=floor.get('images', []),
            thread_name=thread_cfg['name'],
        )

        crawler._send_wx(msg, group_id)
        nga_db.mark_sent(tid, pid, group_id)

        return jsonify({'success': True, 'message': '发送成功'})
    except Exception as e:
        logger.error(f"手动发送 NGA 楼层失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/nga_tasks/<int:tid>/toggle', methods=['POST'])
def toggle_nga_task(tid):
    """切换指定帖子的自动运行开关"""
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        new_state = nga_db.set_thread_auto_run(tid)
        if new_state is None:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        return jsonify({'success': True, 'auto_run': new_state})
    except Exception as e:
        logger.error(f"切换 NGA 任务状态失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_tasks/<int:tid>', methods=['GET'])
def get_nga_task(tid):
    """获取单条 NGA 监控任务（用于编辑）"""
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        task = nga_db.get_thread_config(tid)
        if task is None:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        return jsonify({'success': True, 'task': task})
    except Exception as e:
        logger.error(f"获取 NGA 任务失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_tasks', methods=['POST'])
def create_nga_task():
    """新增 NGA 监控帖子"""
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        data = request.get_json() or {}
        tid = data.get('tid')
        if tid is None:
            return jsonify({'success': False, 'message': '缺少帖子 ID (tid)'}), 400
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'tid 必须为整数'}), 400
        name = (data.get('name') or '').strip()
        watch_author_ids = data.get('watch_author_ids')
        if isinstance(watch_author_ids, list):
            watch_author_ids = [int(x) for x in watch_author_ids if x is not None and str(x).strip() != '']
        elif isinstance(watch_author_ids, str):
            watch_author_ids = [int(x.strip()) for x in watch_author_ids.split(',') if x.strip().isdigit()]
        else:
            watch_author_ids = []
        message_group_id = data.get('message_group_id')
        if message_group_id is not None:
            message_group_id = str(message_group_id).strip() or '0'
        else:
            message_group_id = '0'
        auto_run = bool(data.get('auto_run', True))
        nga_db.save_thread_config(tid=tid, name=name, watch_author_ids=watch_author_ids,
                                   message_group_id=message_group_id, auto_run=auto_run)
        return jsonify({'success': True, 'message': '添加成功'})
    except ValueError as e:
        return jsonify({'success': False, 'message': f'参数错误: {e}'}), 400
    except Exception as e:
        logger.error(f"添加 NGA 任务失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_tasks/<int:tid>', methods=['PUT'])
def update_nga_task(tid):
    """编辑 NGA 监控帖子"""
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        existing = nga_db.get_thread_config(tid)
        if existing is None:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        data = request.get_json() or {}
        name = (data.get('name') or '').strip() if 'name' in data else existing['name']
        watch_author_ids = data.get('watch_author_ids')
        if watch_author_ids is not None:
            if isinstance(watch_author_ids, list):
                watch_author_ids = [int(x) for x in watch_author_ids if x is not None and str(x).strip() != '']
            elif isinstance(watch_author_ids, str):
                watch_author_ids = [int(x.strip()) for x in watch_author_ids.split(',') if x.strip().isdigit()]
            else:
                watch_author_ids = []
        else:
            watch_author_ids = existing['watch_author_ids']
        message_group_id = data.get('message_group_id')
        if message_group_id is not None:
            message_group_id = str(message_group_id).strip() or '0'
        else:
            message_group_id = existing.get('message_group_id') or '0'
        auto_run = data.get('auto_run') if 'auto_run' in data else existing['auto_run']
        auto_run = bool(auto_run)
        nga_db.save_thread_config(tid=tid, name=name, watch_author_ids=watch_author_ids,
                                   message_group_id=message_group_id, auto_run=auto_run)
        return jsonify({'success': True, 'message': '保存成功'})
    except ValueError as e:
        return jsonify({'success': False, 'message': f'参数错误: {e}'}), 400
    except Exception as e:
        logger.error(f"更新 NGA 任务失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_tasks/<int:tid>', methods=['DELETE'])
def delete_nga_task(tid):
    """删除 NGA 监控帖子"""
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        ok = nga_db.delete_thread_config(tid)
        if not ok:
            return jsonify({'success': False, 'message': '任务不存在或删除失败'}), 404
        return jsonify({'success': True, 'message': '已删除'})
    except Exception as e:
        logger.error(f"删除 NGA 任务失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_message_groups', methods=['GET'])
def get_nga_message_groups():
    """获取消息群组列表（用于添加/编辑帖子时的下拉选择），从数据库读取。"""
    try:
        db = Database.Create()
        db.ensure_message_group_tables()
        groups = db.get_all_message_groups()
        db.close()
        out = [{'group_id': str(g.get('group_id', '')), 'chat_list': g.get('chat_list', [])} for g in groups]
        return jsonify({'success': True, 'groups': out})
    except Exception as e:
        logger.error(f"获取消息群组列表失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/test_send_image', methods=['POST'])
def test_send_image():
    """
    测试发送图片：从 config.ini [WX] TestImageUrl 下载图片，
    通过剪贴板（SendFiles）发送到 TestImageSendTo 配置的微信聊天。
    仅 Windows 且启用微信时有效。
    """
    #if platform.system() != 'Windows':
    #    return jsonify({'success': False, 'message': '仅支持 Windows 系统'}), 400
    try:
        url = config.get('WX', 'TestImageUrl')
        send_to = config.get('WX', 'TestImageSendTo') or '光影相生'
        if not url or not url.strip():
            return jsonify({'success': False, 'message': '未配置 TestImageUrl，请在 config.ini [WX] 中设置'}), 400
        url = url.strip()
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        cookies = None
        try:
            cfg = load_nga_config()
            auth_cfg = (cfg or {}).get('auth') or {}
            uid = auth_cfg.get('ngaPassportUid') or ''
            cid = auth_cfg.get('ngaPassportCid') or ''
            if uid and cid:
                headers['Referer'] = 'https://bbs.nga.cn/'
                cookies = {'ngaPassportUid': str(uid), 'ngaPassportCid': str(cid)}
            settings = (cfg or {}).get('settings') or {}
            if settings.get('user_agent'):
                headers['User-Agent'] = settings.get('user_agent')
        except Exception:
            pass
        suffix = '.png'
        if '.jpg' in url.lower() or 'jpeg' in url.lower():
            suffix = '.jpg'
        elif '.gif' in url.lower():
            suffix = '.gif'
        filename = 'test_image' + suffix
        tmpdir = tempfile.mkdtemp()
        try:
            import nga_format
            fullpath = nga_format.util_down(url, tmpdir, filename, '', headers=headers, cookies=cookies)
            wx_instance = getattr(stockGlobal, 'wx', None)
            if wx_instance is None:
                return jsonify({'success': False, 'message': '微信未初始化，请确认已开启微信并启用 EnableWX'}), 400
            wx_instance.SendFiles(fullpath, who=send_to)
            return jsonify({'success': True, 'message': f'已发送到「{send_to}」'})
        finally:
            try:
                import shutil
                if os.path.exists(tmpdir):
                    shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"测试发送图片失败: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

# 辅助函数
def AddMessage(message):
    global sendAllMessage
    sendAllMessage += message + "\n"

def SendAllMessages():
    stockGlobal.wx.SendMsg(sendAllMessage, "光影相生") 

def SendSignalMessages(messages):
    stockGlobal.wx.SendMsg(messages, "光影相生") 

def update_all_stocks(SkipZeroSocks = True):
    try:
        stocks = fetcher.get_stock_list()
        updated_count = 0
        failed_stocks = []
        signalsMessages = []
        logger.info(stocks)
        for stock in stocks:
            try:
                logger.info(f"正在更新股票 {stock['code']} 的数据...")
                df = fetcher.get_stock_data(stock['code'], days=365)
                
                if df is not None and not df.empty:
                    df = analyzer.calculate_indicators(df)


                    df['trade_date'] = df['trade_date'].dt.strftime('%Y-%m-%d')

                    formatted_date = datetime.now().strftime("%Y-%m-%d")
                    signals = analyzer.generate_signals(df)
                    message = formatted_date + "\n股票：" + stock['name'] + "(" + stock['code'] + ")"
                    if len(signals) == 0:
                        if SkipZeroSocks: 
                            continue
                        message = "\n未触发任何信号"
                    else:
                        for signal in signals:
                            message = message + "\n" + signal['message']

                    signalsMessages.append(message)
                    updated_count += 1
                    logger.info(f"股票 {stock['code']} 更新成功: {message}")
                else:
                    failed_stocks.append(stock['code'])
                    logger.error(f"股票 {stock['code']} 更新失败：无法获取数据")
                
            except Exception as e:
                failed_stocks.append(stock['code'])
                logger.error(f"更新股票 {stock['code']} 时出错: {str(e)}", exc_info=True)
        
        return updated_count, failed_stocks, signalsMessages
        
    except Exception as e:
        logger.error(f"更新所有股票时出错: {str(e)}", exc_info=True)
        raise

def calculate_amplitude(df):
    try:
        df['amplitude'] = (df['high'] - df['low']) / df['close'].shift(1) * 100
        avg_amplitude = df['amplitude'].mean()
        
        return {
            'average_amplitude': round(avg_amplitude, 2),
            'max_amplitude': round(df['amplitude'].max(), 2),
            'min_amplitude': round(df['amplitude'].min(), 2),
            'latest_amplitude': round(df['amplitude'].iloc[-1], 2)
        }
    except Exception as e:
        logger.error(f"计算振幅时出错: {str(e)}", exc_info=True)
        return None

def check_signal_conditions(df, stock_code):
    """根据最新一根K线的 BOLL / MACD / KDJ 情况，检测是否触发高位 BOLL 信号。

    入参校验：df 必须为非空 DataFrame，stock_code 为非空字符串；否则返回 None。
    有信号时返回描述字符串，无信号或异常时返回 None。
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    if not stock_code or not isinstance(stock_code, str) or not str(stock_code).strip():
        return None
    stock_code = str(stock_code).strip()

    latest_data = df.iloc[-1]

    try:
        # 安全地读取需要的字段，缺失时直接认为不触发信号
        high = latest_data.get('high')
        boll_upper2 = latest_data.get('boll_upper2')
        boll_upper3 = latest_data.get('boll_upper3')

        if high is None or boll_upper2 is None or boll_upper3 is None:
            return None

        is_between_2_3_sigma = (high >= boll_upper2 and high <= boll_upper3)
        is_above_3_sigma = high > boll_upper3

        if not (is_between_2_3_sigma or is_above_3_sigma):
            return None

        close = latest_data.get('close')
        low = latest_data.get('low')
        volume = latest_data.get('volume')
        boll_mid = latest_data.get('boll_mid')
        macd = latest_data.get('macd')
        macd_signal = latest_data.get('macd_signal')
        macd_hist = latest_data.get('macd_hist')
        k_val = latest_data.get('k')
        d_val = latest_data.get('d')
        j_val = latest_data.get('j')

        def _fmt(val, fmt, default='-'):
            try:
                if val is None:
                    return default
                return format(float(val), fmt)
            except Exception:
                return default

        vol_wan = '-'
        try:
            if volume is not None:
                vol_wan = format(float(volume) / 10000.0, '.2f')
        except Exception:
            pass

        message = (
            f"股票 {stock_code} 出现BOLL带信号！\n"
            f"日期: {latest_data.get('trade_date')}\n"
            f"收盘价: {_fmt(close, '.2f')}\n"
            f"最低价: {_fmt(low, '.2f')}\n"
            f"成交量： {vol_wan} 万手\n"
            f"BOLL指标:\n"
            f"- 中轨: {_fmt(boll_mid, '.2f')}\n"
            f"- 上轨(2σ): {_fmt(boll_upper2, '.2f')}\n"
            f"- 上轨(3σ): {_fmt(boll_upper3, '.2f')}\n"
            f"MACD指标:\n"
            f"- MACD: {_fmt(macd, '.3f')}\n"
            f"- 信号线: {_fmt(macd_signal, '.3f')}\n"
            f"- 柱状值: {_fmt(macd_hist, '.3f')}\n"
            f"KDJ指标:\n"
            f"- K值: {_fmt(k_val, '.2f')}\n"
            f"- D值: {_fmt(d_val, '.2f')}\n"
            f"- J值: {_fmt(j_val, '.2f')}\n"
            f"信号类型: {'突破3σ上轨' if is_above_3_sigma else '位于2σ-3σ之间'}"
        )
        logger.info(f"触发BOLL信号 - 股票代码: {stock_code}")
        return message
    except Exception as e:
        logger.error(f"检查信号条件时出错: {str(e)}", exc_info=True)
        return None 

@bp.route('/stock_filter')
def stock_filter():
    """股票筛选器页面"""
    return render_template('stock_filter.html')

@bp.route('/api/filter_stocks', methods=['GET'])
def filter_stocks():
    """处理股票筛选请求"""
    try:
        # 从 URL 参数中获取数据；targetDate 可选，YYYY-MM-DD，不传则使用当前交易日
        data = {
            'market': request.args.get('market', 'CN'),
            'period': request.args.get('period', 'k1d'),
            'filterSignal': request.args.getlist('filterSignal'),
            'volume': request.args.get('volume', ''),
            'priceMin': request.args.get('priceMin'),
            'priceMax': request.args.get('priceMax'),
            'dayRange': request.args.get('dayRange'),
            'targetDate': request.args.get('targetDate'),  # 筛选基准日期，可选
        }
        
        filter = StockFilger()

        def Progress():
            stocks = manager.get_stock_list()

            index = 0
            maxNum =  len(stocks)
            resultData = []
            signals = []
            avg_returnAll = 0.0
            positive_probAll = 0.0
            for stock in stocks:
                logger.info(f"{index}/{maxNum}更新股票：{stock['code']} -- {stock['name']}")
                code = stock['code']
                #code = '001323'
                manager.update_stock_history(code)
               
                df = manager.get_stock_data(code, 365)
                filterSignals = data['filterSignal']
                dayRange = data['dayRange']
                target_date = data.get('targetDate')
                signal, avg_return, positive_prob = filter.filter_stock(
                    df, dayRange, filterSignals, target_date=target_date
                )
                newData = {"code": code, "avg_return": "{:.2f}".format(float(avg_return)), "positive_prob" : "{:.2f}".format(float(positive_prob) * 100)}
                resultData.append(newData)
                avg_returnAll = avg_returnAll + float(avg_return)
                positive_probAll = positive_probAll + float(positive_prob)
                if signal != None:
                    signals.append(signal)
                index = index + 1
                # 更新进度信息
                progress = {
                    'type': 'progress',
                    'current': index,
                    'total': maxNum,
                    'current_stock': "a",#stock['code'],
                    'matched_count': 1#len(matched_stocks)
                }
                delay = config.get('DEFAULT', 'UPDATE_STOCKS_DELAY')
                time.sleep(float(delay))
                yield f"data: {json.dumps(progress)}\n\n"
                #signalMsg = ""
                #if index == 2:
                #    break
                ''''if isCheckSingle:
                    signalMsg = checkFunc(stock['code'], self)# check_signal.CheckSingle(stock['code'], self)
                if signalMsg != None and signalMsg != "":
                    outMessage = outMessage + signalMsg + "\n"'''
            avg_returnAll = avg_returnAll / index
            positive_probAll = positive_probAll / index
            print(f"平均上涨幅度:{avg_returnAll},  平均上涨概率： {positive_probAll}")
            msg = filter.SignalToWeChatData(signals)
            print(msg)
            with open("output.csv", "w", newline="", encoding="utf-8") as file:
                fieldnames = ["code", "avg_return", "positive_prob"]  # 定义列名
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()  # 自动写入标题行
                writer.writerows(resultData)  # 写入多行数据
            SendSignalMessages(msg)
             # 发送最终结果
            final_result = {
                'type': 'result',
                'success': True,
                'data': "matched_stocks",
                'progress': {
                    'current': maxNum,
                    'total': maxNum,
                    'matched_count': 10
                }
            }
            yield f"data: {json.dumps(final_result)}\n\n"

        
                
        
        '''return jsonify({
            'success': True,
            'data': results
        })'''
        
    except Exception as e:
        logger.error(f"股票筛选失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }) 
    return Response(stream_with_context(Progress()), mimetype='text/event-stream')

##########################################Scan Routes########################################
@bp.route('/api/save-timed-scan', methods=['POST'])
def SaveTimedScan():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "请求体为空"}), 400
    scanManager = ScanManager()
    success, response = scanManager.SaveTimedScan(data)
    return response if success else (response, 500)

@bp.route('/api/get-timed-scan-list', methods=['GET'])
def get_TimedScan_List():
    """定时扫描列表，返回 JSON 数组 [{id, name}, ...]"""
    try:
        scanManager = ScanManager()
        items = scanManager.GetTimedScanList()
        return jsonify(items)
    except Exception as e:
        logger.error("获取定时扫描列表失败: %s", str(e), exc_info=True)
        return jsonify({"error": str(e)}), 500

##########################################Scan Routes########################################



########################股票实时数据######################
# 存储活跃的WebSocket连接
active_connections = {}

socketio = stockGlobal.socketio

# WebSocket连接处理
'''
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')
    # 清理连接
    for stock_code in list(active_connections.keys()):
        if request.sid in active_connections[stock_code]:
            active_connections[stock_code].remove(request.sid)
            if not active_connections[stock_code]:
                del active_connections[stock_code]
                '''