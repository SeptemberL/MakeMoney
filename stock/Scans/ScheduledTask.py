import threading
import time
from typing import Callable, Any, Optional

class ScheduledTask:
    def __init__(self, task_id: str, func: Callable[..., Any], interval: float, 
                 *args: Any, **kwargs: Any):
        """
        定时任务类
        
        :param task_id: 任务ID
        :param func: 要执行的函数
        :param interval: 执行间隔(秒)
        :param args: 函数位置参数
        :param kwargs: 函数关键字参数
        """
        self.task_id = task_id
        self.func = func
        self.interval = interval
        self.args = args
        self.kwargs = kwargs
        self._timer: Optional[threading.Timer] = None
        self._is_running = False
        self._last_execution_time: Optional[float] = None

    def start(self) -> None:
        """启动定时任务"""
        if not self._is_running:
            self._is_running = True
            self._schedule_next_run()

    def stop(self) -> None:
        """停止定时任务"""
        if self._timer is not None:
            self._timer.cancel()
        self._is_running = False

    def _run(self) -> None:
        """执行任务并安排下一次运行"""
        if self._is_running:
            try:
                self.func(*self.args, **self.kwargs)
            except Exception as e:
                print(f"Task {self.task_id} error: {e}")
            finally:
                self._last_execution_time = time.time()
                self._schedule_next_run()

    def _schedule_next_run(self) -> None:
        """安排下一次任务执行"""
        if self._is_running:
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.daemon = True
            self._timer.start()

    def is_running(self) -> bool:
        """检查任务是否正在运行"""
        return self._is_running

    def __repr__(self) -> str:
        return (f"ScheduledTask(task_id={self.task_id!r}, func={self.func.__name__}, "
                f"interval={self.interval}, running={self._is_running})")


class TaskManager:
    def __init__(self):
        """任务管理器"""
        self.tasks: dict[str, ScheduledTask] = {}

    def add_task(self, task_id: str, func: Callable[..., Any], interval: float, 
                 *args: Any, **kwargs: Any) -> bool:
        """
        添加新任务
        
        :param task_id: 任务ID
        :param func: 要执行的函数
        :param interval: 执行间隔(秒)
        :param args: 函数位置参数
        :param kwargs: 函数关键字参数
        :return: 是否添加成功
        """
        if task_id in self.tasks:
            print(f"Task ID {task_id} already exists")
            return False
        
        task = ScheduledTask(task_id, func, interval, *args, **kwargs)
        self.tasks[task_id] = task
        return True

    def remove_task(self, task_id: str) -> bool:
        """
        移除任务
        
        :param task_id: 要移除的任务ID
        :return: 是否移除成功
        """
        task = self.tasks.pop(task_id, None)
        if task is None:
            print(f"Task ID {task_id} not found")
            return False
        
        task.stop()
        return True

    def start_task(self, task_id: str) -> bool:
        """
        启动任务
        
        :param task_id: 要启动的任务ID
        :return: 是否启动成功
        """
        task = self.tasks.get(task_id)
        if task is None:
            print(f"Task ID {task_id} not found")
            return False
        
        if not task.is_running():
            task.start()
        return True

    def stop_task(self, task_id: str) -> bool:
        """
        停止任务
        
        :param task_id: 要停止的任务ID
        :return: 是否停止成功
        """
        task = self.tasks.get(task_id)
        if task is None:
            print(f"Task ID {task_id} not found")
            return False
        
        if task.is_running():
            task.stop()
        return True

    def start_all(self) -> None:
        """启动所有任务"""
        for task in self.tasks.values():
            if not task.is_running():
                task.start()

    def stop_all(self) -> None:
        """停止所有任务"""
        for task in self.tasks.values():
            if task.is_running():
                task.stop()

    def list_tasks(self) -> list[dict]:
        """获取所有任务信息"""
        return [{
            'task_id': task_id,
            'function': task.func.__name__,
            'interval': task.interval,
            'running': task.is_running()
        } for task_id, task in self.tasks.items()]

    def task_exists(self, task_id: str) -> bool:
        """检查任务是否存在"""
        return task_id in self.tasks

    def clear_all(self) -> None:
        """清除所有任务"""
        self.stop_all()
        self.tasks.clear()