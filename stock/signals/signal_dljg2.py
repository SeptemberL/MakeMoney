"""
Signal_DLJG2 - MACD结构预警系统
实现基于MACD的底部和顶部结构预警
"""

import numpy as np
import pandas as pd
import talib
from datetime import datetime
import logging
import sys
import os
import math

# 添加tools目录到系统路径
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
from Tools.MyTT import MACD, EMA, CROSS, REF, HHV, LLV, RD, BARSLAST
from Core.constants import DF_CLOSE

logger = logging.getLogger(__name__)

class Signal_DLJG2:
    def __init__(self):
        """
        初始化MACD结构预警系统
        """
        # MACD参数
        self.ema_short = 12
        self.ema_long = 26
        self.dea_period = 9
        
        # 存储历史信号
        self.last_death_cross = None  # 最近一次死叉位置
        self.last_golden_cross = None  # 最近一次金叉位置
        
        # 存储上一次的信号状态
        self.last_signals = {}
        
    def calculate(self, df):
        """
        计算MACD结构预警指标并添加到DataFrame中
        
        Args:
            df (pd.DataFrame): 包含 DF_CLOSE 列的DataFrame
            
        Returns:
            pd.DataFrame: 添加了MACD结构预警指标的DataFrame
        """
        try:
            # 使用myTT的MACD函数计算MACD指标
            dif, dea, macd = MACD(df[DF_CLOSE].values, self.ema_short, self.ema_long, self.dea_period)
            
            # 将MACD指标添加到DataFrame中
            df['DIF'] = dif
            df['DEA'] = dea
            df['MACD'] = macd
            print(f"最后一天的dif: {df['DIF'].iloc[-1]} DEA: {df['DEA'].iloc[-1]} MACD:{ df['MACD'].iloc[-1]}")


            # 计算金叉和死叉
            df['dljg2_death_cross'] = CROSS(dea, dif).astype(int)
            df['dljg2_golden_cross'] = CROSS(dif, dea).astype(int)
            #{ === 底部结构预警 === }
            avg_return,positive_prob = self.calculate_Bottom_Divergence(df)
                       
            return df,avg_return,positive_prob
            
        except Exception as e:
            logger.error(f"计算MACD结构预警指标时出错: {str(e)}")
            return df
            
    def generate_signals(self, dayData):
        """
        生成MACD结构预警信号
        
        Args:
            df (pd.DataFrame): 包含MACD结构预警指标的DataFrame
            
        Returns:
            list: 信号列表
        """
        signals = []
        date = dayData['trade_date'].strftime("%Y%m%d")
        code = dayData['code']
        if dayData['底钝化形成'] != None and dayData['底钝化形成'] == 1:
            signals.append(f"底钝化形成")
        elif dayData['底钝化'] != None and dayData['底钝化'] == 1:
            signals.append(f"底钝化开始， 可以加入观察")
            
        return signals 

    #Ref函数
    def ref_series(self, series, periods):
        if isinstance(periods, pd.Series):
            shifted_series = pd.Series(index=series.index, dtype=series.dtype)
            for i, period in periods.items():
                if pd.notna(period):
                    if isinstance(i, pd.Timestamp):
                        delta = pd.Timedelta(days=int(period))
                        shifted_index = i - delta
                    else:
                        shifted_index = i - int(period)
                    if shifted_index in series.index:
                        shifted_series.loc[i] = series.loc[shifted_index]
                    else:
                        shifted_series.loc[i] = np.nan
                else:
                    shifted_series.loc[i] = np.nan
            return shifted_series
        else:
            return series.shift(int(periods))
    #计算N2
    def calculate_n2(self, index, n1_series):
        n1_value = n1_series.iloc[index]
        if pd.isna(n1_value):
            return np.nan
        shift_period = int(n1_value) + 1
        if index - shift_period >= 0:
            return n1_series.iloc[index - shift_period]
        else:
            return np.nan
    #计算N3
    def calculate_n3(self, index, n1_series, n2_series):
        n1_value = n1_series.iloc[index]
        if pd.isna(n1_value):
            return np.nan

        shift_n1_plus_2 = int(n1_value) + 2
        n2_shifted_value = n2_series.shift(shift_n1_plus_2).iloc[index]
        if pd.isna(n2_shifted_value):
            return np.nan

        shift_period = int(n1_value) + int(n2_shifted_value) + 2
        if index - shift_period >= 0:
            return n1_series.iloc[index - shift_period]
        else:
            return np.nan

    def get_power_of_ten(self, x):
        if abs(x) < 1 and x != 0:
            return 0
        elif x > 0:
            return int(math.log10(x))
        elif x < 0:
            return int(math.log10(-x))
        else:
            return 0

    def calculate_Bottom_Divergence(self, df):
        """
        参数说明：
        df - 包含DEA/DIF/CLOSE的DataFrame
        """
        # ========== 基础计算 ==========
        #df = df.copy()
                
        # ========== 历史死叉位置计算 ==========
        # 生成BARSLAST序列
        N1 = BARSLAST(df['dljg2_death_cross'] == 1)
        df['N1'] = N1  # 最近一次死叉位置
        
        df['N2'] = [self.calculate_n2(i, df['N1']) for i in range(len(df))]
        df['N3'] = [self.calculate_n3(i, df['N1'], df['N2']) for i in range(len(df))]

        # ===== 动态窗口计算 =====
        # 预处理N1的值，确保为非负整数
        df['N1_filled'] = df['N1'].fillna(0).astype(int)
        df['CL1'] = df.apply(
            lambda row: df[DF_CLOSE].iloc[
            max(0, row.name - row['N1_filled']) : row.name + 1  # 闭区间切片
            ].min(), 
            axis=1
        )

        df["DIFL1"] = df.groupby((df["N1"] == 0).cumsum())["DIF"].cummin()
        df['CL2'] = self.ref_series(df['CL1'], df['N1'] + 1)
        df['DIFL2'] = self.ref_series(df['DIFL1'], df['N1'] + 1)
        df['CL3'] = self.ref_series(df['CL2'], df['N1'] + 1)
        df['DIFL3'] = self.ref_series(df['DIFL2'], df['N1'] + 1)

        df['PDIFL2'] = self.calculate_PDIFL2(df['DIFL2'])
        df['MDIFL2'] = self.calculate_MDIFL2(df['DIFL2'], df['PDIFL2'])
        df['PDIFL3'] = self.calculate_PDIFL2(df['DIFL3'])
        df['MDIFL3'] = self.calculate_MDIFL2(df['DIFL3'], df['PDIFL3'])
        df['MDIFB2'] = self.calculate_MDIFL2(df['DIF'], df['PDIFL2'])
        df['MDIFB3'] = self.calculate_MDIFL2(df['DIF'], df['PDIFL3'])

        df['直接底背离'] = (df['CL1'] < df['CL2']) & (df['MDIFB2'] > df['MDIFL2']) & (df['MACD'] < 0) & (df['MACD'].shift(1) < 0) & (df['MDIFB2'] <= df['MDIFB2'].shift(1))
        df['隔峰底背离'] = (df['CL1'] < df['CL3']) & (df['CL3'] < df['CL2']) & (df['MDIFB3'] > df['MDIFL3']) & (df['MACD'] < 0) & (df['MACD'].shift(1) < 0) & (df['MDIFB3'] <= df['MDIFB3'].shift(1))
        df['B'] = df['直接底背离'] | df['隔峰底背离']
        df['BG'] = ((df['MDIFB2'] > df['MDIFB2'].shift(1)) & df['直接底背离'].shift(1)) | ((df['MDIFB3'] > df['MDIFB3'].shift(1)) & df['隔峰底背离'].shift(1))
        df['底背离消失'] = (df['直接底背离'].shift(1) & (df['DIFL1'] <= df['DIFL2'])) | (df['隔峰底背离'].shift(1) & (df['DIFL1'] <= df['DIFL3']))

        df['TFILTER_B_钝化'] = df['B'] & (df['B'].shift(1) == False) & (df['MACD'] <= 0)
        df['TFILTER_消失_底'] = df['底背离消失'] & (df['底背离消失'].shift(1) == False) & (df['B'] == False)
        df['TFILTER_BG_形成'] = df['BG'] & (df['BG'].shift(1) == False) & (df['MACD'] <= 0)

        df['底钝化'] = df['TFILTER_B_钝化'].astype(int)
        df['底钝化消失'] = df['TFILTER_消失_底'].astype(int)
        df['底钝化形成'] = df['TFILTER_BG_形成'].astype(int)


        # 按日期排序以确保时间序列正确
        df_sorted = df.sort_values('trade_date').copy()
        avg_return = 0.0
        positive_prob = 0.0
        '''
        # 计算未来1天、2天、3天的涨跌幅
        df_sorted['pct_1'] = df_sorted['pct_change'].shift(-1)
        df_sorted['pct_2'] = df_sorted['pct_change'].shift(-2)
        df_sorted['pct_3'] = df_sorted['pct_change'].shift(-3)
        df_sorted['pct_4'] = df_sorted['pct_change'].shift(-4)
        df_sorted['pct_5'] = df_sorted['pct_change'].shift(-5)
        df_sorted['pct_6'] = df_sorted['pct_change'].shift(-6)
        df_sorted['pct_7'] = df_sorted['pct_change'].shift(-7)

        # 筛选信号为1且未来三天数据完整的行
        valid_mask = (
            (df_sorted['底钝化形成'] == 1) &
            df_sorted['pct_1'].notna() &
            df_sorted['pct_2'].notna() &
            df_sorted['pct_3'].notna() &
            df_sorted['pct_4'].notna() &
            df_sorted['pct_5'].notna() &
            df_sorted['pct_6'].notna() &
            df_sorted['pct_7'].notna()
        )
        
        valid_signals = df_sorted[valid_mask]
        avg_return = 0.0
        positive_prob = 0.0
        if valid_signals.empty:
            print("提示：没有符合条件的信号数据")
        else:
            # 计算平均涨幅（所有三天的总平均）
            all_returns = valid_signals[['pct_1', 'pct_2', 'pct_3', 'pct_4', 'pct_5', 'pct_6', 'pct_7']].values.flatten()
            avg_return = all_returns.mean()
            
            # 计算涨跌概率（上涨天数占比）
            positive_days = (all_returns > 0).sum()
            total_days = len(all_returns)
            positive_prob = positive_days / total_days
            
            # 输出结果
            print(f"信号触发后三天的平均涨幅: {avg_return:.4f}")
            print(f"信号触发后三天的上涨概率: {positive_prob:.2%}")
        '''
        return avg_return, positive_prob
        '''print("底钝化形成")
        for index, row in df[::-1].iterrows():
            print(row['trade_date'].strftime('%Y-%m-%d') + " : " + str(row['底钝化形成']))'''

    
        #return df
    def calculate_MDIFL2(self, DIFL2, PDIFL2):
        """
        实现公式 MDIFL2 = IF(PDIFL2 != 0, INTPART(DIFL2 / 10^PDIFL2), DIFL2)
        """
        # 处理输入类型
        is_pandas = isinstance(DIFL2, (pd.Series, pd.DataFrame)) or isinstance(PDIFL2, (pd.Series, pd.DataFrame))
        if is_pandas:
            index = DIFL2.index if isinstance(DIFL2, (pd.Series, pd.DataFrame)) else PDIFL2.index
            DIFL2 = DIFL2.values if isinstance(DIFL2, pd.Series) else DIFL2
            PDIFL2 = PDIFL2.values if isinstance(PDIFL2, pd.Series) else PDIFL2
        else:
            DIFL2 = np.array(DIFL2)
            PDIFL2 = np.array(PDIFL2)

        # 计算缩放因子并避免除以零
        scale = np.power(np.float64(10), PDIFL2)
        #scale = np.power(10, PDIFL2)
        scale[PDIFL2 == 0] = 1  # 当 PDIFL2=0 时，缩放因子为 1

        # 计算缩放后的值并取整（向下取整，与 Excel 的 INTPART 一致）
        scaled_values = DIFL2 / scale
        int_part = np.floor(scaled_values) if (scaled_values.dtype == float) else scaled_values.astype(int)

        # 应用条件逻辑
        result = np.where(PDIFL2 != 0, int_part, DIFL2)

        # 恢复数据类型
        if is_pandas:
            return pd.Series(result, index=index, name='MDIFL2')
        else:
            return result
        
    def calculate_PDIFL2(self, DIFL2):
        """
        实现公式 PDIFL2 = IF(DIFL2>0, INTPART(LOG(DIFL2))-1,
                        IF(DIFL2<0, INTPART(LOG(-DIFL2))-1, 0)
        """
        values = DIFL2.values if isinstance(DIFL2, pd.Series) else np.array(DIFL2)
        abs_values = np.abs(values)
            
        with np.errstate(divide='ignore', invalid='ignore'):
            log_values = np.where(abs_values > 0, np.log10(abs_values), 0)
            
        int_part = np.floor(log_values).astype(int)
        result = np.where(
            values > 0,
            int_part - 1,
            np.where(values < 0, int_part - 1, 0)
        )
            
        if isinstance(DIFL2, pd.Series):
            return pd.Series(result, index=DIFL2.index, name='PDIFL2')
        else:
            return result
"""
使用示例：
假设已有包含DEA/DIF/close的DataFrame
df = calculate_indicators(your_df)
"""