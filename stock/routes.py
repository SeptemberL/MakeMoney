from flask import (Blueprint, 
                   render_template, 
                   jsonify, 
                   request, 
                   session, 
                   Response,
                   stream_with_context)
from stock_fetcher import StockFetcher
from stock_analyzer import StockAnalyzer
from database.database import Database
from indicator_manager import IndicatorManager
import logging
import json
import pandas as pd
import numpy as np
from datetime import datetime
import os
import subprocess
import schedule
import time
import threading
import platform
if platform.system() == 'Windows':
    import wxauto
    from wxauto import *
from config import Config
import check_signal
from stock_list_manager import StockListManager
from signals.signal_boll3 import Signal_BOLL3
from stock_global import stockGlobal
from stock_filter import StockFilger
from Managers.ScanManager import ScanManager
from stock_gatter.stockgetter_btc import StockGetter_BTC
import csv



# 创建蓝图
bp = Blueprint('main', __name__)



# 初始化组件
fetcher = StockFetcher()
analyzer = StockAnalyzer()
indicator_manager = IndicatorManager()
manager = StockListManager()

# 设置日志
logger = logging.getLogger(__name__)

# 全局变量
sendAllMessage = ""
SVN_PATH = r'svn.exe'  # Windows示例
config = Config()



@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/api/stocks', methods=['GET'])
def get_stocks():
    """获取所有股票列表"""
    try:
        print("get_stocks")
        stocks = fetcher.get_stock_list()
        return jsonify(stocks)
    except Exception as e:
        logger.error(f"获取股票列表失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@bp.route('/api/stocks', methods=['POST'])
def add_stock():
    """添加新股票"""
    try:
        data = request.get_json()
        code = data.get('code')
        name = data.get('name')
        
        if not code:
            return jsonify({'error': '股票代码不能为空'}), 400
            
        if fetcher.add_stock(code, name):
            return jsonify({'success': True})
        else:
            return jsonify({'error': '添加股票失败'}), 500
            
    except Exception as e:
        logger.error(f"添加股票失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@bp.route('/api/stocks/<code>', methods=['DELETE'])
def delete_stock(code):
    """删除股票"""
    try:
        if fetcher.delete_stock(code):
            return jsonify({'success': True})
        else:
            return jsonify({'error': '删除股票失败'}), 500
            
    except Exception as e:
        logger.error(f"删除股票失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@bp.route('/api/stock_data/<stock_code>')
def get_stock_data(stock_code):
    try:
        #stockGetterBtc = StockGetter_BTC()
        #stockGetterBtc.get_data()
        #return jsonify({'error': '没有找到数据'}), 404
        scanManager = ScanManager()

        stock_btc = StockGetter_BTC()
        ethResult = stock_btc.get_data()
        filterSignals = ["DLJG"]
        filter = StockFilger()
        signal,avg_return ,positive_prob  = filter.filter_stock(ethResult, 10, filterSignals)
        return
        if manager.update_stock_history(stock_code):
            df = manager.get_stock_data(stock_code, 365)
            #signalClass = Signal_DLJG2()
            #signalClass.calculate(df) 
            if df is not None and not df.empty:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
                numeric_columns = ['open', 'close', 'high', 'low', 'volume', 'amount', 'p_change', 'turnover_rate']
                for col in numeric_columns:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                # 计算技术指标
                df = analyzer.calculate_indicators(df)
                
        
                signalMsg= check_signal.CheckSingle(stock_code, manager)
                if signalMsg != None and signalMsg != "":
                    print(signalMsg)
        

                # 计算振幅
                #amplitude_info = calculate_amplitude(df)
                
                # 检查信号条件
                check_signal_conditions(df, stock_code)
                # 将DataFrame转换为字典列表
                data = df.replace({np.nan: None}).to_dict('records')
                response_data = {
                    'data': data,
                    'probabilities': "", #analyzer.calculate_probability(df),
                    'signals': "", #analyzer.generate_signals(df),
                    'amplitude': "" #amplitude_info
                }
                print(jsonify(response_data))
                return jsonify(response_data)
        return jsonify({'error': '没有找到数据'}), 404
        
    except Exception as e:
        logger.error(f"获取股票数据失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/update_all_stocks', methods=['POST'])
def update_all_stocks_api():
    try:
        updated_count, failed_stocks, signalMessages = update_all_stocks(True)
        stockGlobal.wx.SendSignalMessages(signalMessages)
        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'failed_stocks': failed_stocks,
            'message': f'成功更新 {updated_count} 只股票'
        })
    except Exception as e:
        logger.error(f"更新所有股票时出错: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/list_manager')
def list_manager():
    return render_template('list_manager.html')

@bp.route('/api/items', methods=['GET'])
def get_items():
    try:
        db = Database.Create()
        cursor = db.cursor()
        query = "CREATE TABLE IF NOT EXISTS items (item TEXT PRIMARY KEY, status INTEGER DEFAULT 1)"
        cursor.execute(query)
        
        cursor.execute('SELECT item, status FROM items ORDER BY item')
        items = [{'item': row[0], 'status': bool(row[1])} for row in cursor.fetchall()]
        
        db.close()
        return jsonify(items)
        
    except Exception as e:
        logger.error(f"获取项目列表失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@bp.route('/api/items', methods=['POST'])
def add_item():
    try:
        db = Database.Create()
        data = request.get_json()
        item = data.get('item')
        status = data.get('status', True)
        
        if not item:
            return jsonify({'error': '内容不能为空'}), 400
            
        cursor = db.cursor()
        
        cursor.execute('INSERT OR REPLACE INTO items (item, status) VALUES (?, ?)', 
                      (item, 1 if status else 0))
        
        db.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"添加项目失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@bp.route('/api/items/<item>/toggle', methods=['POST'])
def toggle_item_status(item):
    try:
        db = Database.Create()
        cursor = db.cursor()
        
        cursor.execute('''
            UPDATE items 
            SET status = CASE WHEN status = 1 THEN 0 ELSE 1 END 
            WHERE item = ?
        ''', (item,))
                
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"切换项目状态失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@bp.route('/api/update_stock_list', methods=['POST'])
def update_stock_list_api():
    sendAllMessage = ""
    success, sendAllMessage = manager.update_stock_list(False, None)
    stockGlobal.wx.SendSignalMessages(sendAllMessage)
    if success:
        SendAllMessages()
        return jsonify({
            'success': True, 
            'message': '股票列表更新成功'
        })
    else:
        SendAllMessages()
        return jsonify({
            'success': False,
            'message': '股票列表更新失败'
        }), 500

@bp.route('/api/macd_settings', methods=['POST'])
def update_macd_settings():
    """更新MACD参数设置"""
    try:
        data = request.get_json()
        ema_short = data.get('ema_short')
        ema_long = data.get('ema_long')
        dea_period = data.get('dea_period')
        
        if not all(isinstance(x, int) and x > 0 for x in [ema_short, ema_long, dea_period]):
            return jsonify({'error': '参数必须是正整数'}), 400
            
        analyzer.update_macd_params(ema_short, ema_long, dea_period)
        
        return jsonify({
            'success': True,
            'message': 'MACD参数更新成功',
            'params': {
                'ema_short': ema_short,
                'ema_long': ema_long,
                'dea_period': dea_period
            }
        })
        
    except Exception as e:
        logger.error(f"更新MACD参数失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@bp.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    
    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'})
    
    if db.create_user(username, password, email):
        return jsonify({'success': True, 'message': '注册成功'})
    else:
        return jsonify({'success': False, 'message': '注册失败，用户名可能已存在'})

@bp.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'})
    db = Database.Create()
    result = db.verify_user(username, password)
    if result['success']:
        session['user_id'] = result['user_id']
        session['username'] = result['username']
        db.close()
        return jsonify({
            'success': True,
            'message': '登录成功',
            'user': {
                'id': result['user_id'],
                'username': result['username'],
                'settings': result['settings']
            }
        })
    else:
        db.close()
        return jsonify({'success': False, 'message': result['message']})

@bp.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True, 'message': '已退出登录'})

@bp.route('/api/user/settings', methods=['GET'])
def get_user_settings():
    """获取用户设置"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '请先登录'})
        db = Database.Create()
        settings = db.get_user_settings(session['user_id'])
        db.close()
        return jsonify({'success': True, 'settings': settings}) 
    except Exception as e:
        logger.error(f"获取用户设置失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})
            

@bp.route('/api/user/settings', methods=['POST'])
def update_user_settings():
    """更新用户设置"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '请先登录'})
    
    try:
        data = request.get_json()
        db = Database.Create()
        if db.update_user_settings(session['user_id'], data):
            return jsonify({'success': True, 'message': '设置已更新'})
        else:
            return jsonify({'success': False, 'message': '更新设置失败'})
    except Exception as e:
        logger.error(f"更新用户设置失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})
    finally:
        db.close()

@bp.route('/indicator_manager')
def indicator_manager_page():
    return render_template('indicator_manager.html')

@bp.route('/api/indicators', methods=['GET'])
def get_indicators():
    try:
        indicators = indicator_manager.get_all_indicators()
        return jsonify({
            'success': True,
            'indicators': indicators
        })
    except Exception as e:
        logging.error(f"获取指标列表失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators/<int:id>', methods=['GET'])
def get_indicator(id):
    try:
        indicators = indicator_manager.get_all_indicators()
        indicator = next((i for i in indicators if i['id'] == id), None)
        if indicator:
            return jsonify({
                'success': True,
                'indicator': indicator
            })
        else:
            return jsonify({
                'success': False,
                'message': '指标不存在'
            })
    except Exception as e:
        logging.error(f"获取指标详情失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators', methods=['POST'])
def add_indicator():
    try:
        data = request.get_json()
        name = data.get('name')
        view_number = data.get('view_number')
        class_name = data.get('class_name')
        
        if not all([name, view_number, class_name]):
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            })
            
        indicator_manager.add_indicator(name, view_number, class_name)
        return jsonify({
            'success': True,
            'message': '添加指标成功'
        })
    except Exception as e:
        logging.error(f"添加指标失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators/<int:id>', methods=['PUT'])
def update_indicator(id):
    try:
        data = request.get_json()
        name = data.get('name')
        view_number = data.get('view_number')
        class_name = data.get('class_name')
        
        if not all([name, view_number, class_name]):
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            })
            
        indicator_manager.update_indicator(id, name, view_number, class_name)
        return jsonify({
            'success': True,
            'message': '更新指标成功'
        })
    except Exception as e:
        logging.error(f"更新指标失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators/<int:id>', methods=['DELETE'])
def delete_indicator(id):
    try:
        indicator_manager.delete_indicator(id)
        return jsonify({
            'success': True,
            'message': '删除指标成功'
        })
    except Exception as e:
        logging.error(f"删除指标失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@bp.route('/api/indicators/<int:id>/toggle', methods=['POST'])
def toggle_indicator(id):
    try:
        data = request.get_json()
        is_enabled = data.get('is_enabled')
        
        if is_enabled is None:
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            })
            
        indicator_manager.toggle_indicator(id, is_enabled)
        return jsonify({
            'success': True,
            'message': '切换指标状态成功'
        })
    except Exception as e:
        logging.error(f"切换指标状态失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

# 辅助函数
def AddMessage(message):
    global sendAllMessage
    sendAllMessage += message + "\n"

def SendAllMessages():
    stockGlobal.wx.SendMsg(sendAllMessage, "光影相生") 

def SendSignalMessages(messages):
    stockGlobal.wx.SendMsg(messages, "光影相生") 

def update_all_stocks(SkipZeroSocks = True):
    try:
        stocks = fetcher.get_stock_list()
        updated_count = 0
        failed_stocks = []
        signalsMessages = []
        logger.info(stocks)
        for stock in stocks:
            try:
                logger.info(f"正在更新股票 {stock['code']} 的数据...")
                df = fetcher.get_stock_data(stock['code'], days=365)
                
                if df is not None and not df.empty:
                    df = analyzer.calculate_indicators(df)


                    df['trade_date'] = df['trade_date'].dt.strftime('%Y-%m-%d')

                    formatted_date = datetime.now().strftime("%Y-%m-%d")
                    signals = analyzer.generate_signals(df)
                    message = formatted_date + "\n股票：" + stock['name'] + "(" + stock['code'] + ")"
                    if len(signals) == 0:
                        if SkipZeroSocks: 
                            continue
                        message = "\n未触发任何信号"
                    else:
                        for signal in signals:
                            message = message + "\n" + signal['message']

                    signalsMessages.append(message)
                    updated_count += 1
                    logger.info(f"股票 {stock['code']} 更新成功: {message}")
                else:
                    failed_stocks.append(stock['code'])
                    logger.error(f"股票 {stock['code']} 更新失败：无法获取数据")
                
            except Exception as e:
                failed_stocks.append(stock['code'])
                logger.error(f"更新股票 {stock['code']} 时出错: {str(e)}", exc_info=True)
        
        return updated_count, failed_stocks, signalsMessages
        
    except Exception as e:
        logger.error(f"更新所有股票时出错: {str(e)}", exc_info=True)
        raise

def calculate_amplitude(df):
    try:
        df['amplitude'] = (df['high'] - df['low']) / df['close'].shift(1) * 100
        avg_amplitude = df['amplitude'].mean()
        
        return {
            'average_amplitude': round(avg_amplitude, 2),
            'max_amplitude': round(df['amplitude'].max(), 2),
            'min_amplitude': round(df['amplitude'].min(), 2),
            'latest_amplitude': round(df['amplitude'].iloc[-1], 2)
        }
    except Exception as e:
        logger.error(f"计算振幅时出错: {str(e)}", exc_info=True)
        return None

def check_signal_conditions(df, stock_code):
    if df.empty:
        return
    
    latest_data = df.iloc[-1]
    
    try:
        '''
        is_between_2_3_sigma = (latest_data['high'] >= latest_data['boll_upper2'] and 
                               latest_data['high'] <= latest_data['boll_upper3'])
        is_below_3_sigma = latest_data['high'] > latest_data['boll_upper3']

        if is_between_2_3_sigma or is_below_3_sigma:
            message = f"""
股票 {stock_code} 出现BOLL带信号！
日期: {latest_data['trade_date']}
收盘价: {latest_data['close']:.2f}
最低价: {latest_data['low']:.2f}
成交量： {latest_data['volume'] / 10000:.2f}
BOLL指标:
- 中轨: {latest_data['boll_mid']:.2f}
- 下轨(2σ): {latest_data['boll_lower2']:.2f}
- 下轨(3σ): {latest_data['boll_lower3']:.2f}
MACD指标:
- MACD: {latest_data['macd']:.3f}
- 信号线: {latest_data['macd_signal']:.3f}
- 柱状值: {latest_data['macd_hist']:.3f}
KDJ指标:
- K值: {latest_data['k']:.2f}
- D值: {latest_data['d']:.2f}
- J值: {latest_data['j']:.2f}
信号类型: {'低于3σ下轨' if is_below_3_sigma else '位于2σ-3σ之间'}
"""
            logger.info(f"触发信号 - 股票代码: {stock_code}")
            '''
        return "message"
    except Exception as e:
        logger.error(f"检查信号条件时出错: {str(e)}", exc_info=True) 

@bp.route('/stock_filter')
def stock_filter():
    """股票筛选器页面"""
    return render_template('stock_filter.html')

@bp.route('/api/filter_stocks', methods=['GET'])
def filter_stocks():
    """处理股票筛选请求"""
    try:
        # 从 URL 参数中获取数据
        data = {
            'market': request.args.get('market', 'CN'),
            'period': request.args.get('period', 'k1d'),
            'filterSignal': request.args.getlist('filterSignal'),  # 获取多个值
            'volume': request.args.get('volume', ''),
            'priceMin': request.args.get('priceMin'),
            'priceMax': request.args.get('priceMax'),
            'dayRange': request.args.get('dayRange')
        }
        
        filter = StockFilger()

        def Progress():
            stocks = manager.get_stock_list()

            index = 0
            maxNum =  len(stocks)
            resultData = []
            signals = []
            avg_returnAll = 0.0
            positive_probAll = 0.0
            for stock in stocks:
                logger.info(f"{index}/{maxNum}更新股票：{stock['code']} -- {stock['name']}")
                code = stock['code']
                #code = '001323'
                manager.update_stock_history(code)
               
                df = manager.get_stock_data(code, 365)
                filterSignals = data['filterSignal']
                dayRange = data['dayRange']
                signal,avg_return ,positive_prob  = filter.filter_stock(df, dayRange, filterSignals)
                newData = {"code": code, "avg_return": "{:.2f}".format(float(avg_return)), "positive_prob" : "{:.2f}".format(float(positive_prob) * 100)}
                resultData.append(newData)
                avg_returnAll = avg_returnAll + float(avg_return)
                positive_probAll = positive_probAll + float(positive_prob)
                if signal != None:
                    signals.append(signal)
                index = index + 1
                # 更新进度信息
                progress = {
                    'type': 'progress',
                    'current': index,
                    'total': maxNum,
                    'current_stock': "a",#stock['code'],
                    'matched_count': 1#len(matched_stocks)
                }
                delay = config.get('DEFAULT', 'UPDATE_STOCKS_DELAY')
                time.sleep(float(delay))
                yield f"data: {json.dumps(progress)}\n\n"
                #signalMsg = ""
                #if index == 2:
                #    break
                ''''if isCheckSingle:
                    signalMsg = checkFunc(stock['code'], self)# check_signal.CheckSingle(stock['code'], self)
                if signalMsg != None and signalMsg != "":
                    outMessage = outMessage + signalMsg + "\n"'''
            avg_returnAll = avg_returnAll / index
            positive_probAll = positive_probAll / index
            print(f"平均上涨幅度:{avg_returnAll},  平均上涨概率： {positive_probAll}")
            msg = filter.SignalToWeChatData(signals)
            print(msg)
            with open("output.csv", "w", newline="", encoding="utf-8") as file:
                fieldnames = ["code", "avg_return", "positive_prob"]  # 定义列名
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()  # 自动写入标题行
                writer.writerows(resultData)  # 写入多行数据
            SendSignalMessages(msg)
             # 发送最终结果
            final_result = {
                'type': 'result',
                'success': True,
                'data': "matched_stocks",
                'progress': {
                    'current': maxNum,
                    'total': maxNum,
                    'matched_count': 10
                }
            }
            yield f"data: {json.dumps(final_result)}\n\n"

        
                
        
        '''return jsonify({
            'success': True,
            'data': results
        })'''
        
    except Exception as e:
        logger.error(f"股票筛选失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }) 
    return Response(stream_with_context(Progress()), mimetype='text/event-stream')

##########################################Scan Routes########################################
@bp.route('/api/save-timed-scan', methods=['POST'])
def SaveTimedScan():
    data = request.get_json()
    print("接收到的数据：", data)

    scanManager = ScanManager()
    return scanManager.SaveTimedScan(data)

@bp.route('/api/get-timed-scan-list', methods=['GET'])
def get_TimedScan_List():
    """定时扫描列表"""
    try:
        scanManager = ScanManager()
        return scanManager.GetTimedScanList()
    except Exception as e:
        logger.error(f"获取定时扫描列表失败: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

##########################################Scan Routes########################################



########################股票实时数据######################
# 存储活跃的WebSocket连接
active_connections = {}

socketio = stockGlobal.socketio

# WebSocket连接处理
'''
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')
    # 清理连接
    for stock_code in list(active_connections.keys()):
        if request.sid in active_connections[stock_code]:
            active_connections[stock_code].remove(request.sid)
            if not active_connections[stock_code]:
                del active_connections[stock_code]
                '''