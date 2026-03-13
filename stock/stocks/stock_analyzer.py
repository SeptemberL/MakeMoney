import pandas as pd
import numpy as np
import talib
from datetime import datetime
import logging
from typing import Dict, List, Optional, Union
from signals.signal_boll3 import Signal_BOLL3
from signals.signal_dljg2 import Signal_DLJG2
from flask_socketio import SocketIO, emit
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StockAnalyzer:
    def __init__(self):
        self.required_columns = ['open', 'high', 'low', 'close', 'volume']
        # 添加MACD默认参数
        self.macd_params = {
            'fastperiod': 12,
            'slowperiod': 26,
            'signalperiod': 9
        }
        

    def update_macd_params(self, ema_short: int, ema_long: int, dea_period: int):
        """更新MACD参数"""
        self.macd_params = {
            'fastperiod': ema_short,
            'slowperiod': ema_long,
            'signalperiod': dea_period
        }

    @staticmethod
    def validate_dataframe(df: pd.DataFrame) -> bool:
        """验证数据框是否包含必要的列"""
        required = ['open', 'high', 'low', 'close', 'volume']
        return all(col in df.columns for col in required)

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        try:
            if not StockAnalyzer.validate_dataframe(df):
                raise ValueError("数据框缺少必要的列")

            # 确保数据类型正确
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            # 确保数据按日期排序
            df = df.sort_values('trade_date')
            
            # 计算各种周期的移动平均线
            ma_periods = [5, 10, 20, 30, 60, 99, 250]
            for period in ma_periods:
                column_name = f'ma{period}'
                df[column_name] = talib.MA(df['close'].values, timeperiod=period)
            
            print("计算的均线列:", [col for col in df.columns if col.startswith('ma')])  # 调试信息
           

            # 创建 BOLL3 信号实例
            boll3 = Signal_BOLL3(sd_period=30)
    
            # 计算指标并添加到 DataFrame 中
            boll3.calculate(df)

             # 创建 BOLL3 信号实例
            dljg2 = Signal_DLJG2()
    
            # 计算指标并添加到 DataFrame 中
            dljg2.calculate(df)

            #dljg2.generate_signals(df)

            # 访问 BOLL3 指标数据
            #boll3_data = df['boll3']  
            #if boll3_data is not None:
            #mid_line = df['boll3_mid']  # 中轨线
            #upper_band = df['boll3_upper3']  # 3倍标准差上轨
            #lower_band = df['boll3_lower3']  # 3倍标准差下轨

            # === BOLL指标 ===
            '''
            WIDTH = 2
            WIDTH3 = 3
            SD = 20

            df['boll_mid'] = talib.MA(df['close'], timeperiod=SD)
            df['boll_std'] = talib.STDDEV(df['close'], timeperiod=SD)
            
            df['boll_upper2'] = df['boll_mid'] + WIDTH * df['boll_std']
            df['boll_lower2'] = df['boll_mid'] - WIDTH * df['boll_std']
            df['boll_upper3'] = df['boll_mid'] + WIDTH3 * df['boll_std']
            df['boll_lower3'] = df['boll_mid'] - WIDTH3 * df['boll_std']

            # 添加BOLL带区域标记
            df['boll_upper_zone'] = df.apply(
                lambda x: x['boll_upper3'] if x['high'] < x['boll_upper2'] else None, 
                axis=1
            )
            df['boll_lower_zone'] = df.apply(
                lambda x: x['boll_lower3'] if x['low'] > x['boll_lower2'] else None, 
                axis=1
            )
            '''
            # === MACD指标 ===
            df['macd'], df['macd_signal'], df['macd_hist'] = talib.MACD(
                df['close'],
                fastperiod=12,
                slowperiod=26,
                signalperiod=9
            )

            # === KDJ指标 ===
            df['k'], df['d'] = talib.STOCH(
                df['high'],
                df['low'],
                df['close'],
                fastk_period=9,
                slowk_period=3,
                slowk_matype=0,
                slowd_period=3,
                slowd_matype=0
            )
            df['j'] = 3 * df['k'] - 2 * df['d']

            # === RSI指标 ===
            df['rsi_6'] = talib.RSI(df['close'], timeperiod=6)
            df['rsi_12'] = talib.RSI(df['close'], timeperiod=12)
            df['rsi_24'] = talib.RSI(df['close'], timeperiod=24)

            # === 成交量指标 ===
            df['volume_ma5'] = talib.MA(df['volume'], timeperiod=5)
            df['volume_ma10'] = talib.MA(df['volume'], timeperiod=10)
            df['volume_ma20'] = talib.MA(df['volume'], timeperiod=20)

            # === OBV指标 ===
            df['obv'] = talib.OBV(df['close'], df['volume'])

            # === ATR指标 ===
            df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14)

            # === CCI指标 ===
            df['cci'] = talib.CCI(df['high'], df['low'], df['close'], timeperiod=14)

            # === DMI指标 ===
            df['pdi'] = talib.PLUS_DI(df['high'], df['low'], df['close'], timeperiod=14)
            df['mdi'] = talib.MINUS_DI(df['high'], df['low'], df['close'], timeperiod=14)
            df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)

            # === 趋势强度 ===
            df['trend_strength'] = np.where(
                (df['ma5'] > df['ma20']) & (df['ma20'] > df['ma60']), 1,
                np.where((df['ma5'] < df['ma20']) & (df['ma20'] < df['ma60']), -1, 0)
            )

            return df

        except Exception as e:
            logger.error(f"计算技术指标时出错: {str(e)}")
            raise

    @staticmethod
    def calculate_probability(df: pd.DataFrame) -> Dict[str, float]:
        """计算各种情况下的上涨概率"""
        try:
            probabilities = {}

            # 计算次日收益率
            df['next_day_return'] = df['close'].shift(-1) / df['close'] - 1

            # === BOLL指标概率 ===
            df['near_upper3'] = df['close'] >= df['boll_upper3'] * 0.95
            df['near_lower3'] = df['close'] <= df['boll_lower3'] * 1.05
            
            # 处理BOLL概率
            upper_cases = df[df['near_upper3']]['next_day_return'].dropna()
            lower_cases = df[df['near_lower3']]['next_day_return'].dropna()
            
            probabilities['boll_upper_prob'] = float(upper_cases.gt(0).mean() if not upper_cases.empty else 0.0)
            probabilities['boll_lower_prob'] = float(lower_cases.gt(0).mean() if not lower_cases.empty else 0.0)

            # === KDJ指标概率 ===
            df['kdj_oversold'] = (df['k'] < 20) & (df['d'] < 20)
            df['kdj_overbought'] = (df['k'] > 80) & (df['d'] > 80)
            
            kdj_oversold_cases = df[df['kdj_oversold']]['next_day_return'].dropna()
            kdj_overbought_cases = df[df['kdj_overbought']]['next_day_return'].dropna()
            
            probabilities['kdj_oversold_prob'] = float(kdj_oversold_cases.gt(0).mean() if not kdj_oversold_cases.empty else 0.0)
            probabilities['kdj_overbought_prob'] = float(kdj_overbought_cases.gt(0).mean() if not kdj_overbought_cases.empty else 0.0)

            # === MACD指标概率 ===
            df['macd_golden_cross'] = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
            df['macd_death_cross'] = (df['macd'] < df['macd_signal']) & (df['macd'].shift(1) >= df['macd_signal'].shift(1))
            
            macd_golden_cases = df[df['macd_golden_cross']]['next_day_return'].dropna()
            macd_death_cases = df[df['macd_death_cross']]['next_day_return'].dropna()
            
            probabilities['macd_golden_prob'] = float(macd_golden_cases.gt(0).mean() if not macd_golden_cases.empty else 0.0)
            probabilities['macd_death_prob'] = float(macd_death_cases.gt(0).mean() if not macd_death_cases.empty else 0.0)

            # === RSI指标概率 ===
            df['rsi_oversold'] = df['rsi_6'] < 30
            df['rsi_overbought'] = df['rsi_6'] > 70
            
            rsi_oversold_cases = df[df['rsi_oversold']]['next_day_return'].dropna()
            rsi_overbought_cases = df[df['rsi_overbought']]['next_day_return'].dropna()
            
            probabilities['rsi_oversold_prob'] = float(rsi_oversold_cases.gt(0).mean() if not rsi_oversold_cases.empty else 0.0)
            probabilities['rsi_overbought_prob'] = float(rsi_overbought_cases.gt(0).mean() if not rsi_overbought_cases.empty else 0.0)

            # 添加样本数量信息
            probabilities['sample_counts'] = {
                'boll_upper_samples': len(upper_cases),
                'boll_lower_samples': len(lower_cases),
                'kdj_oversold_samples': len(kdj_oversold_cases),
                'kdj_overbought_samples': len(kdj_overbought_cases),
                'macd_golden_samples': len(macd_golden_cases),
                'macd_death_samples': len(macd_death_cases),
                'rsi_oversold_samples': len(rsi_oversold_cases),
                'rsi_overbought_samples': len(rsi_overbought_cases)
            }

            # 确保所有概率值都是有效的浮点数
            for key, value in probabilities.items():
                if key != 'sample_counts':
                    if pd.isna(value) or value is None:
                        probabilities[key] = 0.0

            return probabilities

        except Exception as e:
            logger.error(f"计算概率时出错: {str(e)}", exc_info=True)
            # 返回默认值
            return {
                'boll_upper_prob': 0.0,
                'boll_lower_prob': 0.0,
                'kdj_oversold_prob': 0.0,
                'kdj_overbought_prob': 0.0,
                'macd_golden_prob': 0.0,
                'macd_death_prob': 0.0,
                'rsi_oversold_prob': 0.0,
                'rsi_overbought_prob': 0.0,
                'sample_counts': {
                    'boll_upper_samples': 0,
                    'boll_lower_samples': 0,
                    'kdj_oversold_samples': 0,
                    'kdj_overbought_samples': 0,
                    'macd_golden_samples': 0,
                    'macd_death_samples': 0,
                    'rsi_oversold_samples': 0,
                    'rsi_overbought_samples': 0
                }
            }

    @staticmethod
    def generate_signals(df: pd.DataFrame) -> List[Dict[str, str]]:
        """生成交易信号"""
        try:
            signals = []
            latest = df.iloc[-1]
            prev = df.iloc[-2]

            # === BOLL信号 ===
            if latest['UPPER_BREAK'] == True:
                signals.append({
                    'type': 'BOLL',
                    'signal': 'BUY',
                    'strength': 'Strong',
                    'message': '价格向上突破了！！'
                })
            elif latest['LOWER_REVERSE'] == True:
                signals.append({
                    'type': 'BOLL',
                    'signal': 'BUY',
                    'strength': 'Strong',
                    'message': '价格过低成交量放大，可能反转'
                })
            
            ''''
            # === KDJ信号 ===
            if latest['k'] < 20 and latest['d'] < 20:
                signals.append({
                    'type': 'KDJ',
                    'signal': 'BUY',
                    'strength': 'Medium',
                    'message': 'KDJ指标进入超卖区域'
                })
            elif latest['k'] > 80 and latest['d'] > 80:
                signals.append({
                    'type': 'KDJ',
                    'signal': 'SELL',
                    'strength': 'Medium',
                    'message': 'KDJ指标进入超买区域'
                })

            # === MACD信号 ===
            if latest['macd'] > latest['macd_signal'] and prev['macd'] <= prev['macd_signal']:
                signals.append({
                    'type': 'MACD',
                    'signal': 'BUY',
                    'strength': 'Medium',
                    'message': 'MACD金叉形成'
                })
            elif latest['macd'] < latest['macd_signal'] and prev['macd'] >= prev['macd_signal']:
                signals.append({
                    'type': 'MACD',
                    'signal': 'SELL',
                    'strength': 'Medium',
                    'message': 'MACD死叉形成'
                })

            # === RSI信号 ===
            if latest['rsi_12'] < 30:
                signals.append({
                    'type': 'RSI',
                    'signal': 'BUY',
                    'strength': 'Medium',
                    'message': 'RSI进入超卖区域'
                })
            elif latest['rsi_12'] > 70:
                signals.append({
                    'type': 'RSI',
                    'signal': 'SELL',
                    'strength': 'Medium',
                    'message': 'RSI进入超买区域'
                })
            '''
            return signals

        except Exception as e:
            logger.error(f"生成信号时出错: {str(e)}")
            return []

    @staticmethod
    def calculate_support_resistance(df: pd.DataFrame, window: int = 20) -> Dict[str, float]:
        """计算支撑位和压力位"""
        try:
            recent_df = df.tail(window)
            
            support_levels = []
            resistance_levels = []
            
            # 使用低点识别支撑位
            for i in range(1, len(recent_df) - 1):
                if recent_df.iloc[i]['low'] < recent_df.iloc[i-1]['low'] and \
                   recent_df.iloc[i]['low'] < recent_df.iloc[i+1]['low']:
                    support_levels.append(recent_df.iloc[i]['low'])
            
            # 使用高点识别压力位
            for i in range(1, len(recent_df) - 1):
                if recent_df.iloc[i]['high'] > recent_df.iloc[i-1]['high'] and \
                   recent_df.iloc[i]['high'] > recent_df.iloc[i+1]['high']:
                    resistance_levels.append(recent_df.iloc[i]['high'])
            
            # 计算主要支撑位和压力位
            support = np.mean(support_levels) if support_levels else df.iloc[-1]['low']
            resistance = np.mean(resistance_levels) if resistance_levels else df.iloc[-1]['high']
            
            return {
                'support': float(support),
                'resistance': float(resistance)
            }
            
        except Exception as e:
            logger.error(f"计算支撑位和压力位时出错: {str(e)}")
            return {'support': 0.0, 'resistance': 0.0}

    @staticmethod
    def analyze_volume_price_relationship(df: pd.DataFrame) -> Dict[str, str]:
        """分析成交量和价格的关系"""
        try:
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            price_change = latest['close'] - prev['close']
            volume_change = latest['volume'] - prev['volume']
            
            analysis = {
                'price_trend': 'UP' if price_change > 0 else 'DOWN',
                'volume_trend': 'UP' if volume_change > 0 else 'DOWN',
                'strength': 'Weak'
            }
            
            # 判断趋势强度
            if price_change > 0 and volume_change > 0:
                analysis['strength'] = 'Strong'
                analysis['message'] = '价升量增，看多信号'
            elif price_change < 0 and volume_change > 0:
                analysis['strength'] = 'Medium'
                analysis['message'] = '价跌量增，需要观察'
            elif price_change > 0 and volume_change < 0:
                analysis['strength'] = 'Weak'
                analysis['message'] = '价升量减，上涨动能不足'
            else:
                analysis['strength'] = 'Medium'
                analysis['message'] = '价跌量减，跌势可能放缓'
                
            return analysis
            
        except Exception as e:
            logger.error(f"分析成交量价格关系时出错: {str(e)}")
            return {
                'price_trend': 'UNKNOWN',
                'volume_trend': 'UNKNOWN',
                'strength': 'Unknown',
                'message': '分析失败'
            } 
        
