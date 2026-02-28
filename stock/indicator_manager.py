import json
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class IndicatorManager:
    def __init__(self):
        self.indicators_file = 'data/indicators.json'
        self._ensure_data_directory()
        self._load_indicators()

    def _ensure_data_directory(self):
        """确保数据目录存在"""
        os.makedirs('data', exist_ok=True)
        if not os.path.exists(self.indicators_file):
            self._save_indicators([])

    def _load_indicators(self):
        """从文件加载指标数据"""
        try:
            with open(self.indicators_file, 'r', encoding='utf-8') as f:
                self.indicators = json.load(f)
        except Exception as e:
            logging.error(f"加载指标数据失败: {str(e)}")
            self.indicators = []

    def _save_indicators(self, indicators: List[Dict]):
        """保存指标数据到文件"""
        try:
            with open(self.indicators_file, 'w', encoding='utf-8') as f:
                json.dump(indicators, f, ensure_ascii=False, indent=2)
            self.indicators = indicators
        except Exception as e:
            logging.error(f"保存指标数据失败: {str(e)}")
            raise

    def get_all_indicators(self) -> List[Dict]:
        """获取所有指标"""
        return self.indicators

    def get_indicator(self, id: int) -> Optional[Dict]:
        """获取指定ID的指标"""
        return next((i for i in self.indicators if i['id'] == id), None)

    def add_indicator(self, name: str, view_number: int, class_name: str) -> Dict:
        """添加新指标"""
        # 生成新的ID
        new_id = max([i['id'] for i in self.indicators], default=0) + 1
        
        indicator = {
            'id': new_id,
            'name': name,
            'view_number': view_number,
            'class_name': class_name,
            'is_enabled': True
        }
        
        self.indicators.append(indicator)
        self._save_indicators(self.indicators)
        return indicator

    def update_indicator(self, id: int, name: str, view_number: int, class_name: str) -> Optional[Dict]:
        """更新指标"""
        indicator = self.get_indicator(id)
        if not indicator:
            return None
            
        indicator['name'] = name
        indicator['view_number'] = view_number
        indicator['class_name'] = class_name
        
        self._save_indicators(self.indicators)
        return indicator

    def delete_indicator(self, id: int) -> bool:
        """删除指标"""
        indicator = self.get_indicator(id)
        if not indicator:
            return False
            
        self.indicators = [i for i in self.indicators if i['id'] != id]
        self._save_indicators(self.indicators)
        return True

    def toggle_indicator(self, id: int, is_enabled: bool) -> Optional[Dict]:
        """切换指标状态"""
        indicator = self.get_indicator(id)
        if not indicator:
            return None
            
        indicator['is_enabled'] = is_enabled
        self._save_indicators(self.indicators)
        return indicator 