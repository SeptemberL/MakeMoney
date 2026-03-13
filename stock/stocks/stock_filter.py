import logging
import pandas as pd
from datetime import datetime
from signals.signal_boll3 import Signal_BOLL3
from signals.signal_dljg2 import Signal_DLJG2

logger = logging.getLogger(__name__)

class StockFilger:
    def __init__(self):
        logger.info("StockFilger")

    def filter_stocks_by_filter(self, filterData, stockManager, progressFunc):
        self.data = filterData
        self.manager = stockManager
         # 获取信号筛选列表
        filter_signals = filterData.get('filterSignal', [])  # 获取信号筛选数组
        # 获取筛选条件
        volume_filter = filterData.get('volumeFilter', '')
        price_min = filterData.get('priceMin')
        price_max = filterData.get('priceMax')

        stockManager.update_stock_list(False, None, progressFunc)

        # 示例返回数据
        results = [
            {
                'code': '000001.SZ',
                'name': '平安银行',
                'price': 18.55,
                'change_pct': 2.15,
                'volume': 123456789,
                'indicators': ['MACD金叉', '布林带突破'],
            }
        ]

        return results
    
    def filter_stock(self, df, dayRange, filterSignals):
        #code = '603707'
        if filterSignals == None:
            return
        
        newSig = None
        avg_return= 0.0
        positive_prob = 0.0
        if df is not None and not df.empty:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            numeric_columns = ['open', 'close', 'high', 'low', 'volume', 'amount', 'p_change', 'turnover_rate']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
             # 计算技术指标
            
            for signal in filterSignals:
                signalClass = self.create_signal_class(signal)
                if signalClass != None:
                    dftemp, avg_return, positive_prob = signalClass.calculate(df)  

                    signal = self.calculate_signal(signalClass, df, dayRange)
                    if len(signal)  > 0:
                        newSig = {}
                        newSig['code'] = df["code"]
                        newSig['signals'] = signal            
        return newSig, avg_return, positive_prob



        '''if 'BOLL' in filterSignals:
                # 创建 BOLL3 信号实例
                boll3 = Signal_BOLL3(sd_period=30)
                # 计算指标并添加到 DataFrame 中
                df = boll3.calculate(df)
                
            if 'DLJG' in filterSignals:
                # 创建 DLJG 信号实例
                dljg2 = Signal_DLJG2()
                # 计算指标并添加到 DataFrame 中
                df = dljg2.calculate(df)
                '''
       
        '''signalMsg= check_signal.CheckSingle(stock_code, manager)
            if signalMsg != None and signalMsg != "":
                print(signalMsg)'''
    

            # 计算振幅
            #amplitude_info = calculate_amplitude(df)
               
            # 检查信号条件
            #check_signal_conditions(df, stock_code)
    def create_signal_class(self, className):
        if className == 'BOLL':
            return Signal_BOLL3(sd_period=30)
        elif className == 'DLJG':
            return Signal_DLJG2()
        return None
    
    def calculate_signal(self, signalClass, df, dayRange):
        signals = []
        target_date = "2025-04-29"
        daily_data = df[df["trade_date"] == target_date]
        now_date = int(datetime.now().strftime("%Y%m%d"))
        forwardIndex = 0
        for index, row in df[::-1].iterrows():
            # 处理每一行数据，现在是倒序
            date = int(row['trade_date'].strftime("%Y%m%d"))
            if forwardIndex > int(dayRange) - 1:
                break
            signal = signalClass.generate_signals(row)
            if len(signal) > 0:
                for subsignal in signal:
                    newSig = {}
                    newSig['date'] = date
                    newSig['msg'] = subsignal
                    signals.append(newSig)
            forwardIndex = forwardIndex + 1
            
        return signals
    
    def SignalToHtmlData(self, signals):

        return "";

    def SignalToWeChatData(self, signals):
        result = ""
        for signal in signals:
            code = signal['code']
            subSignals = signal['signals']
            result = result + "股票:" + code + "\n"
            for subSignal in subSignals:
                date = subSignal['date']
                msg = subSignal['msg']
                result = result + " \t日期:" + str(date) + "  触发：" + str(msg) + "\n"
            
            result = result + "\n"
        return result
    