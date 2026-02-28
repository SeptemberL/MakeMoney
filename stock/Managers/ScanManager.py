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
        """初始化数据库连接并检查表是否存在"""
        self._check_table()
        
    
    def _check_table(self):
        try:
            db = Database.Create()
            query = """
                 CREATE TABLE IF NOT EXISTS stock_tools_scan (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(10) NOT NULL UNIQUE,
                    data TEXT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            cursor = db.execute(query)
            
        
            db.close()
            return
            
        except Exception as e:
            logger.error(f"获取项目列表失败: {str(e)}", exc_info=True)
            return
        finally:
            db.close()
     
    def SaveTimedScan(self, jsonData):
        try:
            print("接收到的数据：", jsonData)

            # 在此处调用数据库操作函数
            db = Database.Create()
            # 检查股票是否已存在
            
            # 插入新记录
            insert_query = """
                INSERT INTO stock_tools_scan (name, data) 
                VALUES (%s, %s)
                """
            db.execute(insert_query, (jsonData['scanName'], str(jsonData)))

            return True, jsonify({"success": True, "message": "定时扫描数据已保存"})
        except Exception as e:
                logger.error(f"添加定时扫描失败: {str(e)}")
                return False, jsonify({"success": False, "error": str(e)})
        finally:
            db.close()

    #获取定时扫描列表
    def GetTimedScanList(self):
        try:
            db = Database.Create()
            query = "SELECT * FROM stock_tools_scan ORDER BY id"
            results = db.fetch_all(query)
            
            # 处理查询结果
            stocks = []
            for row in results:
                # 根据返回类型处理结果
                if isinstance(row, dict):
                    # 如果已经是字典格式
                    stocks.append({'id': row['id'], 'name': row['name']})
                else:
                    # 如果是元组格式
                    stocks.append({'code': row[0], 'name': row[1]})
            return stocks
            
        except Exception as e:
            logger.error(f"获取定时扫描列表失败: {str(e)}")
            return []
        finally:
            db.close()


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
