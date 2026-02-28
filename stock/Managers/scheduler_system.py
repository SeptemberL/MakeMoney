# scheduler_system_fixed_final.py
import yaml
import logging
from datetime import datetime
from typing import Dict, Any, Callable, Optional, Union
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import importlib
import sys
import traceback

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED

class TriggerType(Enum):
    CRON = "cron"
    INTERVAL = "interval"
    DATE = "date"

@dataclass
class TaskConfig:
    """任务配置类"""
    task_id: str
    task_name: str
    module_path: str  # 模块路径，如：task_functions.file_ops
    function_name: str  # 函数名
    trigger_type: TriggerType
    trigger_args: Dict[str, Any]
    enabled: bool = True
    max_instances: int = 1
    misfire_grace_time: Optional[int] = None
    coalesce: bool = True
    description: str = ""
    args: tuple = ()
    kwargs: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data['trigger_type'] = self.trigger_type.value
        # 移除不能序列化的字段
        data.pop('args', None)
        data.pop('kwargs', None)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskConfig':
        """从字典创建"""
        data['trigger_type'] = TriggerType(data['trigger_type'])
        data['args'] = data.get('args', ())
        data['kwargs'] = data.get('kwargs', {})
        return cls(**data)

class TaskExecutor:
    """任务执行器，专门用于执行字符串引用的函数"""
    
    logger = None

    @staticmethod
    def execute_function(module_path: str, function_name: str, 
                        task_id: str = None, task_name: str = None,
                        args: tuple = (), kwargs: Dict[str, Any] = None):
        """
        执行指定模块的函数
        
        Args:
            module_path: 模块路径
            function_name: 函数名
            task_id: 任务ID（用于日志）
            task_name: 任务名称（用于日志）
            args: 函数参数
            kwargs: 函数关键字参数
        """
        logger = logging.getLogger('TaskExecutor')
        task_identifier = task_name or task_id or f"{module_path}.{function_name}"
        
        try:
            logger.info(f"开始执行任务: {task_identifier}")
            start_time = datetime.now()
            
            # 动态导入模块
            module = importlib.import_module(module_path)
            
            # 获取函数
            func = getattr(module, function_name)
            
            # 执行函数
            result = func(*args, **(kwargs or {}))
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logger.info(f"任务完成: {task_identifier}, 耗时: {duration:.2f}秒")
            return result
            
        except ImportError as e:
            error_msg = f"导入模块失败: {module_path}, 错误: {e}"
            logger.error(error_msg)
            raise ImportError(error_msg)
        except AttributeError as e:
            error_msg = f"模块中未找到函数: {function_name}, 错误: {e}"
            logger.error(error_msg)
            raise AttributeError(error_msg)
        except Exception as e:
            error_msg = f"任务执行失败: {task_identifier}, 错误: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise

