from dataclasses import dataclass, asdict
from typing import Dict, Any, Callable, Optional, Union
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

    wxGroups = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.load_configs()
        return cls._instance
    
    def load_configs(self):
        """从数据库加载聊天群配置（list_type=weixin）。"""
        self.wxGroups = []
        try:
            from database.database import Database
            db = Database.Create()
            db.ensure_message_group_tables()
            groups = db.get_all_message_groups(list_type='weixin')
            db.close()
            for g in groups:
                self.wxGroups.append(WXGroupConfig(group_id=str(g['group_id']), chat_list=g.get('chat_list') or []))
            print(f"从数据库加载了 {len(self.wxGroups)} 个微信聊天分组")
            return True
        except Exception as e:
            print(f"加载聊天群配置失败: {e}", exc_info=True)
            return False
    
    def find_wx_group(self, groupid):
        gid = int(groupid)
        for group in self.wxGroups:
            if int(group.group_id) == gid:
                return group.chat_list
        
