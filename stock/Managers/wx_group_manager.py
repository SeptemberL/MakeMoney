from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, Callable, Optional, Union
import yaml
import sys
import os

# 获取当前脚本（A.py）所在目录的父目录（即项目根目录）
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 将项目根目录添加到模块搜索路径
if project_root not in sys.path:
    sys.path.insert(0, project_root)


@dataclass
class WXGroupConfig:
    """任务配置类"""
    group_id: str
    chat_list: list
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WXGroupConfig':
        """从字典创建"""
        return cls(**data)

class WXGroupManager:
    _instance = None

    config_file = 'configs/send_message_group.yaml'

    wxGroups = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.load_configs()
        return cls._instance
    
    def load_configs(self):
        """从配置文件加载任务配置"""
        self.wxGroups = []
        try:
            config_path = Path(self.config_file)
            if not config_path.exists():
                print(f"配置文件不存在: {self.config_file}")
                return True
            
            with open(config_path, 'r', encoding='utf-8') as f:
                configs_data = yaml.safe_load(f) or {}
            
            datas = configs_data.get('groups', [])
            
            loaded_count = 0
            for data in datas:
                config = WXGroupConfig.from_dict(data)
                self.wxGroups.append(config)
                loaded_count = loaded_count + 1
                
            print(f"从配置文件加载了 {loaded_count} 个聊天分组")
                
        except Exception as e:
            print(f"加载配置文件失败: {e}", exc_info=True)
            return False
    
    def find_wx_group(self, groupid):
        for group in self.wxGroups:
            if group.group_id == groupid:
                return group.chat_list
        
