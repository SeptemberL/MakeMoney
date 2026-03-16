from flask import jsonify
from database.database import Database
import logging
import threading
import time
from typing import Callable, Any, Optional
from Scans.ScheduledTask import ScheduledTask

# 设置日志
logger = logging.getLogger(__name__)

class ScanManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_db()
        return cls._instance
    
    def _init_db(self):
        """初始化数据库连接、任务容器，并检查表是否存在"""
        self.tasks = {}  # 显式初始化，避免 add_task/remove_task 等访问时 AttributeError
        self._check_table()
        
    
    def _check_table(self):
        """确保 stock_tools_scan 表存在（MySQL/SQLite 双模式）"""
        db = None
        try:
            db = Database.Create()
            if db.is_sqlite:
                query = """
                CREATE TABLE IF NOT EXISTS stock_tools_scan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    data TEXT
                )
                """
            else:
                query = """
                CREATE TABLE IF NOT EXISTS stock_tools_scan (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(10) NOT NULL UNIQUE,
                    data TEXT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            db.execute(query)
            logger.info("stock_tools_scan 表已就绪")
        except Exception as e:
            logger.error("创建/检查 stock_tools_scan 表失败: %s", str(e), exc_info=True)
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass
     
    def SaveTimedScan(self, jsonData):
        db = None
        try:
            logger.info("保存定时扫描: %s", jsonData.get("scanName"))
            db = Database.Create()
            insert_query = """
                INSERT INTO stock_tools_scan (name, data) 
                VALUES (%s, %s)
                """
            db.execute(insert_query, (jsonData["scanName"], str(jsonData)))
            return True, jsonify({"success": True, "message": "定时扫描数据已保存"})
        except Exception as e:
            logger.error("添加定时扫描失败: %s", str(e), exc_info=True)
            return False, jsonify({"success": False, "error": str(e)})
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    def GetTimedScanList(self):
        """获取定时扫描列表。返回 list[dict] 含 id、name。"""
        db = None
        try:
            db = Database.Create()
            query = "SELECT * FROM stock_tools_scan ORDER BY id"
            results = db.fetch_all(query)
            out = []
            for row in results:
                if isinstance(row, dict):
                    out.append({"id": row["id"], "name": row["name"]})
                else:
                    # 列顺序: id, name, data
                    out.append({"id": row[0], "name": row[1]})
            return out
        except Exception as e:
            logger.error("获取定时扫描列表失败: %s", str(e), exc_info=True)
            return []
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass


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
            logger.warning("任务已存在，跳过添加: task_id=%s", task_id)
            return False
        task = ScheduledTask(task_id, func, interval, *args, **kwargs)
        self.tasks[task_id] = task
        logger.info("已添加任务: task_id=%s, interval=%s", task_id, interval)
        return True

    def remove_task(self, task_id: str) -> bool:
        """
        移除任务
        
        :param task_id: 要移除的任务ID
        :return: 是否移除成功
        """
        task = self.tasks.pop(task_id, None)
        if task is None:
            logger.warning("任务不存在，无法移除: task_id=%s", task_id)
            return False
        task.stop()
        logger.info("已移除任务: task_id=%s", task_id)
        return True

    def start_task(self, task_id: str) -> bool:
        """
        启动任务
        
        :param task_id: 要启动的任务ID
        :return: 是否启动成功
        """
        task = self.tasks.get(task_id)
        if task is None:
            logger.warning("任务不存在，无法启动: task_id=%s", task_id)
            return False
        if not task.is_running():
            task.start()
            logger.info("已启动任务: task_id=%s", task_id)
        return True

    def stop_task(self, task_id: str) -> bool:
        """
        停止任务
        
        :param task_id: 要停止的任务ID
        :return: 是否停止成功
        """
        task = self.tasks.get(task_id)
        if task is None:
            logger.warning("任务不存在，无法停止: task_id=%s", task_id)
            return False
        if task.is_running():
            task.stop()
            logger.info("已停止任务: task_id=%s", task_id)
        return True

    def start_all(self) -> None:
        """启动所有任务"""
        for task_id, task in self.tasks.items():
            if not task.is_running():
                task.start()
                logger.info("已启动任务: task_id=%s", task_id)
        logger.info("start_all 完成, 共 %s 个任务", len(self.tasks))

    def stop_all(self) -> None:
        """停止所有任务"""
        for task_id, task in self.tasks.items():
            if task.is_running():
                task.stop()
                logger.info("已停止任务: task_id=%s", task_id)
        logger.info("stop_all 完成, 共 %s 个任务", len(self.tasks))

    def list_tasks(self) -> list[dict]:
        """获取所有任务信息"""
        return [{
            "task_id": task_id,
            "function": getattr(task.func, "__name__", repr(task.func)),
            "interval": task.interval,
            "running": task.is_running(),
        } for task_id, task in self.tasks.items()]

    def task_exists(self, task_id: str) -> bool:
        """检查任务是否存在"""
        return task_id in self.tasks

    def clear_all(self) -> None:
        """清除所有任务"""
        n = len(self.tasks)
        self.stop_all()
        self.tasks.clear()
        logger.info("已清除全部任务: 共 %s 个", n)


if __name__ == "__main__":
    # 阶段 1.4 验收：添加任务 → 启动 → 停止 → 删除，过程中不报错
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    def dummy_job():
        pass

    mgr = ScanManager()
    assert mgr.tasks == {}
    ok_add = mgr.add_task("test_1", dummy_job, 60.0)
    assert ok_add is True and "test_1" in mgr.tasks
    ok_start = mgr.start_task("test_1")
    assert ok_start is True and mgr.tasks["test_1"].is_running()
    ok_stop = mgr.stop_task("test_1")
    assert ok_stop is True and not mgr.tasks["test_1"].is_running()
    ok_remove = mgr.remove_task("test_1")
    assert ok_remove is True and "test_1" not in mgr.tasks
    print("ScanManager 验收通过: 添加 → 启动 → 停止 → 删除 无报错")
