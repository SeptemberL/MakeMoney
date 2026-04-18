import os
import sys
from pathlib import Path

# 确保项目根目录（main.py 所在目录）在 sys.path 最前，便于 nga_spider 等包被正确导入
_MAIN_DIR = Path(__file__).resolve().parent
if str(_MAIN_DIR) not in sys.path:
    sys.path.insert(0, str(_MAIN_DIR))

from flask import Flask
from stocks.stock_fetcher import StockFetcher
from stocks.stock_analyzer import StockAnalyzer
import platform
from init_project import init_project, setup_logging
import akshare as ak
from config import Config
from database.database import Database
from stock_list_manager import StockListManager
from indicator_manager import IndicatorManager
import traceback

# 设置更详细的错误捕获
sys.excepthook = lambda exc_type, exc_value, exc_traceback: (
    print("=" * 60),
    print("未捕获的异常:"),
    traceback.print_exception(exc_type, exc_value, exc_traceback),
    print("=" * 60),
    input("按 Enter 退出...")
)

try:
    from routes import bp
except Exception as e:
    import traceback
    traceback.print_exc() 

import threading
import schedule
import time
from stocks.stock_global import stockGlobal
from flask_socketio import SocketIO, emit

from Managers.scheduler_system import TaskManager
from Managers.scheduled_task_sync import sync_scheduled_tasks_yaml_to_db
from Managers.runtime_settings import get_setting
from Managers.scheduler_system import TaskConfig, TriggerType

# NGA 爬虫：根据数据库 nga_thread_config 中 auto_run 开关自动运行
try:
    from nga_spider.nga_monitor import start_nga_monitor
except Exception as e:
    import traceback
    traceback.print_exc()
    start_nga_monitor = None

if platform.system() == 'Windows':
    import wxauto
    from wxauto import *

#from flask_mysqldb import MySQL

# 获取项目根目录和初始化项目
BASE_DIR = Path(__file__).parent



# 设置日志
logger = setup_logging(BASE_DIR)

# 初始化配置
config = Config()

# 创建Flask应用
app = Flask(__name__)
app.config['MYSQL_HOST'] = config.get('DATABASE', 'DB_HOST') 
app.config['MYSQL_PORT'] = config.get('DATABASE', 'DB_PORT') # MySQL主机地址
app.config['MYSQL_USER'] = config.get('DATABASE', 'DB_USER') # MySQL用户名
app.config['MYSQL_PASSWORD'] = config.get('DATABASE', 'DB_PASSWORD') # MySQL密码
app.config['MYSQL_DB'] = config.get('DATABASE', 'DB_NAME') # MySQL数据库名
app.secret_key = 'your-secret-key-here'  # 请更改为随机字符串


# 确保当前数据库（MySQL / SQLite）中的业务表已创建
try:
    db = Database.Create()
    db.init_database()
    db.close()
    logger.info("数据库结构已初始化（如不存在则创建 positions / transactions / portfolio 等表）")
except Exception as e:
    logger.error("初始化数据库结构失败: %s", e, exc_info=True)


# 注册蓝图
app.register_blueprint(bp)