class TaskManager:
    """完全修复序列化问题的任务管理器"""
    
    logger = None

    def __init__(self, config_file: str = "tasks_config.yaml", 
                 use_persistence: bool = False,
                 db_url: str = "sqlite:///jobs.db"):
        """
        初始化任务管理器
        
        Args:
            config_file: 配置文件路径
            use_persistence: 是否使用持久化存储
            db_url: 数据库URL，用于持久化任务
        """

        logger = logging.getLogger('TaskMagager')

        self.config_file = config_file
        
        # 根据是否持久化选择不同的jobstore
        if use_persistence:
            jobstores = {'default': SQLAlchemyJobStore(url=db_url)}
            logger.info(f"使用持久化存储: {db_url}")
        else:
            jobstores = {'default': MemoryJobStore()}
            logger.info("使用内存存储")
        
        # 创建调度器
        self.scheduler = BackgroundScheduler(
            jobstores=jobstores,
            job_defaults={
                'coalesce': True,
                'max_instances': 3,
                'misfire_grace_time': 30
            }
        )
        
        # 设置事件监听
        self._setup_event_listeners()
        
        self.tasks: Dict[str, TaskConfig] = {}
        self.logger = self._setup_logger()
        self.use_persistence = use_persistence
    
    def _setup_logger(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger('TaskManager')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            # 控制台处理器
            console_handler = logging.StreamHandler()
            console_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)
        
        return logger
    
    def _setup_event_listeners(self):
        """设置事件监听器"""
        def job_executed(event):
            if event.exception:
                self.logger.error(f"任务执行失败: {event.job_id}")
                self.logger.error(traceback.format_exc())
            else:
                self.logger.info(f"任务执行成功: {event.job_id}")
        
        def job_missed(event):
            self.logger.warning(f"任务错过执行: {event.job_id}")
        
        self.scheduler.add_listener(job_executed, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        self.scheduler.add_listener(job_missed, EVENT_JOB_MISSED)

    def load_module_function(self, module_path: str, function_name: str) -> Callable:
        """
        动态加载模块函数
        
        Args:
            module_path: 模块路径，如：package.module
            function_name: 函数名
            
        Returns:
            可调用函数
        """
        try:
            module = __import__(module_path, fromlist=[function_name])
            func = getattr(module, function_name)
            return func
        except ImportError as e:
            self.logger.error(f"导入模块失败: {module_path}, 错误: {e}")
            raise
        except AttributeError as e:
            self.logger.error(f"模块中未找到函数: {function_name}, 错误: {e}")
            raise
    
    def add_task(self, config: TaskConfig) -> bool:
        """
        添加定时任务（完全修复序列化问题）
        
        关键：使用字符串格式的函数引用，而不是函数对象
        
        Args:
            config: 任务配置
            
        Returns:
            是否添加成功
        """
        try:
            # 创建触发器
            if config.trigger_type == TriggerType.CRON:
                trigger = CronTrigger(**config.trigger_args)
            elif config.trigger_type == TriggerType.INTERVAL:
                trigger = IntervalTrigger(**config.trigger_args)
            elif config.trigger_type == TriggerType.DATE:
                trigger = DateTrigger(**config.trigger_args)
            else:
                raise ValueError(f"不支持的触发器类型: {config.trigger_type}")
            
            func = self.load_module_function(config.module_path, config.function_name)

            # 关键点：使用字符串引用TaskExecutor.execute_function
            # 并传递模块路径和函数名作为参数
            job_kwargs = {
                'func': func,
                #'args': (config.module_path, config.function_name, 
                #        config.task_id, config.task_name,
                #        config.args, config.kwargs),
                'trigger': trigger,
                'id': config.task_id,
                'name': config.task_name,
                'max_instances': config.max_instances,
                'coalesce': config.coalesce,
                'replace_existing': True
            }
            
            # 如果有misfire_grace_time，添加它
            if config.misfire_grace_time is not None:
                job_kwargs['misfire_grace_time'] = config.misfire_grace_time
            
            # 添加任务到调度器
            self.scheduler.add_job(**job_kwargs)
            
            self.tasks[config.task_id] = config
            self.logger.info(f"成功添加任务: {config.task_name} (ID: {config.task_id})")
            
            # 立即测试任务是否可以执行
            self._test_task_execution(config)
            
            return True
            
        except Exception as e:
            self.logger.error(f"添加任务失败: {config.task_name}, 错误: {e}", 
                            exc_info=True)
            return False
    
    def _test_task_execution(self, config: TaskConfig):
        """测试任务是否可以正常执行"""
        try:
            self.logger.info(f"测试任务执行: {config.task_name}")
            TaskExecutor.execute_function(
                config.module_path,
                config.function_name,
                config.task_id,
                config.task_name,
                config.args,
                config.kwargs
            )
            self.logger.info(f"任务测试通过: {config.task_name}")
        except Exception as e:
            self.logger.error(f"任务测试失败: {config.task_name}, 错误: {e}")
    
    def add_simple_task(self, 
                       task_id: str,
                       module_path: str,
                       function_name: str,
                       trigger_type: str,
                       trigger_args: Dict[str, Any],
                       task_name: str = None,
                       args: tuple = (),
                       kwargs: Dict[str, Any] = None,
                       **task_kwargs):
        """
        快速添加任务
        
        Args:
            task_id: 任务ID
            module_path: 模块路径
            function_name: 函数名
            trigger_type: 触发器类型
            trigger_args: 触发器参数
            task_name: 任务名称
            args: 函数参数
            kwargs: 函数关键字参数
            **task_kwargs: 其他任务参数
        """
        # 创建配置
        config = TaskConfig(
            task_id=task_id,
            task_name=task_name or function_name,
            module_path=module_path,
            function_name=function_name,
            trigger_type=TriggerType(trigger_type),
            trigger_args=trigger_args,
            args=args,
            kwargs=kwargs or {},
            **task_kwargs
        )
        
        return self.add_task(config)
    
    def load_configs(self) -> bool:
        """从配置文件加载任务配置"""
        try:
            config_path = Path(self.config_file)
            if not config_path.exists():
                self.logger.warning(f"配置文件不存在: {self.config_file}")
                self._create_default_config()
                return True
            
            with open(config_path, 'r', encoding='utf-8') as f:
                configs_data = yaml.safe_load(f) or {}
            
            tasks_data = configs_data.get('tasks', [])
            
            loaded_count = 0
            for task_data in tasks_data:
                config = TaskConfig.from_dict(task_data)
                if config.enabled:
                    if self.add_task(config):
                        loaded_count += 1
                else:
                    self.logger.info(f"跳过禁用任务: {config.task_name}")
            
            self.logger.info(f"从配置文件加载了 {loaded_count} 个任务")
            return True
            
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}", exc_info=True)
            return False
    
    def _create_default_config(self):
        """创建默认配置文件"""
        default_config = {
            'tasks': [
                {
                    'task_id': 'demo_task',
                    'task_name': '演示任务',
                    'module_path': 'demo_tasks',
                    'function_name': 'demo_function',
                    'trigger_type': 'interval',
                    'trigger_args': {'seconds': 60},
                    'enabled': True,
                    'description': '这是一个演示任务'
                }
            ]
        }
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, allow_unicode=True, 
                     default_flow_style=False, sort_keys=False)
        
        self.logger.info(f"已创建默认配置文件: {self.config_file}")
    
    def start(self) -> None:
        """启动调度器"""
        if not self.scheduler.running:
            self.scheduler.start()
            self.logger.info("定时任务调度器已启动")
        else:
            self.logger.warning("调度器已经在运行")
    
    def stop(self) -> None:
        """停止调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            self.logger.info("定时任务调度器已停止")
        else:
            self.logger.warning("调度器未在运行")
    
    def list_tasks(self) -> list:
        """列出所有任务"""
        return list(self.tasks.values())
    
    def get_running_jobs(self) -> list:
        """获取运行中的任务"""
        return self.scheduler.get_jobs()
    
    def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        try:
            self.scheduler.pause_job(task_id)
            self.logger.info(f"任务已暂停: {task_id}")
            return True
        except Exception as e:
            self.logger.error(f"暂停任务失败: {task_id}, 错误: {e}")
            return False
    
    def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        try:
            self.scheduler.resume_job(task_id)
            self.logger.info(f"任务已恢复: {task_id}")
            return True
        except Exception as e:
            self.logger.error(f"恢复任务失败: {task_id}, 错误: {e}")
            return False
    
    def remove_task(self, task_id: str) -> bool:
        """移除任务"""
        try:
            self.scheduler.remove_job(task_id)
            if task_id in self.tasks:
                del self.tasks[task_id]
            self.logger.info(f"任务已移除: {task_id}")
            return True
        except Exception as e:
            self.logger.error(f"移除任务失败: {task_id}, 错误: {e}")
            return False