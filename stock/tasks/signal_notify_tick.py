from __future__ import annotations

import logging

from Managers.runtime_settings import get_setting
from signals.signal_notify_runner import run_signal_notify_tick

logger = logging.getLogger(__name__)


def run_signal_notify_tick_job():
    """
    APScheduler 任务入口：执行一次“全量信号扫描 tick”。
    - 是否交易时间由 run_signal_notify_tick(force=False) 内部判断
    - interval 秒数由 scheduled_task.trigger_args 控制（由启动时按 settings 写入）
    """
    try:
        # 读取一次配置，便于日志观测（实际节拍由调度器控制）
        interval = get_setting("SIGNAL_NOTIFY", "update_interval_seconds", "15")
        logger.info("signal_notify_tick_job: interval_setting=%s", interval)
    except Exception:
        pass
    return run_signal_notify_tick(force=False)