def run_schedule():
    """运行定时任务"""
    with app.app_context():
        #schedule.every().day.at("15:10").do(bp.update_all_stocks_api)
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == '__main__':
    # 确保项目初始化
    #if not os.path.exists(DB_PATH):
    #    from init_project import init_project
    #    init_project()
    
    if config.get_boolean('WX', 'EnableWX') == True:
        logger.info(f"已打开微信通知")
        if platform.system() == 'Windows':
            stockGlobal.wx = wxauto.WeChat()

    # 启动定时任务
    schedule_thread = threading.Thread(target=run_schedule)
    schedule_thread.daemon = True
    schedule_thread.start()

    taskManager = TaskManager(config_file=str(BASE_DIR / "configs" / "tasks_config.yaml"))

    db_tm = Database.Create()
    try:
        sync_scheduled_tasks_yaml_to_db(db_tm, BASE_DIR / "configs" / "tasks_config.yaml")
        if not taskManager.load_configs_from_database(db_tm):
            logger.error("从数据库加载定时任务失败，调度器可能无任务")
    finally:
        db_tm.close()

    # ─────────────────────────── 内置任务：交易时间信号扫描 ────────────────────────────
    # 目标：启动后即存在一条 interval 任务；周期秒数从 settings_console 写入的 DB 配置读取
    try:
        sec_raw = get_setting("SIGNAL_NOTIFY", "update_interval_seconds", "15")
        try:
            sec = int(float(sec_raw))
        except Exception:
            sec = 15
        if sec < 5:
            sec = 5
        cfg = TaskConfig(
            task_id="task_signal_notify_tick",
            task_name="交易时间信号扫描（interval）",
            module_path="tasks.signal_notify_tick",
            function_name="run_signal_notify_tick_job",
            trigger_type=TriggerType.INTERVAL,
            trigger_args={"seconds": sec},
            enabled=True,
            max_instances=1,
            misfire_grace_time=30,
            coalesce=True,
            description="交易时间每N秒全量扫描 signal_rule 并触发通知；N 来自系统设置 SIGNAL_NOTIFY.update_interval_seconds。",
        )
        db_tm2 = Database.Create()
        try:
            taskManager.persist_task_to_database(db_tm2, cfg)
            # 写入后重新从数据库加载一遍（保证本轮启动已注册到 scheduler）
            taskManager.load_configs_from_database(db_tm2)
        finally:
            db_tm2.close()
    except Exception as e:
        logger.error("初始化 signal_notify tick 任务失败: %s", e, exc_info=True)

    # ─────────────────────────── 内置任务：信号 state 写入缓冲落库（Redis 可选） ────────────────────────────
    try:
        enabled = str(get_setting("REDIS", "signal_state_buffer_enabled", "0") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if enabled:
            sec_raw = get_setting("REDIS", "signal_state_flush_interval_seconds", "3")
            try:
                sec = int(float(sec_raw))
            except Exception:
                sec = 3
            if sec < 1:
                sec = 1
            cfg = TaskConfig(
                task_id="task_signal_state_flush",
                task_name="信号 state 缓冲落库（interval）",
                module_path="tasks.signal_state_flush",
                function_name="run_signal_state_flush_job",
                trigger_type=TriggerType.INTERVAL,
                trigger_args={"seconds": sec},
                enabled=True,
                max_instances=1,
                misfire_grace_time=30,
                coalesce=True,
                description="当开启 REDIS.signal_state_buffer_enabled 时，将 signal_rule_state 的写入先缓冲到 Redis，再定时批量落库。",
            )
            db_tm3 = Database.Create()
            try:
                taskManager.persist_task_to_database(db_tm3, cfg)
                taskManager.load_configs_from_database(db_tm3)
            finally:
                db_tm3.close()
    except Exception as e:
        logger.error("初始化 signal_state_flush 任务失败: %s", e, exc_info=True)

    # 启动后先跑一次（force=true）：让新建/刚启用的规则立刻生效（非交易时间也可用于验证）
    try:
        from signals.signal_notify_runner import run_signal_notify_tick

        st = run_signal_notify_tick(force=True)
        logger.info("启动首轮 signal_notify 扫描完成: %s", st)
    except Exception as e:
        logger.warning("启动首轮 signal_notify 扫描失败: %s", e, exc_info=True)

    taskManager.start()

    app.config['TASK_MANAGER'] = taskManager

    # 启动 NGA 爬虫：仅对数据库中 auto_run=1 的帖子进行监控
    if start_nga_monitor is not None:
        start_nga_monitor()
    else:
        logger.warning("NGA 监控模块未加载，跳过 NGA 爬虫启动")

    #stockGlobal.socketio = SocketIO(app, cors_allowed_origins="*")

    
    # 启动Flask应用
    app.run(host='0.0.0.0', port=5123, debug=False) 