import numpy as np
import pandas as pd
import talib
import logging
from Tools.MyTT import *

logger = logging.getLogger(__name__)

class Signal_BOLL3:
    def __init__(self, sd_period=30):
        """
        初始化 BOLL3 信号类
        
        Args:
            sd_period (int): 30
        """
        self.sd_period = sd_period
        
    def calculate(self, df):
        """
        计算 BOLL3 指标并添加到 DataFrame 中
        
        Args:
            df (pd.DataFrame): 包含 'close', 'high', 'low' 列的 DataFrame
            
        Returns:
            pd.DataFrame: 添加了 BOLL3 指标的 DataFrame
        """
        try:
            # 创建 BOLL3 指标字典
            ATR_FACTOR = 0.5
            # 处理 NaN 值
            df['boll3_mid'] = EMA(df['close'], self.sd_period) #talib.SMA(df['close'], timeperiod=self.sd_period)
            
            # 计算标准差 (DIS)
            std = df['close'].rolling(window=self.sd_period).std()
            ATR_ADJ =AVEDEV(df['close'].values , 5) * ATR_FACTOR / df['close'];
            print(ATR_ADJ)
            df['boll3_std'] = STD(df['close'].values, self.sd_period) * (1+ ATR_ADJ)
            
            # 计算 2 倍标准差带
            df['boll3_upper2'] = round(df['boll3_mid'] + 2 * df['boll3_std'], 3)
            df['boll3_lower2'] = round(df['boll3_mid'] - 2 * df['boll3_std'], 3)
            
            # 计算 3 倍标准差带
            df['boll3_upper3'] = round(df['boll3_mid'] + 3 * df['boll3_std'], 3)
            df['boll3_lower3'] = round(df['boll3_mid'] - 3 * df['boll3_std'], 3)
            
            # 计算 BOLL3 信号
            df['boll3_signal'] = pd.Series(0, index=df.index)
            
            df['boll3_mid'] = round(df['boll3_mid'], 3)
            
            # 计算成交量比
            volume_ma5 = MA(df['volume'].values, 20)  # 20日平均成交量
            df['volume_ratio'] = df['volume'] / volume_ma5  # 成交量比
            df['volume_ratio'] = df['volume_ratio'].round(2)  # 保留两位小数
            #ATR_ADJ =AVEDEV(df['close'].values , 5) * ATR_FACTOR / df['close'];

            # 使用Pandas的向量化操作计算条件
            ratio = df['volume_ratio'] > 1.2
            
            # 修复upper_break的计算
            upper_break = (df['close'] > df['boll3_upper2']) & (df['close'] < df['boll3_upper3'])
            df["UPPER_BREAK"] = upper_break & ratio

            # 修复lower_break的计算
            lower_break = (df['close'] < df['boll3_lower2']) & (df['close'] > df['boll3_lower3'])
            df["LOWER_BREAK"] = lower_break & ratio

            ratio = df['volume_ratio'] > 1.5

            # 修复upper_reverse的计算
            upper_reverse = df['close'] >= df['boll3_upper3']
            df["UPPER_REVERSE"] = upper_reverse & ratio

            # 修复lower_reverse的计算
            lower_reverse = df['close'] <= df['boll3_lower3']
            df["LOWER_REVERSE"] = lower_reverse & ratio

            df["TREND_POWER"] = (df['close'] - df['close'].shift(3)) / df['boll3_std']
            df["STRONG_TREND"] = abs(df['TREND_POWER']) > 1.5
            #print(df["LOWER_BREAK"] == True)
            #MORNING_FADE:=TIME<1030 AND UPPER_BREAK;
            #LUNCH_REVERSAL:=TIME>1130 AND TIME<1330 AND (UPPER_REVERSE OR LOWER_REVERSE);
            #POWER_HOUR:=TIME>1500 AND STRONG_TREND;

            for _, row in df.iterrows():
                if row["LOWER_BREAK"] == True:
                    print(f"{row['trade_date']} ---- {row['close']} LOWER_BREAK")
                elif row["UPPER_BREAK"] == True:
                    print(f"{row['trade_date']} ---- {row['close']} UPPER_BREAK")
                elif row["UPPER_REVERSE"] == True:
                    print(f"{row['trade_date']} ---- {row['close']} UPPER_REVERSE")
                elif row["LOWER_REVERSE"] == True:
                    print(f"{row['trade_date']} ---- {row['close']} LOWER_REVERSE")


            # 创建boll3字典，包含所有指标
            boll3 = {
                'mid': df['boll3_mid'],
                'upper2': df['boll3_upper2'],
                'lower2': df['boll3_lower2'],
                'upper3': df['boll3_upper3'],
                'lower3': df['boll3_lower3'],
                'std': df['boll3_std'],
                'signal': df['boll3_signal'],
                'volume_ratio': df['volume_ratio']  # 添加成交量比到指标字典中
            }
            
            # 将 BOLL3 字典作为一列添加到 DataFrame 中
            df['boll3'] = boll3
            
            return df
            
        except Exception as e:
            logger.error(f"计算 BOLL3 指标时出错: {str(e)}")
            return df
            
    def generate_signals(self, df):
        """
        生成 BOLL3 交易信号
        
        Args:
            df (pd.DataFrame): 包含 BOLL3 指标的 DataFrame
            
        Returns:
            list: 信号列表
        """
        signals = []
        
        try:
            # 获取最新数据
            for index in range(len(df) - 1, len(df)):
                latest = df.iloc[index]
                #latest = df.iloc[-3]
                latest_boll3 = latest['boll3']
                
                # 检查是否突破上轨 2 倍标准差
                if latest['UPPER_BREAK'] == True:
                    signals.append({
                        'trade_date': latest['trade_date'],
                        'type': 'BOLL3',
                        'name': latest['name'],
                        'signal': 'BUY',
                        'message': f"价格突破 BOLL 上轨 2 倍标准差，观察是否还继续向上",
                        'close': latest['close'],
                        'time': latest.name,
                        'indicators': {
                            'mid': latest['boll3_mid'],
                            'upper3': latest['boll3_upper3'],
                            'lower3': latest['boll3_lower3'],
                            'volume_ratio': latest['volume_ratio']  # 添加成交量比到信号中
                        }
                    })
                    # 检查是否突破上轨 3 倍标准差
                elif latest['UPPER_REVERSE'] == True:
                    signals.append({
                        'trade_date': latest['trade_date'],
                        'type': 'BOLL3',
                        'signal': 'SELL',
                        'name': latest['name'],
                        'message': f"价格突破 BOLL 上轨 3 倍标准差，建议卖出",
                        'close': latest['close'],
                        'time': latest.name,
                        'indicators': {
                            'mid': latest['boll3_mid'],
                            'upper3': latest['boll3_upper3'],
                            'lower3': latest['boll3_lower3'],
                            'volume_ratio': latest['volume_ratio']  # 添加成交量比到信号中
                        }
                    })
                    
                # 检查是否突破下轨 3 倍标准差
                elif latest['LOWER_REVERSE'] == True:
                    signals.append({
                        'trade_date': latest['trade_date'],
                        'type': 'BOLL3',
                        'signal': 'BUY',
                        'name': latest['name'],
                        'message': f"价格突破 BOLL 下轨 3 倍标准差，建议买入",
                        'close': latest['close'],
                        'time': latest.name,
                        'indicators': {
                            'mid': latest['boll3_mid'],
                            'upper3': latest['boll3_upper3'],
                            'lower3': latest['boll3_lower3'],
                            'volume_ratio': latest['volume_ratio']  # 添加成交量比到信号中
                        }
                    })
                
        except Exception as e:
            logger.error(f"生成 BOLL3 信号时出错: {str(e)}")
            
        return signals 