# -*- coding: UTF-8 -*-
"""
NGA 监控调度器
- 加载 configs/nga.yaml 配置
- 初始化数据库表
- 按配置的 poll_interval 定时调用每个帖子的 crawler.crawl_once()
- 支持独立运行（python nga_monitor.py）
  也支持由项目 TaskManager / scheduler 集成调用
"""
import sys
import os
import time
import logging
import platform
import threading
from pathlib import Path
from typing import Dict, List

import yaml

# ── 路径配置：将项目根目录加入 sys.path ─────────────────────────────────────
_THIS_DIR    = Path(__file__).parent
_PROJECT_DIR = _THIS_DIR.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

import nga_db
from nga_crawler import NGACrawler

logger = logging.getLogger('nga_monitor')


# ──────────────────────────── 配置加载 ──────────────────────────────────────

def load_config(config_path: str = None) -> dict:
    path = config_path or str(_THIS_DIR / 'configs' / 'nga.yaml')
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


# ──────────────────────────── 监控器 ────────────────────────────────────────

class NGAMonitor:
    """
    多帖子监控器
    每个启用的帖子对应一个 NGACrawler 实例，
    统一在一个后台线程里按 poll_interval 循环调度
    """

    def __init__(self, config_path: str = None, wx=None):
        self.cfg          = load_config(config_path)
        self.wx           = wx
        self._stop_event  = threading.Event()
        self.crawlers: List[NGACrawler] = []

    def _init(self):
        """初始化 DB 表 + 构建 crawler 列表"""
        nga_db.init_tables()

        auth_cfg = self.cfg.get('auth', {})
        threads  = self.cfg.get('threads', [])

        for th in threads:
            if not th.get('enabled', True):
                logger.info(f"跳过禁用帖子 tid={th.get('tid')}")
                continue
            tid = int(th['tid'])
            crawler = NGACrawler(tid=tid, thread_cfg=th, auth_cfg=auth_cfg, wx=self.wx)
            self.crawlers.append(crawler)
            logger.info(f"已注册监控帖子: [{crawler.name}] tid={tid}")

        logger.info(f"共注册 {len(self.crawlers)} 个帖子的监控")

    def start(self, block: bool = True) -> None:
        """
        启动监控
        :param block: True = 阻塞当前线程（脚本直接运行时用）
                      False = 在后台线程运行（集成到 Flask/APScheduler 时用）
        """
        self._init()

        interval = int(self.cfg.get('settings', {}).get('poll_interval', 30))
        logger.info(f'监控启动，轮询间隔 {interval} 秒')

        if block:
            self._loop(interval)
        else:
            t = threading.Thread(target=self._loop, args=(interval,), daemon=True)
            t.start()

    def stop(self) -> None:
        self._stop_event.set()
        logger.info('监控已停止')

    def _loop(self, interval: int) -> None:
        while not self._stop_event.is_set():
            for crawler in self.crawlers:
                if self._stop_event.is_set():
                    break
                try:
                    crawler.crawl_once()
                except Exception as e:
                    logger.error(f'[{crawler.name}] crawl_once 异常: {e}', exc_info=True)

            # 等待下一个轮询周期（可被 stop() 中断）
            self._stop_event.wait(timeout=interval)


# ──────────────────────────── 集成入口（供 TaskManager 调用） ────────────────

_monitor_instance: NGAMonitor = None


def start_nga_monitor():
    """
    供 TaskManager / scheduler_system 动态加载并调用的函数入口
    （module_path='nga_spider.nga_monitor', function_name='start_nga_monitor'）
    保证单例，重复调用无副作用
    """
    global _monitor_instance
    if _monitor_instance is not None:
        logger.info('NGA 监控已在运行，跳过重复启动')
        return

    wx = None
    try:
        from stock_global import stockGlobal
        wx = stockGlobal.wx
    except Exception:
        pass

    _monitor_instance = NGAMonitor(wx=wx)
    _monitor_instance.start(block=False)


# ──────────────────────────── 独立运行 ──────────────────────────────────────

def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(_THIS_DIR / 'nga_monitor.log'), encoding='utf-8'),
        ]
    )


if __name__ == '__main__':
    _setup_logging()

    wx = None
    if platform.system() == 'Windows':
        try:
            import sys
            sys.path.insert(0, str(_PROJECT_DIR))
            import wxauto
            from stock_global import stockGlobal
            if stockGlobal.wx:
                wx = stockGlobal.wx
            else:
                wx = wxauto.WeChat()
                logger.info('微信实例已创建')
        except Exception as e:
            logger.warning(f'微信初始化失败，推送将以日志模拟: {e}')

    monitor = NGAMonitor(wx=wx)
    try:
        monitor.start(block=True)   # 阻塞运行
    except KeyboardInterrupt:
        monitor.stop()
        logger.info('用户中断，退出')
