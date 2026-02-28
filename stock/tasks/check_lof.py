import yaml
import sys
import os
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, Callable, Optional, Union

from stock_global import StockGlobal

# 获取当前脚本（A.py）所在目录的父目录（即项目根目录）
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 将项目根目录添加到模块搜索路径
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 现在可以从 BB 目录导入 B 模块
from crawls import crawl_lof
from Managers.wx_group_manager import WXGroupManager

@dataclass
class LofConfig:
    """任务配置类"""
    lof_check_id: str
    lof_desc: str
    lof_url: str  # 模块路径，如：task_functions.file_ops
    lof_check_warning_point: float  # 预警最低百分比
    send_message_group: int
    send_message: str
    
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LofConfig':
        """从字典创建"""
        return cls(**data)
    
#class LofCheck:

config_file = "configs/lof_check.yaml"

lofs = []
def check_lof():
    print("开始check_lof")
    configs = load_configs()
    results = []
    for config in configs:
        print("开始获取 lof 数据", config.lof_desc)
        out_data = crawl_lof.fetch_fund_data(config.lof_url)
        if out_data != None:
            if out_data['premium_rate'] >= float(config.lof_check_warning_point):
                result = {
                    'config': config,
                    'out_data': out_data
                }
                results.append(result)
    messages = ''
    wxGroupManager = WXGroupManager()
    wxList = wxGroupManager.find_wx_group(1)

    for result in results:
        message = result['config'].send_message
        message = message.format(
        fund_name=result['out_data']['fund_name'],
            fund_code=result['out_data']['fund_code'],
            current_price=result['out_data']['current_price'],
            unit_nav=result['out_data']['unit_nav'],
            premium_rate=result['out_data']['premium_rate']
        )
        message = message + "\\n"
        messages = messages + message
        

    stockGlobal = StockGlobal()
    if stockGlobal.wx != None:
        for wx in wxList:
            stockGlobal.wx.SendMsg(messages, wx) 
            

        #url = "https://q.fund.sohu.com/161226/index.shtml"
        #sliver_data = crawl_lof.fetch_fund_data(url)


def load_configs() -> bool:
    """从配置文件加载任务配置"""
    result = []
    try:
        config_path = Path(config_file)
        if not config_path.exists():
            print(f"配置文件不存在: {config_file}")
            return True
            
        with open(config_path, 'r', encoding='utf-8') as f:
            configs_data = yaml.safe_load(f) or {}
         
        lofs_data = configs_data.get('checks', [])
           
        loaded_count = 0
        for task_data in lofs_data:
            config = LofConfig.from_dict(task_data)
            result.append(config)
            loaded_count = loaded_count + 1
              
        print(f"从配置文件加载了 {loaded_count} 个 lof 检测配置")
        return result
                
    except Exception as e:
        print(f"加载配置文件失败: {e}", exc_info=True)
        return False
