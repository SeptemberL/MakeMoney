"""
NGA 关注作者「时段总结」自动任务：由 main 定时线程调用。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_due_nga_auto_summary_tasks_safe() -> None:
    try:
        from routes import _run_nga_auto_summary_due_tasks_impl

        _run_nga_auto_summary_due_tasks_impl()
    except Exception as e:
        logger.error("NGA 自动时段总结 tick 失败: %s", e, exc_info=True)
