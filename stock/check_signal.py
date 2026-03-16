"""
信号检查工具
用于检查单只股票的信号触发情况
"""

from signals.signal_boll3 import Signal_BOLL3
from database.database import Database
import pandas as pd
from datetime import datetime
from stocks.stock_analyzer import StockAnalyzer



def CheckSingle(stock_code, list_manager, signal_class = Signal_BOLL3, days=200):
    """
    检查单只股票的信号触发情况
    :param stock_code: 股票代码(如'600000')
    :param signal_class: 信号类(默认为Signal_3DA)
    :param days: 获取的历史数据天数(默认200天)
    """
    # 初始化数据库连接
   
    
    # 获取股票数据
    df = list_manager.get_stock_data(stock_code, days)
    
    if df is None or df.empty:
        print(f"无法获取股票 {stock_code} 的数据")
        return

    df['trade_date'] = pd.to_datetime(df['trade_date'])
    numeric_columns = ['open', 'close', 'high', 'low', 'volume', 'amount', 'p_change', 'turnover_rate']
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 确保数据按日期升序排列
    df = df.sort_values('trade_date')
    analyzer = StockAnalyzer()
    df = analyzer.calculate_indicators(df)
    
    # 初始化信号系统
    signal = signal_class()
    
    signals = signal.generate_signals(df)

    # 处理每条数据
    '''
    for _, row in df.iterrows():
        # 检测特殊时段信号
        trade_date = row['trade_date']
        temptrade_date = trade_date.strftime('%Y-%m-%d')
    
        df = analyzer.calculate_indicators(df)
        
        
        if isinstance(trade_date, str):
            trade_date = datetime.strptime(trade_date, '%Y-%m-%d')
        # 记录触发的信号
        triggered = ""
          
        if triggered != "":
            signals_triggered.append({
                'date': row['trade_date'],
                'close': row['close'],
                'signal': triggered
            })
    '''
    outMsg = ""
    # 打印结果
    if signals:
            print(f"\n股票 {stock_code} 信号触发记录:")
            print("-" * 50)
            for record in signals:
                date = int(record['trade_date'].strftime("%Y%m%d"))
                now_date = int(datetime.now().strftime("%Y%m%d"))
                #msg = f"{now_date} 股票"
                #now_date = "2025-04-07"
                #outMsg = f"{now_date} 股票 {stock_code} 今日信号触发: | 收盘价: {record['close']} | 信号: {record['signal']}"
                #if ((now_date - date) <= 3):
                outMsg = f"{date} 股票 {stock_code} ({record['name']}) 今日信号触发: | 收盘价: {record['close']} | 信号: {record['message']}"
                print(f"日期: {record['trade_date']} | 收盘价: {record['close']} | 信号: {record['signal']}")
            print("-" * 50)
            print(f"共触发 {len(signals)} 次信号")
    else:
            print(f"股票 {stock_code} 在最近 {days} 天内未触发任何信号")

            
    return outMsg

