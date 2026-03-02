import os
from pathlib import Path
from flask import Flask
from stock_fetcher import StockFetcher
from stock_analyzer import StockAnalyzer
import platform
from init_project import init_project, setup_logging
import akshare as ak
from config import Config
from database.database import Database
from stock_list_manager import StockListManager
from indicator_manager import IndicatorManager
import sys
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
from stock_global import stockGlobal
from flask_socketio import SocketIO, emit

from Managers.scheduler_system import TaskManager

# NGA 爬虫：根据数据库 nga_thread_config 中 auto_run 开关自动运行
try:
    from nga_spider.nga_monitor import start_nga_monitor
except Exception:
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
app.config['MYSQL_USER'] = config.get_int('DATABASE', 'DB_USER') # MySQL用户名
app.config['MYSQL_PASSWORD'] = config.get('DATABASE', 'DB_PASSWORD') # MySQL密码
app.config['MYSQL_DB'] = config.get('DATABASE', 'DB_NAME') # MySQL数据库名
app.secret_key = 'your-secret-key-here'  # 请更改为随机字符串



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

    taskManager = TaskManager(config_file="configs/tasks_config.yaml")
    
    # 加载配置
    taskManager.load_configs()
    
    # 启动调度器
    taskManager.start()

    # 启动 NGA 爬虫：仅对数据库中 auto_run=1 的帖子进行监控
    if start_nga_monitor is not None:
        start_nga_monitor()
    else:
        logger.warning("NGA 监控模块未加载，跳过 NGA 爬虫启动")

    #stockGlobal.socketio = SocketIO(app, cors_allowed_origins="*")

    
    # 启动Flask应用
    app.run(host='0.0.0.0', port=5123, debug=True) 