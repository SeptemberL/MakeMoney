import logging
import pandas as pd
from datetime import datetime, timedelta
from signals.signal_boll3 import Signal_BOLL3
from signals.signal_dljg2 import Signal_DLJG2

logger = logging.getLogger(__name__)


def get_current_trading_date():
    """返回当前交易日日期字符串 YYYY-MM-DD；若当天为周末则返回上一周五。"""
    today = datetime.now().date()
    # 周六(6)回退1天，周日(7)回退2天
    if today.weekday() == 6:
        today = today - timedelta(days=1)
    elif today.weekday() == 5:
        today = today - timedelta(days=1)
    return today.strftime("%Y-%m-%d")


def parse_target_date(value):
    """将请求参数解析为 YYYY-MM-DD 字符串，无效则返回 None。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        value = value.strip()[:10]
    try:
        dt = pd.to_datetime(value)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


class StockFilger:
    def __init__(self):
        logger.info("StockFilger")

    def filter_stocks_by_filter(self, filterData, stockManager, progressFunc, target_date=None):
        """
        按筛选条件执行全市场筛选。支持通过 filterData['targetDate'] 或参数 target_date 传入基准日期。
        target_date: 可选，YYYY-MM-DD；不传则使用当前交易日。
        """
        self.data = filterData
        self.manager = stockManager
        filter_signals = filterData.get('filterSignal', [])
        volume_filter = filterData.get('volumeFilter', '')
        price_min = filterData.get('priceMin')
        price_max = filterData.get('priceMax')
        if target_date is None:
            target_date = parse_target_date(filterData.get('targetDate')) or get_current_trading_date()
        logger.info("filter_stocks_by_filter: target_date=%s, filterSignal=%s", target_date, filter_signals)
        try:
            stockManager.update_stock_list(False, None, progressFunc)
        except Exception as e:
            logger.exception("更新股票列表失败: %s", e)
            raise
        # 占位返回；后续可改为实际调用 filter_stock 并汇总结果
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
    
    def filter_stock(self, df, dayRange, filterSignals, target_date=None):
        """
        单只股票按信号筛选。返回 (signal_dict_or_None, avg_return, positive_prob)。
        target_date: 可选，YYYY-MM-DD；不传则使用当前交易日。
        """
        if filterSignals is None or (isinstance(filterSignals, (list, tuple)) and len(filterSignals) == 0):
            return None, 0.0, 0.0
        day_range = 5
        try:
            if dayRange is not None and str(dayRange).strip() != "":
                day_range = int(dayRange)
        except (TypeError, ValueError):
            day_range = 5
        if target_date is None:
            target_date = get_current_trading_date()
        else:
            target_date = parse_target_date(target_date) or get_current_trading_date()

        newSig = None
        avg_return = 0.0
        positive_prob = 0.0
        if df is None or df.empty:
            return None, avg_return, positive_prob
        try:
            df = df.copy()
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            numeric_columns = ['open', 'close', 'high', 'low', 'volume', 'amount', 'p_change', 'turnover_rate']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            for signal in filterSignals:
                signalClass = self.create_signal_class(signal)
                if signalClass is not None:
                    try:
                        dftemp, avg_return, positive_prob = signalClass.calculate(df)
                    except Exception as e:
                        logger.warning("信号 %s 计算指标失败: %s", signal, e)
                        continue
                    sig_list = self.calculate_signal(signalClass, df, day_range, target_date=target_date)
                    if len(sig_list) > 0:
                        newSig = {}
                        code_val = df["code"].iloc[0] if "code" in df.columns and len(df) else ""
                        newSig['code'] = code_val
                        newSig['signals'] = sig_list
        except Exception as e:
            logger.exception("filter_stock 异常: %s", e)
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
    
    def calculate_signal(self, signalClass, df, dayRange, target_date=None):
        """
        在 df 中按 dayRange 向前查找信号，仅考虑 trade_date <= target_date 的数据。
        target_date: 可选，YYYY-MM-DD；不传则使用当前交易日。
        """
        signals = []
        if target_date is None:
            target_date = get_current_trading_date()
        else:
            target_date = parse_target_date(target_date) or get_current_trading_date()
        try:
            target_dt = pd.to_datetime(target_date)
        except Exception as e:
            logger.warning("calculate_signal target_date 解析失败 %s, 使用当前交易日", e)
            target_dt = pd.to_datetime(get_current_trading_date())
        df = df.loc[df['trade_date'] <= target_dt]
        if df.empty:
            return signals
        day_range = max(1, int(dayRange)) if dayRange is not None else 5
        forwardIndex = 0
        for index, row in df[::-1].iterrows():
            date = int(row['trade_date'].strftime("%Y%m%d"))
            if forwardIndex >= day_range:
                break
            try:
                signal = signalClass.generate_signals(row)
            except Exception as e:
                logger.debug("generate_signals 单行异常: %s", e)
                forwardIndex += 1
                continue
            if len(signal) > 0:
                for subsignal in signal:
                    newSig = {'date': date, 'msg': subsignal}
                    signals.append(newSig)
            forwardIndex += 1
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
    