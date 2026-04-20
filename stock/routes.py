from flask import (Blueprint,
                   render_template,
                   jsonify,
                   request,
                   session,
                   Response,
                   stream_with_context,
                   redirect,
                   url_for,
                   current_app)
from stocks.stock_fetcher import StockFetcher
from stocks.stock_analyzer import StockAnalyzer
from database.database import Database
from indicator_manager import IndicatorManager
import logging
import json
import pandas as pd
import numpy as np
from datetime import date, datetime, time, timedelta
import os
import subprocess
import schedule
import time as time_module
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
from Managers.feishu_bot import feishu_signal_send_batch
from Managers.notify_channel import send_notify_fallback, send_notify_to_group
from stock_gatter.stockgetter_btc import StockGetter_BTC
from signals.signal_notify_system import (
    create_signal_instance,
    SendType,
    SignalConfig,
    SignalMessageTemplate,
    SingleManager,
    SingleType,
    validate_signal_rule_payload,
)
from signals.signal_notify_runner import run_signal_notify_for_stock, run_signal_notify_tick
from signals.signal_notify_card import (
    build_public_card_url,
    decode_notify_card_payload,
    notify_card_context_for_template,
)
import csv
import tempfile
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from Managers.scheduler_system import TaskConfig, TriggerType

from tasks.daily_tushare_sync import get_tracked_stocks_list, run_daily_tushare_sync
from tasks.adj_factor_sync import run_sync_all_tracked_adj_factors

from backtest.engine import normalize_stock_code, run_ma_crossover_backtest
from backtest.types import BacktestInput

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


def _test_trigger_runtime_state(signal_type: SingleType) -> dict:
    """测试触发时不读库；到价提醒用空状态以便当次条件满足即可发一条。"""
    if signal_type == SingleType.PRICE_LEVEL_INTERVAL:
        return {}
    return {"sent_lower": False, "sent_upper": False, "last_notified_date": ""}


def _send_signal_to_group(group_id: int, message: str):
    """
    信号系统发送适配器（与 NGA/LOF 等同通道）：
    多 group_id 时请在调用侧用 feishu_signal_send_batch 包裹，飞书单 Webhook 同正文只发一次。
    """
    try:
        send_notify_to_group(group_id, message)
    except Exception as e:
        logger.error("发送信号消息失败: %s", e, exc_info=True)


def _send_signal_to_group_with_optional_card(feishu_signal_payload: Optional[Dict[str, Any]] = None):
    """
    返回 (group_id, message) -> None，可附带模板 payload 以便飞书在开关开启时发送卡片图。
    """

    def _inner(group_id: int, message: str):
        try:
            send_notify_to_group(
                group_id,
                message,
                feishu_signal_payload=feishu_signal_payload,
            )
        except Exception as e:
            logger.error("发送信号消息失败: %s", e, exc_info=True)

    return _inner


def _signal_test_card_image_status(group_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """测试信号接口返回：说明为何可能未发飞书卡片图，并列出 group 配置缺失点。"""
    from Managers.feishu_group_manager import FeishuGroupManager
    from Managers.runtime_settings import get_feishu_signal_send_card_image, get_notify_channel

    ch = get_notify_channel()
    img_on = get_feishu_signal_send_card_image()
    gids = [int(x) for x in (group_ids or []) if x is not None]
    hints: List[str] = []
    group_checks: List[Dict[str, Any]] = []

    if ch != "feishu":
        hints.append(
            f"当前全局通知渠道为「{ch}」；卡片 PNG 仅走飞书。请在配置中将 [NOTIFY] channel 设为 feishu。"
        )
    if not img_on:
        hints.append(
            "未开启发图开关：在 DB 或 config.ini 设置 [SIGNAL_NOTIFY] feishu_send_card_image = 1（或 true/yes/on）。"
        )

    if ch == "feishu" and img_on:
        gm = FeishuGroupManager()
        for gid in gids:
            g = gm.get(int(gid))
            if g is None:
                group_checks.append(
                    {
                        "group_id": int(gid),
                        "ok": False,
                        "reason": "该 group_id 未在「群组管理」中配置 list_type=feishu",
                    }
                )
                continue
            has_creds = bool((g.app_id or "").strip()) and bool((g.app_secret or "").strip())
            group_checks.append(
                {
                    "group_id": int(gid),
                    "send_mode": g.send_mode,
                    "has_webhook_url": bool((g.webhook_url or "").strip()),
                    "has_chat_id": bool((g.chat_id or "").strip()),
                    "has_app_credentials": has_creds,
                    "ok_for_image_upload": bool(has_creds),
                }
            )
        hints.append(
            "若仍无图：需要飞书应用具备机器人与上传图片权限；并查看服务端日志中的「飞书信号卡片图未发送」后缀原因（token/上传/发图失败）。"
        )

    return {
        "notify_channel": ch,
        "feishu_send_card_image": img_on,
        "card_image_will_attempt": (ch == "feishu" and img_on),
        "group_checks": group_checks,
        "card_image_hints": hints,
    }


def _run_signal_notify_for_stock(stock_code: str, price: float) -> List[str]:
    """兼容旧调用点：逻辑迁移到 signals/signal_notify_runner.py。"""
    return run_signal_notify_for_stock(stock_code, float(price))

def _get_tracked_stocks():
    """获取已跟踪的股票列表，优先 stock_list，否则回退到扫描已有的 stock_XXXXXX_XX 表"""
    return get_tracked_stocks_list(manager)


def _parse_quant_iso_date(value) -> Optional[date]:
    """解析 YYYY-MM-DD 或 YYYYMMDD，失败返回 None。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("-", "")
    if len(s) == 8 and s.isdigit():
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            return None
    if len(s) >= 8:
        try:
            return datetime.strptime(s[:10].replace("-", ""), "%Y%m%d").date()
        except ValueError:
            pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


@bp.route('/')
def index():
    # 默认主页：DSA Web 工作台
    return render_template('dsaweb.html')


@bp.route('/classic')
def classic_home():
    """传统首页（原 /）。"""
    return render_template('index.html')

@bp.route('/quant')
def quant():
    """量化功能专用页面"""
    return render_template('quant.html')


@bp.route('/quant/backtest')
def quant_backtest_page():
    """双均线策略回测页面"""
    return render_template('quant_backtest.html')


@bp.route('/api/quant/backtest', methods=['POST'])
def api_quant_backtest():
    """执行本地日线双均线回测，返回 JSON。"""
    payload = request.get_json(silent=True) or {}
    code = normalize_stock_code(str(payload.get("stock_code", "") or ""))
    if not code:
        return jsonify({"success": False, "message": "股票代码无效（需 6 位数字，如 600000）"}), 400

    d0 = _parse_quant_iso_date(payload.get("start_date"))
    d1 = _parse_quant_iso_date(payload.get("end_date"))
    if d0 is None or d1 is None:
        return jsonify({"success": False, "message": "起止日期格式无效，请使用 YYYY-MM-DD"}), 400
    if d0 > d1:
        return jsonify({"success": False, "message": "开始日期不能晚于结束日期"}), 400

    try:
        short_w = int(payload.get("short_window", 5))
        long_w = int(payload.get("long_window", 20))
        initial_cash = float(payload.get("initial_cash", 100_000))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "参数 short_window / long_window / initial_cash 无效"}), 400

    if initial_cash <= 0:
        return jsonify({"success": False, "message": "初始资金必须大于 0"}), 400

    try:
        manager.update_stock_history(code)
    except Exception as e:
        logger.warning("回测前更新 %s 行情失败，继续读本地: %s", code, e)

    df = manager.get_stock_data_range(code, d0, d1)
    inp = BacktestInput(
        stock_code=code,
        start_date=d0.isoformat(),
        end_date=d1.isoformat(),
        strategy="ma_crossover",
        short_window=short_w,
        long_window=long_w,
        initial_cash=initial_cash,
    )
    result = run_ma_crossover_backtest(df, inp)
    if not result.success:
        return jsonify({"success": False, "message": result.error or "回测失败"}), 400
    return jsonify({"success": True, "data": result.to_api_dict()})


@bp.route('/dsaweb')
def dsaweb():
    """DSA Web 页面"""
    return render_template('dsaweb.html')


@bp.route('/signal_notify')
def signal_notify():
    """股票信号通知配置页面（含悬浮配置层）"""
    return render_template('signal_notify.html')


@bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    """读取系统设置（DB 优先，缺失回退 config.ini）。"""
    try:
        defaults = {
            "DATABASE": {
                "DB_TYPE": "mysql",
                "DB_HOST": "",
                "DB_PORT": "",
                "DB_NAME": "",
                "DB_USER": "",
                "DB_PASSWORD": "",
                "DB_CHARSET": "",
                "DB_PATH": "",
            },
            "REDIS": {
                "enabled": "0",
                "host": "127.0.0.1",
                "port": "6379",
                "db": "0",
                "password": "",
                "key_prefix": "stock",
                "socket_timeout_seconds": "0.5",
                # 读缓存 TTL（秒）
                "latest_close_ttl_seconds": "10",
                "stock_name_ttl_seconds": "3600",
                # 写缓冲：信号 state 先写 Redis，再异步落库
                "signal_state_buffer_enabled": "0",
                "signal_state_flush_interval_seconds": "3",
                "signal_state_flush_batch_size": "500",
            },
            "NOTIFY": {
                "channel": "wx",
                "message_group": "",
                "fallback_group_id": "",
                "filter_result_group_ids": "",
            },
            "TUSHARE": {
                "TOKEN": "",
            },
            "SIGNAL_NOTIFY": {
                "update_interval_seconds": "15",
                "price_source": "db_latest_close_qfq",
                "missing_adj_factor_policy": "skip",
                "feishu_send_card_image": "0",
                "send_text_enabled": "1",
            },
        }
        from Managers.runtime_settings import get_all_settings_merged

        return jsonify({"success": True, "settings": get_all_settings_merged(defaults), "require_restart": False})
    except Exception as e:
        logger.error("读取 settings 失败: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "服务器内部错误"}), 500


@bp.route('/api/settings', methods=['PUT'])
def api_put_settings():
    """保存系统设置到 DB（并不改写 config.ini）。"""
    try:
        data = request.get_json(silent=True) or {}
        settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        db = Database.Create()
        try:
            db.ensure_system_settings_tables()
            for section, kv in (settings or {}).items():
                if not isinstance(kv, dict):
                    continue
                for k, v in kv.items():
                    db.upsert_system_setting(str(section), str(k), v)
        finally:
            db.close()
        # 这里返回 require_restart=true：部分配置（比如 DB_TYPE）需要重启才能在全局生效
        return jsonify({"success": True, "require_restart": True})
    except Exception as e:
        logger.error("保存 settings 失败: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "服务器内部错误"}), 500


@bp.route('/scheduled_tasks')
def scheduled_tasks_page():
    """APScheduler 定时任务管理页（配置存数据库 scheduled_task）。"""
    return render_template('scheduled_tasks.html')


@bp.route('/settings_console')
def settings_console():
    """系统设置中心（DB 优先，缺失回退 config.ini）。"""
    return render_template('settings_console.html')


def _get_task_manager():
    """main.py 在启动时注入 app.config['TASK_MANAGER']。"""
    return current_app.config.get('TASK_MANAGER')


def _scheduled_task_api_dict(tm, task_id: str, cfg: TaskConfig) -> dict:
    job = tm.scheduler.get_job(task_id)
    next_run: Optional[str] = None
    paused = False
    in_sched = job is not None
    if job:
        if job.next_run_time:
            next_run = job.next_run_time.isoformat()
        elif cfg.enabled:
            paused = True
    row = cfg.to_dict()
    row['in_scheduler'] = in_sched
    row['next_run_time'] = next_run
    row['paused'] = paused
    return row


def _task_config_from_json(data: dict, task_id: Optional[str] = None) -> TaskConfig:
    tid = (task_id or data.get('task_id') or '').strip()
    if not tid:
        raise ValueError('task_id 不能为空')
    if not (data.get('module_path') or '').strip():
        raise ValueError('module_path 不能为空')
    if not (data.get('function_name') or '').strip():
        raise ValueError('function_name 不能为空')
    tt = (data.get('trigger_type') or 'cron').strip().lower()
    if tt not in ('cron', 'interval', 'date'):
        raise ValueError('trigger_type 必须是 cron / interval / date')
    trigger_args = data.get('trigger_args')
    if isinstance(trigger_args, str):
        trigger_args = json.loads(trigger_args)
    if not isinstance(trigger_args, dict):
        raise ValueError('trigger_args 必须为 JSON 对象')
    mg = data.get('misfire_grace_time')
    if mg is not None:
        mg = int(mg)
    return TaskConfig(
        task_id=tid,
        task_name=(data.get('task_name') or tid).strip(),
        module_path=(data.get('module_path') or '').strip(),
        function_name=(data.get('function_name') or '').strip(),
        trigger_type=TriggerType(tt),
        trigger_args=trigger_args,
        run_once_per_day=bool(data.get('run_once_per_day', False)),
        enabled=bool(data.get('enabled', True)),
        max_instances=int(data.get('max_instances', 1)),
        misfire_grace_time=mg,
        coalesce=bool(data.get('coalesce', True)),
        description=(data.get('description') or '').strip(),
        args=tuple(data.get('args') or ()),
        kwargs=data.get('kwargs') if isinstance(data.get('kwargs'), dict) else {},
    )


@bp.route('/api/scheduled_tasks', methods=['GET'])
def api_scheduled_tasks_list():
    tm = _get_task_manager()
    if tm is None:
        return jsonify({'success': False, 'message': '定时任务管理器未初始化'}), 503
    try:
        out = []
        for task_id, cfg in sorted(tm.tasks.items(), key=lambda x: x[0]):
            out.append(_scheduled_task_api_dict(tm, task_id, cfg))
        return jsonify({'success': True, 'tasks': out})
    except Exception as e:
        logger.error('列出定时任务失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/scheduled_tasks', methods=['POST'])
def api_scheduled_tasks_create():
    tm = _get_task_manager()
    if tm is None:
        return jsonify({'success': False, 'message': '定时任务管理器未初始化'}), 503
    try:
        data = request.get_json(silent=True) or {}
        cfg = _task_config_from_json(data)
        if cfg.task_id in tm.tasks:
            return jsonify({'success': False, 'message': 'task_id 已存在，请使用更新接口'}), 400
        if not tm.upsert_task(cfg):
            return jsonify({'success': False, 'message': '任务注册失败（检查模块与触发器）'}), 400
        db = Database.Create()
        try:
            if not tm.persist_task_to_database(db, tm.tasks[cfg.task_id]):
                return jsonify({'success': False, 'message': '写入数据库失败'}), 500
        finally:
            db.close()
        return jsonify({
            'success': True,
            'task': _scheduled_task_api_dict(tm, cfg.task_id, tm.tasks[cfg.task_id]),
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error('创建定时任务失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/scheduled_tasks/<task_id>', methods=['PUT'])
def api_scheduled_tasks_update(task_id: str):
    tm = _get_task_manager()
    if tm is None:
        return jsonify({'success': False, 'message': '定时任务管理器未初始化'}), 503
    try:
        data = request.get_json(silent=True) or {}
        tid = (data.get('task_id') or task_id).strip()
        if tid != task_id.strip():
            return jsonify({'success': False, 'message': '路径与 body 中的 task_id 不一致'}), 400
        if task_id.strip() not in tm.tasks:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        cfg = _task_config_from_json(data, task_id=task_id.strip())
        if not tm.upsert_task(cfg):
            return jsonify({'success': False, 'message': '任务更新失败（检查模块与触发器）'}), 400
        db = Database.Create()
        try:
            if not tm.persist_task_to_database(db, tm.tasks[cfg.task_id]):
                return jsonify({'success': False, 'message': '写入数据库失败'}), 500
        finally:
            db.close()
        return jsonify({
            'success': True,
            'task': _scheduled_task_api_dict(tm, cfg.task_id, tm.tasks[cfg.task_id]),
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error('更新定时任务失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/scheduled_tasks/<task_id>', methods=['DELETE'])
def api_scheduled_tasks_delete(task_id: str):
    tm = _get_task_manager()
    if tm is None:
        return jsonify({'success': False, 'message': '定时任务管理器未初始化'}), 503
    try:
        tid = task_id.strip()
        if tid not in tm.tasks:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        db = Database.Create()
        try:
            tm.delete_task_config(tid, db)
        finally:
            db.close()
        return jsonify({'success': True})
    except Exception as e:
        logger.error('删除定时任务失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/scheduled_tasks/<task_id>/pause', methods=['POST'])
def api_scheduled_tasks_pause(task_id: str):
    tm = _get_task_manager()
    if tm is None:
        return jsonify({'success': False, 'message': '定时任务管理器未初始化'}), 503
    tid = task_id.strip()
    if tid not in tm.tasks:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    if not tm.tasks[tid].enabled:
        return jsonify({'success': False, 'message': '任务已禁用，无法暂停调度'}), 400
    ok = tm.pause_task(tid)
    return jsonify({
        'success': ok,
        'message': '已暂停' if ok else '暂停失败（可能未在调度器中）',
        'task': _scheduled_task_api_dict(tm, tid, tm.tasks[tid]),
    })


@bp.route('/api/scheduled_tasks/<task_id>/resume', methods=['POST'])
def api_scheduled_tasks_resume(task_id: str):
    tm = _get_task_manager()
    if tm is None:
        return jsonify({'success': False, 'message': '定时任务管理器未初始化'}), 503
    tid = task_id.strip()
    if tid not in tm.tasks:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    if not tm.tasks[tid].enabled:
        return jsonify({'success': False, 'message': '任务已禁用，请先启用配置'}), 400
    ok = tm.resume_task(tid)
    return jsonify({
        'success': ok,
        'message': '已恢复' if ok else '恢复失败',
        'task': _scheduled_task_api_dict(tm, tid, tm.tasks[tid]),
    })


@bp.route('/api/signal_notify/editor_schema', methods=['GET'])
def signal_notify_editor_schema():
    """1.1：给其他页面复用的悬浮编辑器接口定义"""
    schema = SingleManager.get_floating_editor_schema()
    return jsonify({'success': True, 'schema': schema})


@bp.route('/api/signal_notify/signals', methods=['GET'])
def signal_notify_list():
    """查看当前已注册信号"""
    db = Database.Create()
    try:
        stock_code = (request.args.get('stock_code') or '').strip()
        only_active_raw = (request.args.get('only_active') or 'true').strip().lower()
        only_active = only_active_raw not in ('0', 'false', 'no', 'off')
        rows = db.get_signal_rules(stock_code=stock_code or None, only_active=only_active)
        out = []
        for r in rows or []:
            out.append({
                'id': r.get('id'),
                'stock_code': r.get('stock_code'),
                'stock_name': r.get('stock_name') or '',
                'group_ids': json.loads(r.get('group_ids_json') or '[]'),
                'signal_type': r.get('signal_type'),
                'params': json.loads(r.get('params_json') or '{}'),
                'message_template': r.get('message_template') or '',
                'send_type': r.get('send_type') or SendType.ON_TRIGGER.value,
                'send_interval_seconds': int(r.get('send_interval_seconds') or 0),
                'is_active': int(r.get('is_active') or 0),
            })
        return jsonify({'success': True, 'signals': out})
    except Exception as e:
        logger.error("读取 signal_rule 失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500
    finally:
        db.close()


@bp.route('/api/signal_notify/signals', methods=['POST'])
def signal_notify_create():
    """1.2/1.3：创建一个信号（当前支持股价区间信号）"""
    try:
        data = request.get_json() or {}
        stock_code = (data.get('stock_code') or '').strip()
        stock_name = (data.get('stock_name') or '').strip()
        group_ids = data.get('group_ids') or []
        params = data.get('params') or {}
        signal_type_raw = (data.get('signal_type') or SingleType.PRICE_RANGE.value).strip()
        send_type_raw = (data.get('send_type') or SendType.ON_TRIGGER.value).strip()
        send_interval_seconds = int(data.get('send_interval_seconds') or 0)
        template_text = data.get('message_template') or SignalMessageTemplate().template

        if not stock_code:
            return jsonify({'success': False, 'message': 'stock_code 不能为空'}), 400
        if not isinstance(group_ids, list) or not group_ids:
            return jsonify({'success': False, 'message': 'group_ids 不能为空且必须是数组'}), 400
        try:
            signal_type = SingleType(signal_type_raw)
        except ValueError:
            valid_types = [x.value for x in SingleType]
            return jsonify({'success': False, 'message': f'signal_type 非法，可选: {valid_types}'}), 400

        normalized_group_ids = []
        for gid in group_ids:
            try:
                normalized_group_ids.append(int(gid))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': f'group_id 非法: {gid}'}), 400

        # 按全局通知渠道校验 group_ids 是否存在（规则侧仅保存 group_id）
        from Managers.runtime_settings import get_notify_channel
        notify_ch = get_notify_channel()
        db = Database.Create()
        try:
            db.ensure_message_group_tables()
            list_type = "feishu" if notify_ch == "feishu" else "weixin"
            existing = {
                int(r.get("group_id"))
                for r in (db.get_all_message_groups(list_type=list_type) or [])
                if r.get("group_id") is not None
            }
        finally:
            db.close()
        missing = [gid for gid in normalized_group_ids if gid not in existing]
        if missing:
            return jsonify({'success': False, 'message': f'group_id 未配置（{list_type}）：{missing}'}), 400

        # 若前端未传 stock_name，则尽量从 stock_basic 补全（用于通知卡片图展示）
        if not stock_name:
            dbn = Database.Create()
            try:
                nm = _lookup_stock_name_from_basic(dbn, stock_code)
                if nm:
                    stock_name = str(nm).strip()
            finally:
                dbn.close()

        config = SignalConfig(
            stock_code=stock_code,
            stock_name=stock_name,
            group_ids=normalized_group_ids,
            signal_type=signal_type,
            params=params,
            message_template=SignalMessageTemplate(template=template_text),
            send_type=SendType(send_type_raw),
            send_interval_seconds=send_interval_seconds,
        )
        # 创建一次实例用于参数校验（如 lower/upper 合法性）
        _ = SingleManager().add_signal(config)

        db = Database.Create()
        try:
            ok, ret = db.create_signal_rule(
                stock_code=stock_code,
                stock_name=stock_name,
                group_ids_json=json.dumps(normalized_group_ids, ensure_ascii=False),
                signal_type=signal_type_raw,
                params_json=json.dumps(params, ensure_ascii=False),
                message_template=template_text,
                send_type=send_type_raw,
                send_interval_seconds=send_interval_seconds,
                is_active=1,
            )
            if not ok:
                return jsonify({'success': False, 'message': f'持久化失败: {ret}'}), 500
            return jsonify({'success': True, 'message': '信号创建成功', 'id': ret})
        finally:
            db.close()
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error("创建信号失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/signal_notify/signals/<int:rule_id>', methods=['PUT'])
def signal_notify_update(rule_id: int):
    """编辑信号规则（用于自选列表逐行编辑）"""
    try:
        data = request.get_json() or {}
        stock_name = data.get('stock_name')
        group_ids = data.get('group_ids')
        params = data.get('params')
        message_template = data.get('message_template')
        send_type = data.get('send_type')
        send_interval_seconds = data.get('send_interval_seconds')
        is_active = data.get('is_active')

        group_ids_json = None
        normalized = None
        if group_ids is not None:
            if not isinstance(group_ids, list):
                return jsonify({'success': False, 'message': 'group_ids 必须是数组'}), 400
            normalized = []
            for gid in group_ids:
                try:
                    normalized.append(int(gid))
                except (TypeError, ValueError):
                    return jsonify({'success': False, 'message': f'group_id 非法: {gid}'}), 400
            group_ids_json = json.dumps(normalized, ensure_ascii=False)

        params_json = None
        if params is not None:
            if not isinstance(params, dict):
                return jsonify({'success': False, 'message': 'params 必须是对象'}), 400
            params_json = json.dumps(params, ensure_ascii=False)

        if send_type is not None and send_type not in (SendType.ON_TRIGGER.value, SendType.INTERVAL.value):
            return jsonify({'success': False, 'message': 'send_type 非法'}), 400

        db = Database.Create()
        try:
            row = db.fetch_one(
                'SELECT signal_type, params_json, message_template, send_type, send_interval_seconds '
                'FROM signal_rule WHERE id = %s',
                (int(rule_id),),
            )
            if not row:
                return jsonify({'success': False, 'message': '规则不存在'}), 404

            # stock_name 允许为空字符串，但为了卡片图展示，若用户显式提交空且 stock_basic 能查到，则自动补全
            if stock_name is not None:
                sn = str(stock_name or "").strip()
                if not sn:
                    nm = _lookup_stock_name_from_basic(db, str(data.get("stock_code") or "") or "")
                    # 更新接口未传 stock_code 时无法查 basic；这里改用 DB 内 stock_code
                    if not nm:
                        try:
                            r2 = db.fetch_one("SELECT stock_code FROM signal_rule WHERE id=%s", (int(rule_id),))
                            nm = _lookup_stock_name_from_basic(db, (r2 or {}).get("stock_code") or "")
                        except Exception:
                            nm = None
                    if nm:
                        stock_name = str(nm).strip()

            merged_params = json.loads(row.get('params_json') or '{}')
            if params is not None:
                merged_params = dict(params)
            merged_msg = (
                message_template
                if message_template is not None
                else (row.get('message_template') or '')
            )
            merged_send_type = send_type if send_type is not None else row.get('send_type')
            merged_interval = (
                send_interval_seconds
                if send_interval_seconds is not None
                else row.get('send_interval_seconds')
            )
            try:
                validate_signal_rule_payload(
                    signal_type=SingleType(row.get('signal_type') or SingleType.PRICE_RANGE.value),
                    params=merged_params,
                    send_type=SendType(merged_send_type or SendType.ON_TRIGGER.value),
                    send_interval_seconds=int(merged_interval or 0),
                    message_template=merged_msg,
                )
            except ValueError as ve:
                return jsonify({'success': False, 'message': str(ve)}), 400

            # 若更新了 group_ids，则按全局通知渠道校验其存在
            if normalized is not None:
                from Managers.runtime_settings import get_notify_channel
                notify_ch = get_notify_channel()
                list_type = "feishu" if notify_ch == "feishu" else "weixin"
                db.ensure_message_group_tables()
                existing = {
                    int(r.get("group_id"))
                    for r in (db.get_all_message_groups(list_type=list_type) or [])
                    if r.get("group_id") is not None
                }
                missing = [gid for gid in normalized if gid not in existing]
                if missing:
                    return jsonify({'success': False, 'message': f'group_id 未配置（{list_type}）：{missing}'}), 400

            db.update_signal_rule(
                rule_id=rule_id,
                stock_name=stock_name,
                group_ids_json=group_ids_json,
                params_json=params_json,
                message_template=message_template,
                send_type=send_type,
                send_interval_seconds=send_interval_seconds,
                is_active=is_active,
            )
            return jsonify({'success': True})
        finally:
            db.close()
    except Exception as e:
        logger.error("更新 signal_rule 失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/signal_notify/update_price', methods=['POST'])
def signal_notify_update_price():
    """
    用于交易时间刷新时调用：更新某只股票价格并检查触发。
    body: { stock_code, price }
    """
    try:
        data = request.get_json() or {}
        stock_code = (data.get('stock_code') or '').strip()
        price = data.get('price')
        if not stock_code:
            return jsonify({'success': False, 'message': 'stock_code 不能为空'}), 400
        try:
            price = float(price)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'price 必须为数值'}), 400

        # 约定：该接口传入 price 为“未复权实时价”，后端会用 adj_factor 转为前复权再做触发计算
        messages = _run_signal_notify_for_stock(stock_code=stock_code, price=price)
        return jsonify({'success': True, 'triggered': len(messages), 'messages': messages})
    except Exception as e:
        logger.error("更新价格并检查信号失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/signal_notify/test_trigger', methods=['POST'])
def signal_notify_test_trigger():
    """
    测试信号触发：
    - 满足条件即发送
    - 无视历史发送状态（不读取/不写入 signal_rule_state）
    """
    try:
        data = request.get_json() or {}
        stock_code = (data.get('stock_code') or '').strip()
        price = data.get('price')
        if not stock_code:
            return jsonify({'success': False, 'message': 'stock_code 不能为空'}), 400
        try:
            price = float(price)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'price 必须为数值'}), 400

        db = Database.Create()
        try:
            rows = db.get_signal_rules(stock_code=stock_code, only_active=True)
        finally:
            db.close()

        # 约定：测试触发传入 price 为“未复权价”，后端用 adj_factor 转为前复权做比较
        db2 = Database.Create()
        try:
            af_row = db2.get_latest_adj_factor_row(stock_code)
        finally:
            db2.close()
        if not af_row or af_row.get("adj_factor") is None:
            return jsonify({'success': False, 'message': '缺少复权因子(adj_factor)，无法按前复权口径测试'}), 400
        try:
            qfq_price = float(price) * float(af_row.get("adj_factor"))
        except Exception:
            return jsonify({'success': False, 'message': '复权因子转换失败'}), 400

        messages = []
        used_group_ids: List[int] = []
        for r in rows or []:
            try:
                st = SingleType(r.get('signal_type') or SingleType.PRICE_RANGE.value)
                signal = create_signal_instance(
                    SignalConfig(
                        stock_code=r.get('stock_code') or '',
                        stock_name=r.get('stock_name') or '',
                        group_ids=json.loads(r.get('group_ids_json') or '[]'),
                        signal_type=st,
                        params=json.loads(r.get('params_json') or '{}'),
                        message_template=SignalMessageTemplate(
                            template=r.get('message_template') or SignalMessageTemplate().template
                        ),
                        send_type=SendType(r.get('send_type') or SendType.ON_TRIGGER.value),
                        send_interval_seconds=int(r.get('send_interval_seconds') or 0),
                        runtime_state=_test_trigger_runtime_state(st),
                    )
                )
                new_messages = signal.update(qfq_price)
                payloads = signal.take_trigger_payloads()
                try:
                    used_group_ids.extend([int(x) for x in signal.config.group_ids or [] if x is not None])
                except Exception:
                    pass
                for idx, msg in enumerate(new_messages):
                    pl = payloads[idx] if idx < len(payloads) else None
                    with feishu_signal_send_batch():
                        signal.send_message(msg, _send_signal_to_group_with_optional_card(pl))
                    messages.append(msg)
            except Exception as e:
                logger.warning("测试触发 signal_rule(id=%s) 失败，已跳过: %s", r.get('id'), e)

        return jsonify(
            {
                "success": True,
                "triggered": len(messages),
                "messages": messages,
                "card_image_status": _signal_test_card_image_status(used_group_ids),
            }
        )
    except Exception as e:
        logger.error("测试触发信号失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/signal_notify/test_trigger_realtime', methods=['POST'])
def signal_notify_test_trigger_realtime():
    """
    点击“测试信号”时使用实时股价进行测试触发：
    - 自动拉取实时价
    - 满足条件即发送
    - 无视历史发送状态
    """
    try:
        data = request.get_json() or {}
        stock_code = (data.get('stock_code') or '').strip()
        if not stock_code:
            return jsonify({'success': False, 'message': 'stock_code 不能为空'}), 400

        from stocks.stock_quote_tencent import fetch_quotes
        quotes = fetch_quotes([stock_code]) or {}
        quote = None
        if stock_code in quotes:
            quote = quotes.get(stock_code)
        if quote is None:
            base = stock_code.split('.', 1)[0]
            for key in (base, f"sh{base}", f"sz{base}", f"bj{base}", f"hk{base.zfill(5)}"):
                if key in quotes:
                    quote = quotes.get(key)
                    break
        if quote is None or quote.now is None:
            return jsonify({'success': False, 'message': '未获取到实时股价'}), 400

        # 约定：腾讯实时价按未复权输入，后端用 adj_factor 转为前复权做比较
        price = float(quote.now)
        
        
        # 复用测试逻辑：直接本地执行，避免二次 HTTP 调用
        db = Database.Create()
        try:
            rows = db.get_signal_rules(stock_code=stock_code, only_active=True)
        finally:
            db.close()

        messages = []
        used_group_ids: List[int] = []
        for r in rows or []:
            try:
                st = SingleType(r.get('signal_type') or SingleType.PRICE_RANGE.value)
                signal = create_signal_instance(
                    SignalConfig(
                        stock_code=r.get('stock_code') or '',
                        stock_name=r.get('stock_name') or '',
                        group_ids=json.loads(r.get('group_ids_json') or '[]'),
                        signal_type=st,
                        params=json.loads(r.get('params_json') or '{}'),
                        message_template=SignalMessageTemplate(
                            template=r.get('message_template') or SignalMessageTemplate().template
                        ),
                        send_type=SendType(r.get('send_type') or SendType.ON_TRIGGER.value),
                        send_interval_seconds=int(r.get('send_interval_seconds') or 0),
                        runtime_state=_test_trigger_runtime_state(st),
                    )
                )
                new_messages = signal.update(price)
                payloads = signal.take_trigger_payloads()
                try:
                    used_group_ids.extend([int(x) for x in signal.config.group_ids or [] if x is not None])
                except Exception:
                    pass
                for idx, msg in enumerate(new_messages):
                    pl = payloads[idx] if idx < len(payloads) else None
                    with feishu_signal_send_batch():
                        signal.send_message(msg, _send_signal_to_group_with_optional_card(pl))
                    messages.append(msg)
            except Exception as e:
                logger.warning("测试触发(实时价) signal_rule(id=%s) 失败，已跳过: %s", r.get('id'), e)

        return jsonify(
            {
                "success": True,
                "price": price,
                "triggered": len(messages),
                "messages": messages,
                "card_image_status": _signal_test_card_image_status(used_group_ids),
            }
        )
    except Exception as e:
        logger.error("实时价测试触发失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/signal_notify/run_all', methods=['POST'])
def signal_notify_run_all():
    """
    手动执行一次全量信号扫描（用于非交易时间测试）。
    body: { force?: boolean }
    """
    try:
        data = request.get_json(silent=True) or {}
        force = bool(data.get('force', True))
        stats = run_signal_notify_tick(force=force)
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error("手动全量扫描失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/signal_notify/notify_card', methods=['GET'])
def signal_notify_notify_card_page():
    """
    浏览器查看通知卡片 HTML。可选查询参数 payload=urlsafe_base64(json)，
    与 POST /api/signal_notify/notify_card 的 JSON 体结构相同。
    无 payload 时使用默认占位内容。
    """
    try:
        token = (request.args.get('payload') or '').strip()
        if token:
            data = decode_notify_card_payload(token)
        else:
            data = {}
        ctx = notify_card_context_for_template(data)
        return render_template('signal_notify_card.html', **ctx)
    except ValueError as e:
        return f'<pre style="font-family:system-ui;padding:24px">参数错误: {e}</pre>', 400
    except Exception as e:
        logger.error("渲染 notify_card 失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/signal_notify/notify_card', methods=['POST'])
def signal_notify_notify_card_api():
    """
    根据 JSON 配置渲染与静态示例同风格的通知卡片 HTML（Content-Type: text/html）。
    可与 signal 的模板 payload 对接：传入 signal_payload 可自动生成 rows。
    """
    try:
        data = request.get_json(silent=True) or {}
        ctx = notify_card_context_for_template(data)
        return render_template('signal_notify_card.html', **ctx)
    except Exception as e:
        logger.error("API 渲染 notify_card 失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/signal_notify/notify_card_link', methods=['POST'])
def signal_notify_notify_card_link_api():
    """
    生成可分享的卡片链接（相对 path + 绝对 url）。
    body 与 /api/signal_notify/notify_card 相同；url 基于当前请求的 url_root。
    """
    try:
        data = request.get_json(silent=True) or {}
        path, abs_url = build_public_card_url(base_url=request.url_root, data=data)
        return jsonify({'success': True, 'path': path, 'url': abs_url})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error("生成 notify_card 链接失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/signal_notify/signals/<int:rule_id>/active', methods=['PUT'])
def signal_notify_set_active(rule_id: int):
    """启用/停用信号规则"""
    data = request.get_json() or {}
    is_active = data.get('is_active')
    if is_active is None:
        return jsonify({'success': False, 'message': '缺少 is_active'}), 400
    try:
        is_active = 1 if bool(is_active) else 0
        db = Database.Create()
        try:
            db.set_signal_rule_active(rule_id, is_active)
            return jsonify({'success': True})
        finally:
            db.close()
    except Exception as e:
        logger.error("设置 signal_rule 启用状态失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/signal_notify/signals/<int:rule_id>', methods=['DELETE'])
def signal_notify_delete(rule_id: int):
    """删除信号规则"""
    try:
        db = Database.Create()
        try:
            db.delete_signal_rule(rule_id)
            return jsonify({'success': True})
        finally:
            db.close()
    except Exception as e:
        logger.error("删除 signal_rule 失败: %s", e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500

@bp.route('/market_open_score')
def market_open_score():
    """今日大盘开盘评分"""
    return render_template('market_open_score.html')


def _get_positions_with_market(user_id: int):
    """
    获取指定用户的持仓信息以及当前价/总市值（只读视图）。
    当前价来自 stock_data 中该股票最近一个交易日的 close。
    """
    db = Database.Create()
    try:
        from datetime import datetime as _dt
        uid = int(user_id)
        # 兼容 SQLite / MySQL 的最近交易日查询
        if db.is_sqlite:
            sql = """
                SELECT
                    p.id,
                    p.stock_code,
                    COALESCE(p.stock_name, s.name) AS stock_name,
                    p.quantity,
                    p.cost_price,
                    p.created_at,
                    sd.close AS current_price,
                    CASE
                        WHEN sd.close IS NOT NULL THEN p.quantity * sd.close
                        ELSE NULL
                    END AS total_value
                FROM positions p
                LEFT JOIN stocks s ON s.code = p.stock_code
                LEFT JOIN stock_data sd
                  ON sd.stock_code = p.stock_code
                 AND sd.trade_date = (
                    SELECT MAX(sd2.trade_date)
                    FROM stock_data sd2
                    WHERE sd2.stock_code = p.stock_code
                 )
                WHERE p.user_id = %s
                ORDER BY p.id DESC
            """
        else:
            sql = """
                SELECT
                    p.id,
                    p.stock_code,
                    COALESCE(p.stock_name, s.name) AS stock_name,
                    p.quantity,
                    p.cost_price,
                    p.created_at,
                    sd.close AS current_price,
                    CASE
                        WHEN sd.close IS NOT NULL THEN p.quantity * sd.close
                        ELSE NULL
                    END AS total_value
                FROM positions p
                LEFT JOIN stocks s ON s.code = p.stock_code
                LEFT JOIN stock_data sd
                  ON sd.stock_code = p.stock_code
                 AND sd.trade_date = (
                    SELECT MAX(sd2.trade_date)
                    FROM stock_data sd2
                    WHERE sd2.stock_code = p.stock_code
                 )
                WHERE p.user_id = %s
                ORDER BY p.id DESC
            """
        rows = db.fetch_all(sql, (uid,)) or []
        _fill_positions_stock_name_from_basic(db, rows)

        # 计算持仓天数：按日期计算（首次买入 trade_date -> 今天日期；查不到则回退 created_at）
        today = _dt.now().date()
        # 1) 批量取每个持仓股票的首次买入日期
        first_buy_map = {}
        try:
            codes = [r.get("stock_code") for r in rows if r.get("stock_code")]
            codes = sorted(set([c for c in codes if isinstance(c, str) and c.strip()]))
            if codes:
                if db.is_sqlite:
                    placeholders = ",".join(["?"] * len(codes))
                else:
                    placeholders = ",".join(["%s"] * len(codes))
                buy_rows = db.fetch_all(
                    f"""
                    SELECT stock_code, MIN(trade_date) AS first_buy_date
                    FROM transactions
                    WHERE action='buy' AND user_id = %s AND stock_code IN ({placeholders})
                    GROUP BY stock_code
                    """,
                    tuple([uid] + codes),
                )
                for br in buy_rows or []:
                    sc = br.get("stock_code")
                    fd = br.get("first_buy_date")
                    if sc and fd:
                        first_buy_map[sc] = fd
        except Exception:
            first_buy_map = {}

        for r in rows:
            holding_days = None
            try:
                stock_code = r.get("stock_code")
                base_date_raw = first_buy_map.get(stock_code)
                base_date = None

                if isinstance(base_date_raw, str):
                    # trade_date 一般为 'YYYY-MM-DD'
                    try:
                        base_date = _dt.strptime(base_date_raw, "%Y-%m-%d").date()
                    except ValueError:
                        base_date = _dt.fromisoformat(base_date_raw.replace("Z", "+00:00")).date()
                elif hasattr(base_date_raw, "date"):
                    base_date = base_date_raw.date()

                if base_date is None:
                    created_at = r.get("created_at")
                    if isinstance(created_at, str):
                        created_dt = None
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                            try:
                                created_dt = _dt.strptime(created_at, fmt)
                                break
                            except ValueError:
                                continue
                        if created_dt is None:
                            created_dt = _dt.fromisoformat(created_at.replace("Z", "+00:00"))
                        base_date = created_dt.date()
                    elif hasattr(created_at, "date"):
                        base_date = created_at.date()

                if base_date:
                    holding_days = (today - base_date).days
            except Exception:
                holding_days = None
            r["holding_days"] = holding_days
        return rows
    except Exception as e:
        logger.error("获取持仓信息失败: %s", e, exc_info=True)
        return []
    finally:
        db.close()


def _normalize_stock_code_for_basic(stock_code: str) -> str:
    """
    将业务中可能出现的股票代码规范化为 stock_basic.code 形式（通常为 A 股 6 位数字）。
    例：600000.SS / 600000.SH / 600000 -> 600000
    """
    from stocks.stock_basic_lookup import normalize_stock_code_for_basic

    return normalize_stock_code_for_basic(stock_code)


def _lookup_stock_name_from_basic(db: Database, stock_code: str) -> str | None:
    """按股票代码从 stock_basic 查名称；查不到返回 None。"""
    from stocks.stock_basic_lookup import lookup_stock_name_from_basic

    return lookup_stock_name_from_basic(db, stock_code)


def _lookup_asset_name(db: Database, code: str) -> str | None:
    """
    按代码查名称：
    - 优先 stock_basic（股票/指数等）
    - 其次 etf_basic（场内 ETF）
    """
    name = _lookup_stock_name_from_basic(db, code)
    if name:
        return name
    try:
        row = db.get_etf_basic_by_code((code or "").strip())
        if row and row.get("name"):
            return str(row.get("name"))
    except Exception:
        return None
    return None


def _fill_positions_stock_name_from_basic(db: Database, positions_rows: list) -> None:
    """
    对持仓列表 rows 就地补全 stock_name：
    - 优先 stock_basic
    - 其次 etf_basic
    """
    if not positions_rows:
        return
    codes = []
    for r in positions_rows:
        c = _normalize_stock_code_for_basic(r.get("stock_code"))
        if c:
            codes.append(c)
    codes = sorted(set(codes))
    if not codes:
        return
    try:
        if db.is_sqlite:
            placeholders = ",".join(["?"] * len(codes))
        else:
            placeholders = ",".join(["%s"] * len(codes))
        rows = db.fetch_all(
            f"SELECT code, name FROM stock_basic WHERE code IN ({placeholders})",
            tuple(codes),
        )
        name_map = {str(r.get("code")): (r.get("name") or "") for r in (rows or [])}
        # etf_basic 回填 stock_basic 缺口
        try:
            missing = [c for c in codes if not name_map.get(c)]
            if missing:
                if db.is_sqlite:
                    placeholders2 = ",".join(["?"] * len(missing))
                else:
                    placeholders2 = ",".join(["%s"] * len(missing))
                etf_rows = db.fetch_all(
                    f"SELECT code, name FROM etf_basic WHERE code IN ({placeholders2})",
                    tuple(missing),
                )
                for er in etf_rows or []:
                    k = str(er.get("code"))
                    v = (er.get("name") or "")
                    if k and v:
                        name_map[k] = v
        except Exception:
            pass
        for r in positions_rows:
            key = _normalize_stock_code_for_basic(r.get("stock_code"))
            nm = name_map.get(key)
            if nm:
                r["stock_name"] = nm
    except Exception:
        # 仅用于展示增强，失败不影响主流程
        return


def _fill_records_stock_name_from_basic(db: Database, rows: list, code_key: str = "stock_code") -> None:
    """对任意 rows 批量补全 stock_name 字段（来自 stock_basic / etf_basic）。"""
    if not rows:
        return
    codes = []
    for r in rows:
        c = _normalize_stock_code_for_basic(r.get(code_key))
        if c:
            codes.append(c)
    codes = sorted(set(codes))
    if not codes:
        return
    try:
        if db.is_sqlite:
            placeholders = ",".join(["?"] * len(codes))
        else:
            placeholders = ",".join(["%s"] * len(codes))
        got = db.fetch_all(
            f"SELECT code, name FROM stock_basic WHERE code IN ({placeholders})",
            tuple(codes),
        )
        name_map = {str(r.get("code")): (r.get("name") or "") for r in (got or [])}
        try:
            missing = [c for c in codes if not name_map.get(c)]
            if missing:
                if db.is_sqlite:
                    placeholders2 = ",".join(["?"] * len(missing))
                else:
                    placeholders2 = ",".join(["%s"] * len(missing))
                etf_rows = db.fetch_all(
                    f"SELECT code, name FROM etf_basic WHERE code IN ({placeholders2})",
                    tuple(missing),
                )
                for er in etf_rows or []:
                    k = str(er.get("code"))
                    v = (er.get("name") or "")
                    if k and v:
                        name_map[k] = v
        except Exception:
            pass
        for r in rows:
            key = _normalize_stock_code_for_basic(r.get(code_key))
            nm = name_map.get(key)
            if nm:
                r["stock_name"] = nm
    except Exception:
        return


@bp.route('/positions')
def positions_page():
    """持仓列表页面（只读），需登录，仅展示当前账号持仓。"""
    if 'user_id' not in session:
        return redirect(url_for('main.index'))
    positions = _get_positions_with_market(int(session['user_id']))
    return render_template('positions.html', positions=positions)



@bp.route('/watchlist')
def watchlist_page():
    """自选列表页面（Excel 风格，数据在后续阶段补齐）"""
    # 阶段六 1 只要求页面与样式落地；后续阶段再接入自选列表数据逻辑
    return render_template('watchlist.html', watchlist=[])


@bp.route('/investment_calendar')
def investment_calendar_page():
    """投资日历页面（需登录，仅展示当前账号数据）。"""
    if 'user_id' not in session:
        return redirect(url_for('main.index'))
    return render_template('investment_calendar.html')


@bp.route('/api/watchlist', methods=['GET'])
def api_watchlist_get():
    """已登录用户从数据库读取自选列表（跨设备同步）。"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录', 'require_login': True}), 401
    db = Database.Create()
    try:
        items = db.get_user_watchlist(int(session['user_id']))
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        logger.error('读取自选列表失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500
    finally:
        db.close()


@bp.route('/api/watchlist', methods=['PUT'])
def api_watchlist_put():
    """已登录用户将自选列表整体写入数据库。"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录', 'require_login': True}), 401
    try:
        data = request.get_json() or {}
        raw_items = data.get('items')
        if not isinstance(raw_items, list):
            return jsonify({'success': False, 'message': 'items 必须为数组'}), 400
        normalized = []
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            sc = str(it.get('stock_code') or '').strip()
            if not sc:
                continue
            normalized.append({
                'stock_code': sc,
                'stock_name': str(it.get('stock_name') or '').strip(),
            })
        db = Database.Create()
        try:
            db.replace_user_watchlist(int(session['user_id']), normalized)
            return jsonify({'success': True})
        finally:
            db.close()
    except Exception as e:
        logger.error('保存自选列表失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/api/watchlist/<stock_code>', methods=['DELETE'])
def api_watchlist_delete(stock_code):
    """已登录用户从自选中删除单只股票（按代码匹配，支持 600000 与 600000.SH 等同码）。"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录', 'require_login': True}), 401
    sc = (stock_code or '').strip()
    if not sc:
        return jsonify({'success': False, 'message': '股票代码不能为空'}), 400
    db = Database.Create()
    try:
        deleted = db.remove_user_watchlist_item(int(session['user_id']), sc)
        if deleted <= 0:
            return jsonify({'success': False, 'message': '自选中未找到该代码'}), 404
        return jsonify({'success': True})
    except Exception as e:
        logger.error('删除自选项失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500
    finally:
        db.close()


def _require_login_json():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "未登录", "require_login": True}), 401
    return None


def _parse_investment_calendar_remind_fields(payload: dict):
    """解析并校验投资日历提醒时间选项；返回 (anchor, advance, count, interval)。"""
    anchor = str((payload or {}).get("remind_anchor_time") or "09:00").strip()
    if len(anchor) >= 8 and anchor[2] == ":":
        # 兼容 <input type="time"> 可能返回 HH:MM:SS
        anchor = anchor[:5]
    try:
        datetime.strptime(anchor, "%H:%M")
    except ValueError as e:
        raise ValueError("提醒基准时间格式无效，请使用 HH:MM（24 小时制）") from e

    raw_adv = (payload or {}).get("remind_advance_minutes", 0)
    try:
        advance = int(raw_adv)
    except (TypeError, ValueError) as e:
        raise ValueError("remind_advance_minutes 必须为整数") from e
    if advance < 0 or advance > 4320:
        raise ValueError("提前提醒分钟数必须在 0～4320 之间")

    raw_cnt = (payload or {}).get("remind_count_per_day", 1)
    try:
        count = int(raw_cnt)
    except (TypeError, ValueError) as e:
        raise ValueError("remind_count_per_day 必须为整数") from e
    if count < 1 or count > 24:
        raise ValueError("每日提醒次数必须在 1～24 之间")

    raw_iv = (payload or {}).get("remind_interval_minutes", 60)
    try:
        interval = int(raw_iv)
    except (TypeError, ValueError) as e:
        raise ValueError("remind_interval_minutes 必须为整数") from e
    if interval < 5 or interval > 1440:
        raise ValueError("提醒间隔分钟数必须在 5～1440 之间")

    return anchor, advance, count, interval


@bp.route("/api/investment_calendar/items", methods=["GET"])
def api_investment_calendar_items_get():
    """按日期范围查询当前账号的投资日历项。"""
    not_logged_in = _require_login_json()
    if not_logged_in:
        return not_logged_in

    start_raw = (request.args.get("start_date") or "").strip()
    end_raw = (request.args.get("end_date") or "").strip()
    d0 = _parse_quant_iso_date(start_raw)
    d1 = _parse_quant_iso_date(end_raw)
    if d0 is None or d1 is None:
        return jsonify({"success": False, "message": "起止日期格式无效，请使用 YYYY-MM-DD"}), 400
    if d0 > d1:
        return jsonify({"success": False, "message": "开始日期不能晚于结束日期"}), 400

    db = Database.Create()
    try:
        items = db.list_investment_calendar_items(
            int(session["user_id"]),
            d0.isoformat(),
            d1.isoformat(),
        )
        return jsonify({"success": True, "items": items})
    except Exception as e:
        logger.error("查询投资日历项失败: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "服务器内部错误"}), 500
    finally:
        db.close()


@bp.route("/api/investment_calendar/items", methods=["POST"])
def api_investment_calendar_items_post():
    """创建投资日历项（绑定当前账号）。"""
    not_logged_in = _require_login_json()
    if not_logged_in:
        return not_logged_in

    payload = request.get_json(silent=True) or {}
    d = _parse_quant_iso_date(payload.get("date"))
    if d is None:
        return jsonify({"success": False, "message": "日期格式无效，请使用 YYYY-MM-DD"}), 400

    content = str(payload.get("content") or "").strip()
    if not content:
        return jsonify({"success": False, "message": "内容不能为空"}), 400

    reminder_group = str(payload.get("reminder_group") or "").strip()
    reminder_message = str(payload.get("reminder_message") or "").strip()

    if len(reminder_group) > 128:
        return jsonify({"success": False, "message": "reminder_group 过长（最多 128）"}), 400
    if len(content) > 4000:
        return jsonify({"success": False, "message": "content 过长（最多 4000）"}), 400
    if len(reminder_message) > 4000:
        return jsonify({"success": False, "message": "reminder_message 过长（最多 4000）"}), 400

    try:
        anchor, advance, count, interval = _parse_investment_calendar_remind_fields(payload)
    except ValueError as ve:
        return jsonify({"success": False, "message": str(ve)}), 400

    db = Database.Create()
    try:
        item = db.create_investment_calendar_item(
            user_id=int(session["user_id"]),
            date=d.isoformat(),
            content=content,
            reminder_group=reminder_group or None,
            reminder_message=reminder_message or None,
            remind_anchor_time=anchor,
            remind_advance_minutes=advance,
            remind_count_per_day=count,
            remind_interval_minutes=interval,
        )
        return jsonify({"success": True, "item": item})
    except Exception as e:
        logger.error("创建投资日历项失败: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "服务器内部错误"}), 500
    finally:
        db.close()


@bp.route("/api/investment_calendar/items/<int:item_id>", methods=["PUT"])
def api_investment_calendar_items_put(item_id: int):
    """更新投资日历项（仅业务字段，按账号隔离）。"""
    not_logged_in = _require_login_json()
    if not_logged_in:
        return not_logged_in

    payload = request.get_json(silent=True) or {}
    # date 不允许在此接口隐式变更
    if "date" in payload:
        return jsonify({"success": False, "message": "不支持在更新接口修改 date"}), 400

    content = str(payload.get("content") or "").strip()
    if not content:
        return jsonify({"success": False, "message": "内容不能为空"}), 400
    reminder_group = str(payload.get("reminder_group") or "").strip()
    reminder_message = str(payload.get("reminder_message") or "").strip()
    if len(reminder_group) > 128:
        return jsonify({"success": False, "message": "reminder_group 过长（最多 128）"}), 400
    if len(content) > 4000:
        return jsonify({"success": False, "message": "content 过长（最多 4000）"}), 400
    if len(reminder_message) > 4000:
        return jsonify({"success": False, "message": "reminder_message 过长（最多 4000）"}), 400

    try:
        anchor, advance, count, interval = _parse_investment_calendar_remind_fields(payload)
    except ValueError as ve:
        return jsonify({"success": False, "message": str(ve)}), 400

    db = Database.Create()
    try:
        ok = db.update_investment_calendar_item(
            user_id=int(session["user_id"]),
            item_id=int(item_id),
            content=content,
            reminder_group=reminder_group or None,
            reminder_message=reminder_message or None,
            remind_anchor_time=anchor,
            remind_advance_minutes=advance,
            remind_count_per_day=count,
            remind_interval_minutes=interval,
        )
        if not ok:
            return jsonify({"success": False, "message": "日历项不存在"}), 404
        item = db.get_investment_calendar_item(int(session["user_id"]), int(item_id))
        return jsonify({"success": True, "item": item})
    except Exception as e:
        logger.error("更新投资日历项失败: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "服务器内部错误"}), 500
    finally:
        db.close()


@bp.route("/api/investment_calendar/items/<int:item_id>", methods=["DELETE"])
def api_investment_calendar_items_delete(item_id: int):
    """删除投资日历项（按账号隔离）。"""
    not_logged_in = _require_login_json()
    if not_logged_in:
        return not_logged_in

    db = Database.Create()
    try:
        n = db.delete_investment_calendar_item(int(session["user_id"]), int(item_id))
        if n <= 0:
            return jsonify({"success": False, "message": "日历项不存在"}), 404
        return jsonify({"success": True})
    except Exception as e:
        logger.error("删除投资日历项失败: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "服务器内部错误"}), 500
    finally:
        db.close()


@bp.route('/api/positions/simple', methods=['GET'])
def api_positions_simple():
    """返回当前登录用户持仓的简要信息（用于自选列表自动补齐）；未登录返回空列表。"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': True, 'positions': []})
        positions = _get_positions_with_market(int(session['user_id'])) or []
        simple = []
        for p in positions:
            sc = (p.get('stock_code') or '').strip()
            if not sc:
                continue
            simple.append({
                'stock_code': sc,
                'stock_name': p.get('stock_name') or '',
            })
        return jsonify({'success': True, 'positions': simple})
    except Exception as e:
        logger.error('获取持仓简要信息失败: %s', str(e), exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500


@bp.route('/positions/trade', methods=['GET', 'POST'])
def position_trade_page():
    """
    表单方式录入一笔买入/卖出操作：
    - GET: 展示表单
    - POST: 处理表单提交，调用 _apply_position_trade 并重定向
    """
    from datetime import date

    if request.method == 'GET':
        if 'user_id' not in session:
            return redirect(url_for('main.index'))
        today = date.today().strftime('%Y-%m-%d')
        stock_code = (request.args.get('stock_code') or '').strip()
        stock_name = (request.args.get('stock_name') or '').strip()
        return render_template(
            'positions_trade.html',
            today=today,
            default_action='buy',
            default_stock_code=stock_code,
            default_stock_name=stock_name,
            error_message=None,
        )

    # POST
    if 'user_id' not in session:
        return redirect(url_for('main.index'))
    form = request.form
    asset_type = (form.get('asset_type') or 'stock').strip().lower()
    stock_code = (form.get('stock_code') or '').strip()
    stock_name = (form.get('stock_name') or '').strip() or None
    action = (form.get('action') or '').lower()
    price = form.get('price')
    quantity = form.get('quantity')
    fee = form.get('fee', 0)
    trade_date = form.get('trade_date')
    next_target = form.get('next', 'positions').strip() or 'positions'

    error_message = None

    if asset_type not in ('stock', 'etf'):
        error_message = '标的类型必须为 股票 或 ETF'
    elif not stock_code:
        error_message = '股票代码不能为空'
    elif action not in ('buy', 'sell'):
        error_message = '操作类型必须为买入或卖出'
    else:
        try:
            price = float(price)
            quantity = float(quantity)
            fee = float(fee or 0)
        except (TypeError, ValueError):
            error_message = '价格、数量、手续费必须为数值'
        else:
            # 价格统一保留 3 位小数（用于持仓录入/展示一致性）
            price = round(price, 3)
            if price <= 0 or quantity <= 0:
                error_message = '价格和数量必须大于 0'

    from datetime import datetime as _dt
    if not trade_date:
        trade_date = _dt.now().strftime('%Y-%m-%d')

    if error_message:
        today = trade_date
        return render_template(
            'positions_trade.html',
            today=today,
            default_action=action or 'buy',
            default_stock_code=stock_code,
            default_stock_name=stock_name or '',
            error_message=error_message,
        )

    db = Database.Create()
    try:
        db.begin_transaction()
        # 名称优先使用 stock_basic / etf_basic（若存在）
        basic_name = _lookup_asset_name(db, stock_code)
        if basic_name:
            stock_name = basic_name
        # 若是 ETF 且库里没有，则用表单名称补一条基础信息（只存基本数据）
        if asset_type == 'etf' and not basic_name:
            if not stock_name:
                raise ValueError('ETF 基金名称不能为空（库中不存在该基金时需手动填写）')
            db.upsert_etf_basic(code=stock_code, name=stock_name, source='manual')
        _apply_position_trade(
            db=db,
            user_id=int(session['user_id']),
            stock_code=stock_code,
            stock_name=stock_name,
            action=action,
            price=price,
            quantity=quantity,
            fee=fee,
            trade_date=trade_date,
        )
        db.commit()
    except ValueError as ve:
        db.rollback()
        error_message = str(ve)
        today = trade_date
        return render_template(
            'positions_trade.html',
            today=today,
            default_action=action or 'buy',
            default_stock_code=stock_code,
            default_stock_name=stock_name or '',
            error_message=error_message,
        )
    except Exception as e:
        db.rollback()
        logger.error('表单录入买卖操作失败: %s', e, exc_info=True)
        error_message = '服务器内部错误，请稍后重试'
        today = trade_date
        return render_template(
            'positions_trade.html',
            today=today,
            default_action=action or 'buy',
            default_stock_code=stock_code,
            default_stock_name=stock_name or '',
            error_message=error_message,
        )
    finally:
        db.close()

    if next_target == 'transactions':
        return redirect(url_for('main.positions_transactions_page'))
    return redirect(url_for('main.positions_page'))


def _apply_position_trade(db, user_id: int, stock_code: str, stock_name: str, action: str,
                          price: float, quantity: float, fee: float,
                          trade_date: str):
    """在一个已打开的 db 连接上应用一笔买入/卖出，并写入 transactions 与更新 positions（按 user_id 隔离）。"""
    uid = int(user_id)
    # 写入交易流水
    db.execute(
        '''INSERT INTO transactions
           (user_id, stock_code, action, price, quantity, fee, trade_date)
           VALUES (%s, %s, %s, %s, %s, %s, %s)''',
        (uid, stock_code, action, price, quantity, fee, trade_date)
    )
    # 查询现有持仓
    row = db.fetch_one(
        'SELECT stock_code, stock_name, quantity, cost_price FROM positions WHERE stock_code = %s AND user_id = %s',
        (stock_code, uid)
    )
    if action == 'buy':
        if row:
            old_qty = float(row['quantity'] or 0)
            old_cost = float(row['cost_price'] or 0)
            new_qty = old_qty + quantity
            if new_qty <= 0:
                # 极端情况，直接删除持仓
                db.execute('DELETE FROM positions WHERE stock_code = %s AND user_id = %s', (stock_code, uid))
            else:
                total_cost = old_cost * old_qty + price * quantity + fee
                # 成本价统一保留 3 位小数（用于展示与后续计算一致性）
                new_cost = round((total_cost / new_qty), 3)
                db.execute(
                    '''UPDATE positions
                       SET quantity = %s, cost_price = %s, stock_name = %s, updated_at = CURRENT_TIMESTAMP
                       WHERE stock_code = %s AND user_id = %s''',
                    (new_qty, new_cost, stock_name or row.get('stock_name'), stock_code, uid)
                )
        else:
            db.execute(
                '''INSERT INTO positions
                   (user_id, stock_code, stock_name, quantity, cost_price)
                   VALUES (%s, %s, %s, %s, %s)''',
                (uid, stock_code, stock_name, quantity, round(float(price), 3))
            )
    elif action == 'sell':
        if not row:
            raise ValueError('无持仓可卖出')
        old_qty = float(row['quantity'] or 0)
        if quantity > old_qty:
            raise ValueError('卖出数量大于持仓数量')
        new_qty = old_qty - quantity
        if new_qty <= 0:
            # 卖光后从当前持仓中移除（历史信息保留在 transactions 中）
            db.execute('DELETE FROM positions WHERE stock_code = %s AND user_id = %s', (stock_code, uid))
        else:
            # 简化处理：保留原成本价
            db.execute(
                '''UPDATE positions
                   SET quantity = %s, updated_at = CURRENT_TIMESTAMP
                   WHERE stock_code = %s AND user_id = %s''',
                (new_qty, stock_code, uid)
            )
    else:
        raise ValueError('未知的操作类型')


@bp.route('/api/positions/trade', methods=['POST'])
def api_position_trade():
    """
    录入一笔买入/卖出操作（当前登录用户）：
    body: {stock_code, stock_name?, action: buy/sell, price, quantity, fee?, trade_date?}
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录', 'require_login': True}), 401
    data = request.get_json() or {}
    asset_type = (data.get('asset_type') or 'stock').strip().lower()
    stock_code = (data.get('stock_code') or '').strip()
    stock_name = (data.get('stock_name') or '').strip() or None
    action = (data.get('action') or '').lower()
    price = data.get('price')
    quantity = data.get('quantity')
    fee = data.get('fee') or 0
    trade_date = data.get('trade_date')

    if asset_type not in ('stock', 'etf'):
        return jsonify({'success': False, 'message': 'asset_type 只能为 stock 或 etf'}), 400
    if not stock_code:
        return jsonify({'success': False, 'message': '股票代码不能为空'}), 400
    if action not in ('buy', 'sell'):
        return jsonify({'success': False, 'message': 'action 只能为 buy 或 sell'}), 400
    try:
        price = float(price)
        quantity = float(quantity)
        fee = float(fee)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'price/quantity/fee 必须是数值'}), 400
    # 价格统一保留 3 位小数（用于持仓录入/展示一致性）
    price = round(price, 3)
    if price <= 0 or quantity <= 0:
        return jsonify({'success': False, 'message': 'price 和 quantity 必须大于 0'}), 400

    if not trade_date:
        trade_date = datetime.now().strftime('%Y-%m-%d')

    db = Database.Create()
    try:
        db.begin_transaction()
        basic_name = _lookup_asset_name(db, stock_code)
        if basic_name:
            stock_name = basic_name
        if asset_type == 'etf' and not basic_name:
            if not stock_name:
                raise ValueError('ETF 基金名称不能为空（库中不存在该基金时需填写 stock_name）')
            db.upsert_etf_basic(code=stock_code, name=stock_name, source='manual')
        _apply_position_trade(
            db=db,
            user_id=int(session['user_id']),
            stock_code=stock_code,
            stock_name=stock_name,
            action=action,
            price=price,
            quantity=quantity,
            fee=fee,
            trade_date=trade_date,
        )
        db.commit()
        return jsonify({'success': True})
    except ValueError as ve:
        db.rollback()
        return jsonify({'success': False, 'message': str(ve)}), 400
    except Exception as e:
        db.rollback()
        logger.error('录入买卖操作失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500
    finally:
        db.close()


@bp.route('/api/positions/<stock_code>', methods=['DELETE'])
def api_position_delete(stock_code):
    """
    一键删除当前用户对指定股票的持仓快照（仅删除 positions 行，不删除 transactions 流水）。
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录', 'require_login': True}), 401
    stock_code = (stock_code or '').strip()
    if not stock_code:
        return jsonify({'success': False, 'message': '股票代码不能为空'}), 400
    uid = int(session['user_id'])
    db = Database.Create()
    try:
        cursor = db.execute(
            'DELETE FROM positions WHERE stock_code = %s AND user_id = %s',
            (stock_code, uid),
        )
        deleted = int(getattr(cursor, 'rowcount', 0) or 0)
        if deleted <= 0:
            return jsonify({'success': False, 'message': '未找到该持仓'}), 404
        return jsonify({'success': True})
    except Exception as e:
        logger.error('删除持仓失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500
    finally:
        db.close()


@bp.route('/api/stock_basic/<stock_code>', methods=['GET'])
def get_stock_basic_by_code_api(stock_code):
    """按代码查询 stock_basic / etf_basic（用于前端输入代码后自动回填名称）"""
    stock_code = (stock_code or '').strip()
    if not stock_code:
        return jsonify({'success': False, 'message': '股票代码不能为空'}), 400
    db = Database.Create()
    try:
        code = _normalize_stock_code_for_basic(stock_code)
        row = db.fetch_one("SELECT code, name, market, exchange, list_date, industry, area, status FROM stock_basic WHERE code=%s LIMIT 1", (code,))
        if not row:
            etf = db.get_etf_basic_by_code(code)
            if not etf:
                return jsonify({'success': True, 'found': False, 'code': code})
            data = {
                "code": etf.get("code"),
                "name": etf.get("name"),
                "market": etf.get("market"),
                "exchange": etf.get("exchange"),
                "list_date": etf.get("list_date"),
                "industry": None,
                "area": None,
                "status": None,
            }
            return jsonify({'success': True, 'found': True, 'data': data})
        return jsonify({'success': True, 'found': True, 'data': row})
    except Exception as e:
        logger.error("查询 stock_basic 失败: %s", str(e), exc_info=True)
        return jsonify({'success': False, 'message': f'查询失败: {str(e)}'}), 500
    finally:
        db.close()


@bp.route('/api/quotes/tencent', methods=['POST'])
def api_quotes_tencent():
    """批量获取腾讯实时行情（用于持仓页定时刷新）。"""
    data = request.get_json() or {}
    codes = data.get('codes') or []
    if not isinstance(codes, list):
        return jsonify({'success': False, 'message': 'codes 必须为 list'}), 400
    codes = [str(c).strip() for c in codes if str(c).strip()]
    if not codes:
        return jsonify({'success': True, 'quotes': {}})
    try:
        from stocks.stock_quote_tencent import fetch_quotes

        quotes = fetch_quotes(codes)
        out = {}
        for k, q in (quotes or {}).items():
            out[k] = {
                'code': q.code,
                'name': q.name,
                'now': q.now,
                'prev_close': q.prev_close,
                'avg': q.avg,
                'pressure_line': q.pressure_line,
                'support_line': q.support_line,
            }
        return jsonify({'success': True, 'quotes': out})
    except Exception as e:
        logger.error("腾讯行情获取失败: %s", str(e), exc_info=True)
        return jsonify({'success': False, 'message': f'腾讯行情获取失败: {str(e)}'}), 500


@bp.route('/api/positions/<stock_code>/history', methods=['GET'])
def api_position_history(stock_code):
    """获取当前用户对某只股票的历史交易记录"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '未登录', 'require_login': True}), 401
    stock_code = (stock_code or '').strip()
    if not stock_code:
        return jsonify({'success': False, 'message': '股票代码不能为空'}), 400
    uid = int(session['user_id'])
    db = Database.Create()
    try:
        rows = db.fetch_all(
            '''SELECT id, stock_code, action, price, quantity, fee, trade_date, created_at
               FROM transactions
               WHERE stock_code = %s AND user_id = %s
               ORDER BY trade_date DESC, id DESC''',
            (stock_code, uid)
        )
        records = []
        for r in rows or []:
            amount = float(r.get('price') or 0) * float(r.get('quantity') or 0) + float(r.get('fee') or 0)
            records.append({
                'id': r.get('id'),
                'stock_code': r.get('stock_code'),
                'action': r.get('action'),
                'price': float(r.get('price') or 0),
                'quantity': float(r.get('quantity') or 0),
                'fee': float(r.get('fee') or 0),
                'trade_date': r.get('trade_date'),
                'created_at': r.get('created_at'),
                'amount': amount,
            })
        return jsonify({'success': True, 'records': records})
    except Exception as e:
        logger.error('获取交易历史失败: %s', e, exc_info=True)
        return jsonify({'success': False, 'message': '服务器内部错误'}), 500
    finally:
        db.close()


@bp.route('/positions/transactions')
def positions_transactions_page():
    """当前登录用户的所有交易流水列表页面"""
    if 'user_id' not in session:
        return redirect(url_for('main.index'))
    embed = (request.args.get('embed') or '').strip() in ('1', 'true', 'yes', 'on')
    uid = int(session['user_id'])
    db = Database.Create()
    try:
        rows = db.fetch_all(
            '''SELECT id, stock_code, action, price, quantity, fee, trade_date, created_at
               FROM transactions
               WHERE user_id = %s
               ORDER BY trade_date DESC, id DESC''',
            (uid,)
        )
        records = []
        for r in rows or []:
            price = float(r.get('price') or 0)
            qty = float(r.get('quantity') or 0)
            fee = float(r.get('fee') or 0)
            amount = price * qty + fee
            records.append({
                'id': r.get('id'),
                'stock_code': r.get('stock_code'),
                'stock_name': '',
                'action': r.get('action'),
                'price': price,
                'quantity': qty,
                'fee': fee,
                'trade_date': r.get('trade_date'),
                'created_at': r.get('created_at'),
                'amount': amount,
            })
        _fill_records_stock_name_from_basic(db, records, code_key="stock_code")
        return render_template('positions_transactions.html', transactions=records, embed=embed)
    except Exception as e:
        logger.error('加载交易流水页面失败: %s', e, exc_info=True)
        return render_template('positions_transactions.html', transactions=[], error_message='加载交易流水失败', embed=embed)
    finally:
        db.close()


@bp.route('/positions/<stock_code>/history_page')
def position_history_page(stock_code):
    """当前用户单票历史交易明细页面"""
    if 'user_id' not in session:
        return redirect(url_for('main.index'))
    stock_code = (stock_code or '').strip()
    if not stock_code:
        return render_template('position_history.html', stock_code='', stock_name='', records=[], summary={}, error_message='股票代码不能为空')

    uid = int(session['user_id'])
    db = Database.Create()
    try:
        # 查询基本交易记录
        rows = db.fetch_all(
            '''SELECT stock_code, action, price, quantity, fee, trade_date, created_at
               FROM transactions
               WHERE stock_code = %s AND user_id = %s
               ORDER BY trade_date DESC, id DESC''',
            (stock_code, uid)
        )
        records = []
        total_buy_qty = 0.0
        total_sell_qty = 0.0
        total_buy_amount = 0.0
        total_sell_amount = 0.0
        for r in rows or []:
            action = (r.get('action') or '').lower()
            price = float(r.get('price') or 0)
            qty = float(r.get('quantity') or 0)
            fee = float(r.get('fee') or 0)
            amount = price * qty + fee
            if action == 'buy':
                total_buy_qty += qty
                total_buy_amount += amount
            elif action == 'sell':
                total_sell_qty += qty
                total_sell_amount += amount
            records.append({
                'stock_code': r.get('stock_code'),
                'action': action,
                'price': price,
                'quantity': qty,
                'fee': fee,
                'trade_date': r.get('trade_date'),
                'created_at': r.get('created_at'),
                'amount': amount,
            })

        # 获取当前持仓名称/数量/成本价（如有）
        pos = db.fetch_one(
            '''SELECT stock_name, quantity, cost_price
               FROM positions
               WHERE stock_code = %s AND user_id = %s''',
            (stock_code, uid)
        )
        stock_name = ''
        current_qty = None
        current_cost_price = None
        if pos:
            stock_name = pos.get('stock_name') or ''
            current_qty = float(pos.get('quantity') or 0)
            current_cost_price = float(pos.get('cost_price') or 0)

        # 页面展示名称优先取 stock_basic（若存在）
        basic_name = _lookup_stock_name_from_basic(db, stock_code)
        if basic_name:
            stock_name = basic_name

        net_quantity = total_buy_qty - total_sell_qty
        summary = {
            'total_buy_quantity': total_buy_qty,
            'total_sell_quantity': total_sell_qty,
            'net_quantity': net_quantity,
            'total_buy_amount': total_buy_amount,
            'total_sell_amount': total_sell_amount,
            'current_position_quantity': current_qty,
            'current_cost_price': current_cost_price,
        }

        return render_template(
            'position_history.html',
            stock_code=stock_code,
            stock_name=stock_name,
            records=records,
            summary=summary,
            error_message=None,
        )
    except Exception as e:
        logger.error('加载单票历史页面失败: %s', e, exc_info=True)
        return render_template(
            'position_history.html',
            stock_code=stock_code,
            stock_name='',
            records=[],
            summary={},
            error_message='加载单票历史失败',
        )
    finally:
        db.close()

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
        send_notify_fallback(signalMessages)
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
        name = data.get('name')
        send_mode = data.get('send_mode')
        chat_id = data.get('chat_id')
        webhook_url = data.get('webhook_url')
        sign_secret = data.get('sign_secret')
        app_id = data.get('app_id')
        app_secret = data.get('app_secret')

        chat_list = data.get('chat_list')
        if not isinstance(chat_list, list):
            chat_list = []

        lt_norm = str(list_type or 'weixin').strip().lower()
        if lt_norm == 'feishu':
            sm = str(send_mode or '').strip().lower()
            if sm not in ('oapi', 'https'):
                return jsonify({'success': False, 'message': '飞书 group 的 send_mode 必须为 oapi 或 https'}), 400
            if sm == 'oapi' and not str(chat_id or '').strip():
                return jsonify({'success': False, 'message': 'send_mode=oapi 时必须填写 chat_id'}), 400
            if sm == 'oapi' and (not str(app_id or '').strip() or not str(app_secret or '').strip()):
                return jsonify({'success': False, 'message': 'send_mode=oapi 时必须填写 app_id 和 app_secret'}), 400
            if sm == 'https' and not str(webhook_url or '').strip():
                return jsonify({'success': False, 'message': 'send_mode=https 时必须填写 webhook_url'}), 400
        else:
            # 微信群：chat_list 才有效，其它字段忽略
            send_mode = None
            chat_id = None
            webhook_url = None
            sign_secret = None
            app_id = None
            app_secret = None
        db = Database.Create()
        ok, result = db.create_message_group(
            group_id=group_id,
            list_type=lt_norm,
            chat_list=chat_list,
            name=name,
            send_mode=send_mode,
            chat_id=chat_id,
            webhook_url=webhook_url,
            sign_secret=sign_secret,
            app_id=app_id,
            app_secret=app_secret,
        )
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
        name = data.get('name')
        send_mode = data.get('send_mode')
        chat_id = data.get('chat_id')
        webhook_url = data.get('webhook_url')
        sign_secret = data.get('sign_secret')
        app_id = data.get('app_id')
        app_secret = data.get('app_secret')
        db = Database.Create()
        if group_id is not None:
            try:
                group_id = int(group_id)
            except (TypeError, ValueError):
                db.close()
                return jsonify({'success': False, 'message': 'group_id 须为整数'}), 400

        if list_type is not None:
            list_type = str(list_type).strip().lower() or None
        if list_type == 'feishu' or (list_type is None and isinstance(data.get('send_mode'), str)):
            sm = str(send_mode or '').strip().lower()
            if sm and sm not in ('oapi', 'https'):
                db.close()
                return jsonify({'success': False, 'message': '飞书 group 的 send_mode 必须为 oapi 或 https'}), 400
            if sm == 'oapi' and chat_id is not None and not str(chat_id or '').strip():
                db.close()
                return jsonify({'success': False, 'message': 'send_mode=oapi 时必须填写 chat_id'}), 400
            if sm == 'oapi' and ((app_id is not None and not str(app_id or '').strip()) or (app_secret is not None and not str(app_secret or '').strip())):
                db.close()
                return jsonify({'success': False, 'message': 'send_mode=oapi 时必须填写 app_id 和 app_secret'}), 400
            if sm == 'https' and webhook_url is not None and not str(webhook_url or '').strip():
                db.close()
                return jsonify({'success': False, 'message': 'send_mode=https 时必须填写 webhook_url'}), 400
        ok, err = db.update_message_group(
            pk_id,
            group_id=group_id,
            list_type=list_type,
            chat_list=chat_list,
            name=name,
            send_mode=send_mode,
            chat_id=chat_id,
            webhook_url=webhook_url,
            sign_secret=sign_secret,
            app_id=app_id,
            app_secret=app_secret,
        )
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


@bp.route('/api/chat_groups/<int:pk_id>/test_send', methods=['POST'])
def test_send_chat_group(pk_id: int):
    """
    对单个群组执行一次“测试发送”（仅用于群组管理页按钮）：
    - 仅支持 list_type=feishu
    - 不依赖 NOTIFY.channel（强制走该群组的 send_mode 路由）
    body: { message?: str }
    """
    try:
        data = request.get_json(silent=True) or {}
        msg = str(data.get('message') or '').strip()
        if not msg:
            msg = '【测试消息】这是一条飞书群组测试发送消息。'

        db = Database.Create()
        try:
            db.ensure_message_group_tables()
            row = db.get_message_group_by_id(int(pk_id))
        finally:
            db.close()

        if not row:
            return jsonify({'success': False, 'message': '群组不存在'}), 404
        if str(row.get('list_type') or '').strip().lower() != 'feishu':
            return jsonify({'success': False, 'message': '仅支持飞书群组测试发送'}), 400

        from Managers.notify_types import FeishuGroup
        from Managers.feishu_senders import send_feishu_group_text

        group = FeishuGroup(
            group_id=int(row.get('group_id') or 0),
            name=str(row.get('name') or '').strip() or str(row.get('group_id') or ''),
            send_mode=str(row.get('send_mode') or '').strip().lower(),  # type: ignore[arg-type]
            chat_id=(str(row.get('chat_id') or '').strip() or None),
            webhook_url=(str(row.get('webhook_url') or '').strip() or None),
            sign_secret=(str(row.get('sign_secret') or '').strip() or None),
            app_id=(str(row.get('app_id') or '').strip() or None),
            app_secret=(str(row.get('app_secret') or '').strip() or None),
        )

        send_feishu_group_text(group, msg)
        return jsonify({'success': True, 'message': '发送成功'})
    except Exception as e:
        logger.error("测试发送失败 pk_id=%s: %s", pk_id, e, exc_info=True)
        return jsonify({'success': False, 'message': str(e) or '发送失败'}), 500


@bp.route('/api/update_stock_list', methods=['POST'])
def update_stock_list_api():
    success, sendAllMessage = manager.update_stock_list(False, None)
    if sendAllMessage:
        send_notify_fallback(sendAllMessage)
    if success:
        SendAllMessages()
        return jsonify({
            'success': True, 
            'message': '股票列表更新成功'
        })
    else:
        SendAllMessages()
        return jsonify({
            'success': False,
            'message': '股票列表更新失败'
        }), 500


@bp.route('/api/stock_basic/sync', methods=['POST'])
def sync_stock_basic_api():
    """手动触发：从 AKShare 同步股票基础信息到 stock_basic 表（用于测试按钮）"""
    try:
        from stocks.stock_basic_manager import StockBasicManager  # type: ignore

        # 确保表结构存在（MySQL/SQLite 双引擎）
        db = Database.Create()
        try:
            db.init_database()
        finally:
            db.close()

        n = StockBasicManager().sync_from_akshare()
        return jsonify({'success': True, 'written': n, 'message': f'已同步 {n} 条股票基础信息'})
    except ImportError as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        logger.error("同步 stock_basic 失败: %s", str(e), exc_info=True)
        return jsonify({'success': False, 'message': f'同步失败: {str(e)}'}), 500


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
                    time_module.sleep(2)
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
    result = run_daily_tushare_sync(manager, config)
    status_code = result.pop('status_code', 200)
    return jsonify(result), status_code


@bp.route('/api/sync_adj_factor_all', methods=['POST'])
def sync_adj_factor_all_api():
    """
    增量同步“已跟踪股票”的复权因子（adj_factor）。
    可选 JSON 参数：
      - limit: 只同步前 N 只（用于小规模验收）
      - sleep_seconds: 每只股票之间 sleep，避免触发频控（默认 0）
    """
    try:
        data = request.get_json(silent=True) or {}
        limit = data.get("limit")
        sleep_seconds = data.get("sleep_seconds", 0.0)
        result = run_sync_all_tracked_adj_factors(
            config_obj=config,
            sleep_seconds=float(sleep_seconds or 0.0),
            limit=int(limit) if limit is not None else None,
        )
        return jsonify(result)
    except Exception as e:
        logger.error("同步复权因子失败: %s", e, exc_info=True)
        return jsonify({"success": False, "message": f"同步失败: {str(e)}"}), 500


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
        return render_template(
            'nga_floors.html',
            tid=tid,
            thread=None,
            watch_authors=[],
            default_message_group_id='',
            error="NGA 模块未加载",
        )
    try:
        thread = nga_db.get_thread_config(tid)
        if not thread:
            return render_template(
                'nga_floors.html',
                tid=tid,
                thread=None,
                watch_authors=[],
                default_message_group_id='',
                error="帖子配置不存在，请先在 NGA 监控页面添加。",
            )
        watch_ordered: list[int] = []
        seen_uid: set[int] = set()
        for x in thread.get('watch_author_ids') or []:
            try:
                xi = int(x)
            except (TypeError, ValueError):
                continue
            if xi in seen_uid:
                continue
            seen_uid.add(xi)
            watch_ordered.append(xi)
        name_map = nga_db.resolve_author_names_for_tid(tid, watch_ordered) if watch_ordered else {}
        watch_authors = []
        for aid in watch_ordered:
            nick = (name_map.get(aid) or '').strip()
            watch_authors.append({'author_id': aid, 'forum_name': nick})
        dgid = thread.get('message_group_id')
        default_message_group_id = (
            str(dgid).strip()
            if dgid is not None and str(dgid).strip() not in ('', '0')
            else ''
        )
        return render_template(
            'nga_floors.html',
            tid=tid,
            thread=thread,
            watch_authors=watch_authors,
            default_message_group_id=default_message_group_id,
            error=None,
        )
    except Exception as e:
        logger.error(f"加载 NGA 楼层页面失败: {str(e)}", exc_info=True)
        return render_template(
            'nga_floors.html',
            tid=tid,
            thread=None,
            watch_authors=[],
            default_message_group_id='',
            error=str(e),
        )

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
        watch_ids = thread.get('watch_author_ids') or []
        watch_set = set()
        for x in watch_ids:
            try:
                watch_set.add(int(x))
            except (TypeError, ValueError):
                continue

        filter_author = request.args.get('author_id', type=int)
        if filter_author is not None and filter_author > 0:
            if filter_author not in watch_set:
                return jsonify({'success': False, 'message': '所选作者 ID 不在该帖的关注列表中'}), 400

        group_id = thread.get('message_group_id')
        if group_id is None or group_id == 0 or group_id == '0':
            return jsonify({
                'success': True,
                'thread': thread,
                'floors': [],
                'pagination': None,
                'message': '该帖子未配置消息群组，无法发送，仅展示已抓取楼层。',
            })

        author_filter = filter_author if filter_author and filter_author > 0 else None
        if author_filter is not None:
            per_page = 10
            page = request.args.get('page', type=int) or 1
            if page < 1:
                page = 1
            total = nga_db.count_floors_for_tid_author(tid, author_filter)
            if total == 0:
                total_pages = 0
                page = 1
                offset = 0
            else:
                total_pages = (total + per_page - 1) // per_page
                if page > total_pages:
                    page = total_pages
                offset = (page - 1) * per_page
            floors = nga_db.get_floors_with_sent_for_group(
                tid, group_id, limit=per_page, offset=offset, author_id=author_filter
            )
            pagination = {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
            }
            return jsonify({'success': True, 'thread': thread, 'floors': floors, 'pagination': pagination})

        floors = nga_db.get_floors_with_sent_for_group(tid, group_id, limit=200, offset=0, author_id=None)
        return jsonify({'success': True, 'thread': thread, 'floors': floors, 'pagination': None})
    except Exception as e:
        logger.error(f"获取 NGA 楼层列表失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_floors/<int:tid>/saved_prompts', methods=['GET', 'PUT'])
def nga_floors_saved_prompts(tid: int):
    """
    读取或更新当前帖子在数据库中的「AI 解释 / 时段总结」前置提示词（按 tid 存 nga_thread_config）。
    PUT 请求体可含 ai_explain_prompt、author_summary_prompt 之一或两者；未出现的字段不修改；空字符串表示清空。
    """
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        if request.method == 'GET':
            thread = nga_db.get_thread_config(tid)
            if not thread:
                return jsonify({'success': False, 'message': '帖子配置不存在'}), 404
            return jsonify({
                'success': True,
                'ai_explain_prompt': thread.get('ai_explain_prompt') or '',
                'author_summary_prompt': thread.get('author_summary_prompt') or '',
            })
        payload = request.get_json(silent=True) or {}
        if 'ai_explain_prompt' not in payload and 'author_summary_prompt' not in payload:
            return jsonify({
                'success': False,
                'message': '请求体须包含 ai_explain_prompt 或 author_summary_prompt',
            }), 400
        if not nga_db.get_thread_config(tid):
            return jsonify({'success': False, 'message': '帖子配置不存在'}), 404
        kwargs = {}
        if 'ai_explain_prompt' in payload:
            v = payload.get('ai_explain_prompt')
            kwargs['ai_explain_prompt'] = '' if v is None else str(v)
        if 'author_summary_prompt' in payload:
            v = payload.get('author_summary_prompt')
            kwargs['author_summary_prompt'] = '' if v is None else str(v)
        ok = nga_db.update_nga_thread_saved_prompts(tid, **kwargs)
        if not ok:
            return jsonify({'success': False, 'message': '更新失败或帖子不存在'}), 400
        return jsonify({'success': True, 'message': '已保存到帖子配置'})
    except Exception as e:
        logger.error(f"saved_prompts tid={tid}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


def _parse_nga_post_datetime(post_date_str: str) -> datetime | None:
    """
    NGA 楼层的 post_date 字段在库中是字符串，格式可能不稳定。
    尽量解析为 datetime；解析失败返回 None。
    """
    if not post_date_str:
        return None
    s = str(post_date_str).strip()
    if not s:
        return None
    # 常见：2026-04-10 12:34 / 2026-04-10 12:34:56 / 2026-04-10
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    # 兜底：尝试 ISO 解析（支持 2026-04-10T12:34:56）
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_request_datetime(value) -> datetime | None:
    """解析前端 datetime-local 或常见日期时间字符串。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith('Z'):
        s = s[:-1]
    if 'T' in s.upper():
        try:
            return datetime.fromisoformat(s.replace(' ', 'T'))
        except ValueError:
            pass
    return _parse_nga_post_datetime(s)


def _effective_dt_for_range_filter(post_date_str: str) -> datetime | None:
    """
    将楼层 post_date 转为用于时间区间筛选的时刻。
    若仅有日期无时间，按当日 12:00 参与比较，避免被任意整点时段边界整批排除。
    """
    raw = str(post_date_str or '').strip()
    dt = _parse_nga_post_datetime(raw)
    if dt is None:
        return None
    if len(raw) <= 10 and ' ' not in raw and 'T' not in raw.upper():
        return datetime.combine(dt.date(), time(12, 0))
    return dt


def _nga_collect_author_floors_in_range(
    tid: int, author_id: int, range_start: datetime, range_end: datetime
) -> list[tuple[datetime, dict]]:
    """从已抓取楼层中筛出某作者在 [range_start, range_end) 内的回复，按时间与楼层号排序。"""
    if nga_db is None or range_end <= range_start:
        return []
    floors = nga_db.get_floors_by_tid_author(tid=tid, author_id=author_id, limit=5000, offset=0)
    out: list[tuple[datetime, dict]] = []
    for f in floors:
        eff = _effective_dt_for_range_filter(f.get('post_date') or '')
        if eff is None:
            continue
        if range_start <= eff < range_end:
            out.append((eff, f))
    out.sort(key=lambda x: (x[0], int(x[1].get('floor_num') or 0)))
    return out


def _build_author_daily_transcript(entries: list[tuple[datetime, dict]], *, max_chars: int = 95000) -> str:
    """将多条回复拼成供模型阅读的文本；单条引用过长时截断。"""
    parts: list[str] = []
    for dt, f in entries:
        disp = (f.get('post_date') or '').strip() or dt.strftime('%Y-%m-%d %H:%M:%S')
        block = f"--- 楼层 #{f['floor_num']} pid={f['pid']}  {disp} ---\n"
        qt = (f.get('quote_text') or '').strip()
        if qt:
            if len(qt) > 2000:
                qt = qt[:2000] + '…（引用已截断）'
            block += '【引用】\n' + qt + '\n'
        ct = (f.get('content_text') or '').strip()
        block += '【正文】\n' + (ct or '（无）') + '\n\n'
        parts.append(block)
    full = ''.join(parts)
    if len(full) > max_chars:
        full = full[:max_chars] + '\n\n（时段内材料过长已截断；总结时请说明可能不完整）'
    return full


def _build_author_daily_summary_prompt(
    *,
    thread_name: str,
    tid: int,
    range_start: datetime,
    range_end: datetime,
    author_id: int,
    author_name: str,
    reply_count: int,
    transcript: str,
    user_prefix: str | None = None,
) -> str:
    """关注作者在某时间段内多条回复的总结任务（用户提示）。"""
    blocks: list[str] = []
    up = (user_prefix or '').strip()
    if up:
        max_u = 4000
        if len(up) > max_u:
            up = up[:max_u] + '\n\n（前置说明已截断）'
        blocks.extend(
            [
                '【用户前置说明】（请在遵守安全与事实的前提下尽量落实）',
                up,
                '',
            ]
        )
    nm = (author_name or '').strip()
    author_line = f'作者 uid={author_id}' + (f'（{nm}）' if nm else '')
    rs = range_start.strftime('%Y-%m-%d %H:%M')
    re = range_end.strftime('%Y-%m-%d %H:%M')
    tn = thread_name or '(无)'
    blocks.extend(
        [
            f'下面是 NGA 论坛帖子「{tn}」（tid={tid}）中，{author_line} 在时间段 [{rs} ~ {re})（左闭右开）内的多条回复（按时间排序）。',
            f'共 {reply_count} 条。每条含可选【引用】与该条【正文】。',
            '',
            '请用简体中文撰写**综合性总结**，要求：',
            '1）概括该作者在该时段内讨论的核心主题与态度变化（如有）；',
            '2）提炼其关键论点、论据或情绪走向；',
            '3）若有多条回复，说明它们之间的承接关系；',
            '4）对明显的术语/缩写可简要解释，无法确定处请标注「不确定」；',
            '5）使用小标题与分点，条理清晰。',
            '',
            '—— 时段内回复汇编 ——',
            transcript,
        ]
    )
    return '\n'.join(blocks)


def _default_nga_summary_range_16h(now: datetime | None = None) -> tuple[datetime, datetime]:
    """与楼层页「时段总结」默认一致：昨天 16:00 ～ 今天 16:00（左闭右开）。"""
    now = now or datetime.now()
    end = datetime.combine(now.date(), time(16, 0))
    start = end - timedelta(days=1)
    return start, end


def _execute_nga_author_range_summary(
    tid: int,
    author_id: int,
    start_dt: datetime,
    end_dt: datetime,
    group_id: str,
    extra_prompt: str,
) -> dict:
    """
    执行关注作者时段总结并发送。返回 dict:
      ok, message, reply_count(可选), http_status(失败时)
    """
    from Managers.gemini_client import (
        GeminiAuthError,
        GeminiClient,
        GeminiConfigError,
        GeminiRequestError,
        GeminiTransientError,
    )

    if nga_db is None:
        return {'ok': False, 'message': 'NGA 模块未加载', 'http_status': 500}

    thread = nga_db.get_thread_config(tid)
    if not thread:
        return {'ok': False, 'message': '帖子配置不存在', 'http_status': 404}

    watch_ids = thread.get('watch_author_ids') or []
    watch_set: set[int] = set()
    for x in watch_ids:
        try:
            watch_set.add(int(x))
        except (TypeError, ValueError):
            continue
    if author_id < 1 or author_id not in watch_set:
        return {'ok': False, 'message': 'author_id 必须在本帖的关注作者列表中', 'http_status': 400}

    gid_key = str(group_id or '').strip()
    if not gid_key or gid_key == '0':
        return {'ok': False, 'message': '未选择有效的消息群组', 'http_status': 400}

    db_chk = Database.Create()
    try:
        db_chk.ensure_message_group_tables()
        valid_group_ids = {str(g.get('group_id', '') or '') for g in (db_chk.get_all_message_groups() or [])}
    finally:
        db_chk.close()
    if gid_key not in valid_group_ids:
        return {'ok': False, 'message': '所选消息群组不存在', 'http_status': 400}

    if end_dt <= start_dt:
        return {'ok': False, 'message': '结束时间须晚于开始时间', 'http_status': 400}
    if end_dt - start_dt > timedelta(days=62):
        return {'ok': False, 'message': '时间段最长不超过 62 天', 'http_status': 400}

    entries = _nga_collect_author_floors_in_range(tid, author_id, start_dt, end_dt)
    if not entries:
        return {
            'ok': False,
            'message': '该时段内没有该作者的已抓取回复，请调整时间范围或确认爬虫已抓取。',
            'http_status': 400,
        }

    author_name = ''
    for _, f in entries:
        if f.get('author_name'):
            author_name = str(f['author_name']).strip()
            break

    transcript = _build_author_daily_transcript(entries)
    thread_name = (thread.get('name') or '').strip() or str(tid)
    ep = (extra_prompt or '').strip()

    try:
        client = GeminiClient.from_config(config)
    except GeminiConfigError as e:
        return {'ok': False, 'message': str(e), 'http_status': 400}

    prompt = _build_author_daily_summary_prompt(
        thread_name=thread_name,
        tid=tid,
        range_start=start_dt,
        range_end=end_dt,
        author_id=author_id,
        author_name=author_name,
        reply_count=len(entries),
        transcript=transcript,
        user_prefix=ep or None,
    )
    system_instruction = (
        '你是熟悉中文网络论坛的阅读与归纳助手，输出必须使用简体中文。'
        '只依据用户提供的「时段内回复汇编」做总结，不要编造未出现的言论或事实。'
    )

    try:
        result = client.generate(
            prompt,
            system_instruction=system_instruction,
            temperature=0.35,
            max_output_tokens=8192,
        )
    except GeminiAuthError as e:
        return {'ok': False, 'message': str(e), 'http_status': 401}
    except (GeminiRequestError, GeminiTransientError) as e:
        return {'ok': False, 'message': str(e), 'http_status': 502}

    ai_text = (result.text or '').strip()
    if not ai_text:
        return {'ok': False, 'message': 'Gemini 未返回有效总结内容', 'http_status': 502}

    header = (
        f'[NGA·时段总结] {thread_name} {author_name or ""} uid={author_id} '
        f'{start_dt.strftime("%Y-%m-%d %H:%M")} ~ {end_dt.strftime("%Y-%m-%d %H:%M")} '
        f'共{len(entries)}条\n'
        f'{"─" * 24}\n'
    )
    outbound = header + ai_text

    try:
        send_notify_to_group(int(gid_key), outbound)
    except Exception as e:
        logger.error(f'按日总结投递通知失败: {e}', exc_info=True)
        return {'ok': False, 'message': f'总结已生成，但发送到群组失败: {e}', 'http_status': 500}

    return {
        'ok': True,
        'message': f'已生成总结并发送到所选消息群组（时段内共 {len(entries)} 条回复）',
        'reply_count': len(entries),
    }


def _parse_db_datetime(val) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00').split('+', 1)[0])
    except Exception:
        return _parse_nga_post_datetime(s)


def _run_nga_auto_summary_due_tasks_impl() -> None:
    """扫描 DB 中启用的 NGA 自动时段总结任务，到达每日设定时间后执行（默认 16:00～16:00 窗口）。"""
    if nga_db is None:
        return
    db = Database.Create()
    try:
        db.ensure_nga_auto_summary_task_tables()
        tasks = db.list_nga_auto_summary_tasks_enabled()
    finally:
        db.close()
    now = datetime.now()
    for t in tasks:
        try:
            task_id = int(t['id'])
            tid = int(t['tid'])
            author_id = int(t['author_id'])
            gid = str(t['message_group_id'] or '').strip()
            rt = (t.get('run_time') or '').strip()
            if not rt or ':' not in rt:
                continue
            parts = rt.split(':')
            h, m = int(parts[0]), int(parts[1])
            run_at_today = datetime.combine(now.date(), time(h, m))
        except Exception:
            continue

        last_run_at = _parse_db_datetime(t.get('last_run_at'))
        if now < run_at_today:
            continue
        if last_run_at is not None and last_run_at >= run_at_today:
            continue

        extra = (t.get('extra_prompt') or '').strip()
        start_dt, end_dt = _default_nga_summary_range_16h(now)
        out = _execute_nga_author_range_summary(
            tid=tid,
            author_id=author_id,
            start_dt=start_dt,
            end_dt=end_dt,
            group_id=gid,
            extra_prompt=extra,
        )
        if out.get('ok'):
            db2 = Database.Create()
            try:
                db2.update_nga_auto_summary_task_last_run(task_id, now)
            finally:
                db2.close()
            logger.info(
                "NGA 自动时段总结已执行 task_id=%s tid=%s author=%s reply_count=%s",
                task_id,
                tid,
                author_id,
                out.get('reply_count'),
            )
        else:
            logger.warning(
                "NGA 自动时段总结未成功 task_id=%s tid=%s author=%s: %s",
                task_id,
                tid,
                author_id,
                out.get('message'),
            )


@bp.route('/api/nga_export_author', methods=['GET'])
def export_nga_author_posts():
    """
    导出某帖中某作者在日期范围内的所有楼层，组织为文件并下载。
    参数：
      - tid: int
      - author_id: int
      - start_date: YYYY-MM-DD
      - end_date: YYYY-MM-DD（含当天）
      - format: md|txt（可选，默认 md）
    """
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        tid = request.args.get('tid', type=int)
        author_id = request.args.get('author_id', type=int)
        start_date_str = (request.args.get('start_date') or '').strip()
        end_date_str = (request.args.get('end_date') or '').strip()
        fmt = (request.args.get('format') or 'md').strip().lower()

        if not tid or tid < 1:
            return jsonify({'success': False, 'message': '缺少或无效参数 tid'}), 400
        if not author_id or author_id < 1:
            return jsonify({'success': False, 'message': '缺少或无效参数 author_id'}), 400
        if not start_date_str or not end_date_str:
            return jsonify({'success': False, 'message': '缺少参数 start_date 或 end_date'}), 400
        try:
            start_d = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_d = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except Exception:
            return jsonify({'success': False, 'message': '日期格式必须为 YYYY-MM-DD'}), 400
        if start_d > end_d:
            return jsonify({'success': False, 'message': 'start_date 不能晚于 end_date'}), 400
        if fmt not in ('md', 'txt'):
            fmt = 'md'

        thread = nga_db.get_thread_config(tid)
        thread_name = (thread or {}).get('name') or f"tid={tid}"

        floors = nga_db.get_floors_by_tid_author(tid=tid, author_id=author_id, limit=5000, offset=0)
        selected = []
        for f in floors:
            dt = _parse_nga_post_datetime(f.get('post_date') or '')
            if dt is None:
                continue
            d = dt.date()
            if start_d <= d <= end_d:
                selected.append((dt, f))

        selected.sort(key=lambda x: (x[0], x[1].get('floor_num', 0)))

        author_name = ''
        for _, f in selected:
            if f.get('author_name'):
                author_name = f['author_name']
                break

        title = f"NGA 导出：{thread_name}（tid={tid}）"
        subtitle = f"作者 uid={author_id}" + (f"（{author_name}）" if author_name else "")
        range_line = f"日期范围：{start_d.isoformat()} ~ {end_d.isoformat()}"

        lines = []
        if fmt == 'md':
            lines.append(f"# {title}")
            lines.append("")
            lines.append(f"- {subtitle}")
            lines.append(f"- {range_line}")
            lines.append("")
            for dt, f in selected:
                lines.append(f"## #{f['floor_num']} (pid={f['pid']})  {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                text = (f.get('content_text') or '').strip()
                if not text:
                    text = "(无内容)"
                lines.append("")
                lines.append(text)
                lines.append("")
        else:
            lines.append(title)
            lines.append(subtitle)
            lines.append(range_line)
            lines.append("")
            for dt, f in selected:
                lines.append(f"[#{f['floor_num']}] pid={f['pid']} {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                text = (f.get('content_text') or '').strip()
                lines.append(text if text else "(无内容)")
                lines.append("")

        content = "\n".join(lines).encode("utf-8")
        suffix = "md" if fmt == "md" else "txt"
        filename = f"nga_tid{tid}_uid{author_id}_{start_d.isoformat()}_{end_d.isoformat()}.{suffix}"

        resp = Response(content, mimetype="text/plain; charset=utf-8")
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp
    except Exception as e:
        logger.error(f"导出 NGA 作者发言失败: {str(e)}", exc_info=True)
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

        # 构造爬虫实例，复用 _send_wx（内部走 notify_channel 统一通道）
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


def _build_nga_floor_ai_explain_prompt(
    *,
    thread_name: str,
    tid: int,
    floor_num: int,
    pid: int,
    author_name: str,
    author_id: int,
    post_date: str,
    quote_text: str | None,
    content_text: str | None,
    user_prefix: str | None = None,
) -> str:
    """拼装发给 Gemini 的用户提示（中文），过长字段截断；可选前置说明由用户填写。"""
    q = (quote_text or "").strip()
    c = (content_text or "").strip()
    max_q, max_c = 8000, 12000
    q_trunc = q if len(q) <= max_q else q[:max_q] + "\n\n（引用部分已截断）"
    c_trunc = c if len(c) <= max_c else c[:max_c] + "\n\n（正文部分已截断）"
    blocks: list[str] = []
    up = (user_prefix or "").strip()
    if up:
        max_u = 4000
        if len(up) > max_u:
            up = up[:max_u] + "\n\n（前置说明已截断）"
        blocks.extend(
            [
                "【用户前置说明】（请在遵守安全与事实的前提下尽量落实；若与下文任务冲突，在无安全问题下优先本段）",
                up,
                "",
            ]
        )
    blocks.extend(
        [
            "请阅读以下来自 NGA 论坛某一楼层的「引用内容」与「作者正文」，用简体中文做详细解释。",
            "要求：",
            "1）先概括作者想表达的核心观点；",
            "2）若存在引用，说明引用与正文的关系、对话脉络；",
            "3）对可能的专业术语、梗、缩写做简短说明（若无法确定请标明是推测）；",
            "4）语气客观，条理清晰，可使用小标题与分点。",
            "",
            f"帖子标题：{thread_name or '(无)'}",
            f"tid={tid}，楼层 #{floor_num}，pid={pid}",
            f"作者：{author_name or '(未知)'}（uid={author_id}）",
            f"时间：{post_date or '(无)'}",
            "",
            "—— 引用（被回复/引用的内容）——",
            q_trunc if q_trunc else "（无引用）",
            "",
            "—— 作者正文 ——",
            c_trunc if c_trunc else "（无正文）",
        ]
    )
    return "\n".join(blocks)


@bp.route('/api/nga_floors/<int:tid>/<int:pid>/ai_explain', methods=['POST'])
def nga_floor_ai_explain(tid: int, pid: int):
    """
    调用 Gemini 根据本楼引用与正文生成详细解释，并通过统一通知通道（微信/飞书等）发送到该帖配置的消息群组。
    不写入 nga_sent_log（与「发送」原楼区分）。
    """
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        from Managers.gemini_client import (
            GeminiAuthError,
            GeminiClient,
            GeminiConfigError,
            GeminiRequestError,
            GeminiTransientError,
        )

        thread = nga_db.get_thread_config(tid)
        if not thread:
            return jsonify({'success': False, 'message': '帖子配置不存在'}), 404

        payload = request.get_json(silent=True) or {}
        extra_prompt = (payload.get('extra_prompt') or payload.get('prefix_prompt') or '').strip()

        raw_gid = payload.get('message_group_id')
        if raw_gid is None or str(raw_gid).strip() in ('', '0'):
            group_id = thread.get('message_group_id')
        else:
            group_id = str(raw_gid).strip()

        if group_id is None or str(group_id).strip() in ('', '0'):
            return jsonify({'success': False, 'message': '未选择有效的消息群组，请在弹窗中选择或为此帖配置默认群组'}), 400

        db_chk = Database.Create()
        try:
            db_chk.ensure_message_group_tables()
            valid_group_ids = {str(g.get('group_id', '') or '') for g in (db_chk.get_all_message_groups() or [])}
        finally:
            db_chk.close()
        gid_key = str(group_id).strip()
        if gid_key not in valid_group_ids:
            return jsonify({'success': False, 'message': '所选消息群组不存在，请从下拉列表中选择'}), 400

        floor = nga_db.get_floor_by_tid_pid(tid, pid)
        if not floor:
            return jsonify({'success': False, 'message': '楼层不存在'}), 404

        try:
            client = GeminiClient.from_config(config)
        except GeminiConfigError as e:
            return jsonify({'success': False, 'message': str(e)}), 400

        thread_name = (thread.get('name') or '').strip() or str(tid)
        prompt = _build_nga_floor_ai_explain_prompt(
            thread_name=thread_name,
            tid=tid,
            floor_num=int(floor['floor_num']),
            pid=int(floor['pid']),
            author_name=str(floor.get('author_name') or ''),
            author_id=int(floor['author_id']),
            post_date=str(floor.get('post_date') or ''),
            quote_text=floor.get('quote_text'),
            content_text=floor.get('content_text'),
            user_prefix=extra_prompt or None,
        )

        system_instruction = (
            "你是熟悉中文网络论坛语境的阅读助手，输出必须使用简体中文。"
            "只基于用户提供的引用与正文做解释，不要编造楼层中未出现的事实。"
        )

        try:
            result = client.generate(
                prompt,
                system_instruction=system_instruction,
                temperature=0.35,
                max_output_tokens=8192,
            )
        except GeminiAuthError as e:
            return jsonify({'success': False, 'message': str(e)}), 401
        except (GeminiRequestError, GeminiTransientError) as e:
            return jsonify({'success': False, 'message': str(e)}), 502

        ai_text = (result.text or "").strip()
        if not ai_text:
            return jsonify({'success': False, 'message': 'Gemini 未返回有效解释内容'}), 502

        header = (
            f"[NGA·AI解释] {thread_name} #{floor['floor_num']} "
            f"{floor.get('author_name') or ''} (uid={floor['author_id']}, pid={pid})\n"
            f"{'─' * 24}\n"
        )
        outbound = header + ai_text

        try:
            send_notify_to_group(int(str(group_id).strip()), outbound)
        except Exception as e:
            logger.error(f"AI 解释投递通知失败: {e}", exc_info=True)
            return jsonify({'success': False, 'message': f'解释已生成，但发送到群组失败: {e}'}), 500

        return jsonify({'success': True, 'message': 'AI 解释已发送到所选消息群组'})
    except Exception as e:
        logger.error(f"NGA 楼层 AI 解释失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_floors/<int:tid>/author_daily_summary', methods=['POST'])
def nga_author_daily_summary(tid: int):
    """
    将某关注作者在指定时间段内的已抓取回复拼成文本，调用 Gemini 做总结，
    并通过所选消息群组发送（与单楼 AI 解释相同通道）。
    JSON：author_id, start_datetime, end_datetime（ISO 或 datetime-local，区间为 [start, end)），
    message_group_id（可选）, extra_prompt（可选）。
    兼容旧参数 date=YYYY-MM-DD，等价于该自然日 [00:00, 次日 00:00)。
    """
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        thread = nga_db.get_thread_config(tid)
        if not thread:
            return jsonify({'success': False, 'message': '帖子配置不存在'}), 404

        payload = request.get_json(silent=True) or {}
        try:
            author_id = int(payload.get('author_id'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': '缺少或无效参数 author_id'}), 400

        start_dt = _parse_request_datetime(payload.get('start_datetime'))
        end_dt = _parse_request_datetime(payload.get('end_datetime'))
        if (start_dt is None or end_dt is None) and (payload.get('date') or '').strip():
            try:
                d0 = datetime.strptime((payload.get('date') or '').strip(), '%Y-%m-%d').date()
            except Exception:
                d0 = None
            if d0 is not None:
                start_dt = datetime.combine(d0, time.min)
                end_dt = datetime.combine(d0 + timedelta(days=1), time.min)
        if start_dt is None or end_dt is None:
            return jsonify(
                {'success': False, 'message': '请提供 start_datetime 与 end_datetime（或兼容参数 date）'}
            ), 400

        extra_prompt = (payload.get('extra_prompt') or payload.get('prefix_prompt') or '').strip()
        raw_gid = payload.get('message_group_id')
        if raw_gid is None or str(raw_gid).strip() in ('', '0'):
            group_id = thread.get('message_group_id')
        else:
            group_id = str(raw_gid).strip()

        out = _execute_nga_author_range_summary(
            tid=tid,
            author_id=author_id,
            start_dt=start_dt,
            end_dt=end_dt,
            group_id=str(group_id or '').strip(),
            extra_prompt=extra_prompt,
        )
        if not out.get('ok'):
            return jsonify({'success': False, 'message': out.get('message')}), int(out.get('http_status') or 500)
        body: dict = {'success': True, 'message': out.get('message')}
        if out.get('reply_count') is not None:
            body['reply_count'] = out['reply_count']
        return jsonify(body)
    except Exception as e:
        logger.error(f'NGA 按日总结失败: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


def _normalize_hhmm(s: str) -> str | None:
    s = (s or '').strip()
    if not s or ':' not in s:
        return None
    parts = s.split(':')
    if len(parts) < 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None
    if h < 0 or h > 23 or m < 0 or m > 59:
        return None
    return f'{h:02d}:{m:02d}'


@bp.route('/api/nga_floors/<int:tid>/auto_summary_tasks', methods=['GET'])
def list_nga_auto_summary_tasks_api(tid: int):
    """列出某帖下已保存的 NGA 自动时段总结任务。"""
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        thread = nga_db.get_thread_config(tid)
        if not thread:
            return jsonify({'success': False, 'message': '帖子配置不存在'}), 404
        db = Database.Create()
        try:
            rows = db.list_nga_auto_summary_tasks_by_tid(tid)
        finally:
            db.close()
        aids = []
        for r in rows:
            try:
                aids.append(int(r['author_id']))
            except (TypeError, ValueError):
                pass
        name_map = nga_db.resolve_author_names_for_tid(tid, sorted(set(aids))) if aids else {}
        out = []
        for r in rows:
            aid = int(r['author_id'])
            lr = r.get('last_run_at')
            if lr is not None and hasattr(lr, 'isoformat'):
                lr_s = lr.isoformat(sep=' ', timespec='seconds')
            else:
                lr_s = str(lr) if lr is not None else None
            cr = r.get('created_at')
            if cr is not None and hasattr(cr, 'isoformat'):
                cr_s = cr.isoformat(sep=' ', timespec='seconds')
            else:
                cr_s = str(cr) if cr is not None else None
            out.append(
                {
                    'id': int(r['id']),
                    'tid': int(r['tid']),
                    'author_id': aid,
                    'forum_name': (name_map.get(aid) or '').strip(),
                    'message_group_id': str(r.get('message_group_id') or ''),
                    'run_time': str(r.get('run_time') or ''),
                    'extra_prompt': r.get('extra_prompt') or '',
                    'enabled': bool(int(r.get('enabled') or 0)),
                    'last_run_at': lr_s,
                    'created_at': cr_s,
                }
            )
        return jsonify({'success': True, 'tasks': out})
    except Exception as e:
        logger.error(f'列出 NGA 自动总结任务失败: {e}', exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_floors/<int:tid>/auto_summary_tasks', methods=['POST'])
def create_nga_auto_summary_task_api(tid: int):
    """
    新增自动时段总结任务：每日 run_time 执行，对关注作者 uid 使用默认 [昨16:00,今16:00) 窗口。
    JSON: author_id, message_group_id, run_time (HH:MM), extra_prompt（可选）, enabled（可选，默认 1）
    """
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        thread = nga_db.get_thread_config(tid)
        if not thread:
            return jsonify({'success': False, 'message': '帖子配置不存在'}), 404
        watch_ids = thread.get('watch_author_ids') or []
        watch_set: set[int] = set()
        for x in watch_ids:
            try:
                watch_set.add(int(x))
            except (TypeError, ValueError):
                continue
        payload = request.get_json(silent=True) or {}
        try:
            author_id = int(payload.get('author_id'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': '缺少或无效参数 author_id'}), 400
        if author_id < 1 or author_id not in watch_set:
            return jsonify({'success': False, 'message': 'author_id 必须在本帖的关注作者列表中'}), 400
        rt = _normalize_hhmm(str(payload.get('run_time') or ''))
        if not rt:
            return jsonify({'success': False, 'message': 'run_time 须为 HH:MM（24 小时制）'}), 400
        raw_gid = payload.get('message_group_id')
        if raw_gid is None or str(raw_gid).strip() in ('', '0'):
            gid = thread.get('message_group_id')
        else:
            gid = str(raw_gid).strip()
        if gid is None or str(gid).strip() in ('', '0'):
            return jsonify({'success': False, 'message': '未选择有效的消息群组'}), 400
        db_chk = Database.Create()
        try:
            db_chk.ensure_message_group_tables()
            valid = {str(g.get('group_id', '') or '') for g in (db_chk.get_all_message_groups() or [])}
        finally:
            db_chk.close()
        if str(gid).strip() not in valid:
            return jsonify({'success': False, 'message': '所选消息群组不存在'}), 400
        extra = (payload.get('extra_prompt') or '').strip()
        en = int(payload.get('enabled', 1) or 0)
        en = 1 if en else 0
        db = Database.Create()
        try:
            ok, res = db.insert_nga_auto_summary_task(
                tid=tid,
                author_id=author_id,
                message_group_id=str(gid).strip(),
                run_time=rt,
                extra_prompt=extra or None,
                enabled=en,
            )
        finally:
            db.close()
        if not ok:
            return jsonify({'success': False, 'message': str(res)}), 400
        return jsonify({'success': True, 'message': '已保存自动任务', 'id': int(res)})
    except Exception as e:
        logger.error(f'创建 NGA 自动总结任务失败: {e}', exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/nga_floors/<int:tid>/auto_summary_tasks/<int:task_id>', methods=['DELETE'])
def delete_nga_auto_summary_task_api(tid: int, task_id: int):
    if nga_db is None:
        return jsonify({'success': False, 'message': 'NGA 模块未加载'}), 500
    try:
        db = Database.Create()
        try:
            row = db.get_nga_auto_summary_task_by_id(task_id)
            if not row or int(row['tid']) != int(tid):
                return jsonify({'success': False, 'message': '任务不存在'}), 404
            db.delete_nga_auto_summary_task(task_id)
        finally:
            db.close()
        return jsonify({'success': True, 'message': '已删除'})
    except Exception as e:
        logger.error(f'删除 NGA 自动总结任务失败: {e}', exc_info=True)
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
        out = [
            {
                'group_id': str(g.get('group_id', '') or ''),
                'name': (g.get('name') or '').strip(),
                'list_type': str(g.get('list_type') or ''),
                'chat_list': g.get('chat_list', []) or [],
            }
            for g in groups
        ]
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
            import nga_format  # type: ignore
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
    global sendAllMessage
    send_notify_fallback(sendAllMessage)


def SendSignalMessages(messages):
    send_notify_fallback(messages)


def SendFilterResultMessages(messages: str) -> None:
    """
    股票筛选系统结果推送：
    - 若配置了 NOTIFY.filter_result_group_ids（可多选），则逐个 group_id 推送
    - 否则回退到 send_notify_fallback（与历史行为一致）
    """
    try:
        from Managers.runtime_settings import get_filter_result_group_ids

        gids = get_filter_result_group_ids()
        if gids:
            for gid in gids:
                try:
                    send_notify_to_group(int(gid), messages)
                except Exception as e:
                    logger.error("筛选结果发送失败 group_id=%s: %s", gid, e, exc_info=True)
            return
    except Exception as e:
        logger.error("读取 filter_result_group_ids 失败，将走 fallback: %s", e, exc_info=True)
    send_notify_fallback(messages)

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
                    # 自动执行信号通知系统（价格区间等），并将触发结果并入消息队列
                    try:
                        latest_close = float(df.iloc[-1]['close'])
                        notify_messages = _run_signal_notify_for_stock(stock_code=stock['code'], price=latest_close)
                        for notify_msg in notify_messages:
                            signalsMessages.append(notify_msg)
                    except Exception as notify_err:
                        logger.warning("自动执行 signal_notify 失败 (%s): %s", stock['code'], notify_err)
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
        signal_params = {}
        raw_signal_params = (request.args.get('signalParams') or '').strip()
        if raw_signal_params:
            try:
                signal_params = json.loads(raw_signal_params) or {}
            except Exception:
                signal_params = {}
        data = {
            'market': request.args.get('market', 'CN'),
            'period': request.args.get('period', 'k1d'),
            'filterSignal': request.args.getlist('filterSignal'),
            'signalParams': signal_params,
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
                params_map = data.get('signalParams') or {}
                signal, avg_return, positive_prob = filter.filter_stock(
                    df, dayRange, filterSignals, target_date=target_date, signal_params=params_map
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
                time_module.sleep(float(delay))
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
            SendFilterResultMessages(msg)
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