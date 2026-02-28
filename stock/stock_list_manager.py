import akshare as ak
import pandas as pd
import logging
from typing import List, Dict
from datetime import datetime, timedelta
import check_signal
from database.database import Database

logger = logging.getLogger(__name__)

class StockListManager:
    def __init__(self):
        self.stock_list = None

    #检查stock_list表是否已经存在
    def _ensure_table_exists(self, db = None) -> bool:
        """
        确保stock_list表存在
        """
        if db == None:
            db = Database.Create()
        try:
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS stock_list (
                id INT AUTO_INCREMENT PRIMARY KEY,
                code VARCHAR(10) NOT NULL UNIQUE,
                name VARCHAR(50) NOT NULL,
                market VARCHAR(10) NOT NULL,
                status TINYINT DEFAULT 1 COMMENT '1:正常交易 0:停牌',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_code (code),
                INDEX idx_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            db.execute(create_table_sql)
            logger.info("stock_list表创建成功或已存在")
            return True
        except Exception as e:
            logger.error(f"创建stock_list表失败: {str(e)}")
            return False

    def get_all_a_stocks(self) -> List[Dict[str, str]]:
        """
        获取所有A股股票信息，并筛选：
        1. 只保留00和60开头的股票
        2. 排除退市股票
        3. 排除ST股票
        返回: 股票列表和isSameDay标志(表示数据是否当天更新过)
        """
        # 检查数据是否当天更新过
        db = Database.Create()
        isSameDay = False
        try:
            result = db.fetch_one("SELECT updated_at FROM stock_list LIMIT 1")
            if result and 'updated_at' in result:
                last_update = result['updated_at']
                if isinstance(last_update, str):
                    last_update = datetime.strptime(last_update, '%Y-%m-%d %H:%M:%S')
                current_date = datetime.now()
                isSameDay = last_update.date() == current_date.date()
        except Exception as e:
            logger.warning(f"检查更新日期失败: {str(e)}")
        try:
            # 获取所有A股列表
            df = ak.stock_info_a_code_name()
            
            # 确保代码列为字符串类型
            df['code'] = df['code'].astype(str)
            
            # 筛选00和60开头的股票
            mask = df['code'].str.startswith(('00', '60'))
            df = df[mask].copy()
            
            # 添加市场信息
            df['market'] = df['code'].apply(lambda x: 'SZ' if x.startswith('00') else 'SH')
            
            # 获取股票状态信息
            #status_df = ak.stock_info_sz_status_cm()
            # 合并深市状态信息
            #df = pd.merge(
            #    df,
            #    status_df[['证券代码', '上市状态']],
            #    left_on='code',
            #    right_on='证券代码',
            #    how='left'
            #)
            
            # 筛选上市状态为"上市"的股票
            #df = df[df['name'].str.contains('上市')]
            
            # 排除ST股票（股票名称中包含ST或*ST）
            df = df[~df['name'].str.contains('ST|退')]
            
            # 转换为列表格式
            stocks = []
            for _, row in df.iterrows():
                stocks.append({
                    'code': row['code'],
                    'name': row['name'],
                    'market': row['market']
                })
            
            self.stock_list = stocks
            logger.info(f"成功获取 {len(stocks)} 只股票信息")
            return {
                'stocks': stocks,
                'isSameDay': isSameDay
            }
            
        except Exception as e:
            logger.error(f"获取股票列表失败: {str(e)}")
            return []

    def save_to_database(self) -> bool:
        """
        将股票列表保存到数据库
        """
        try:
            db = Database.Create()
            if not self.stock_list:
                result = self.get_all_a_stocks(db)
                if result and result.get('stocks'):
                    self.stock_list = result['stocks']
                    self.needUpdate = not result['isSameDay']
                else:
                    return False
            
            # 确保表存在
            if not self._ensure_table_exists(db):
                return False
            
            if not self.needUpdate:
                return True

            # 开始事务
            success_count = 0
            try:
                # 先将所有股票状态设置为0
                db.execute("UPDATE stock_list SET status = 0")
                
                for stock in self.stock_list:
                    # 使用REPLACE INTO来处理更新和插入
                    db.execute(
                        """
                        REPLACE INTO stock_list 
                        (code, name, market, status) 
                        VALUES (%s, %s, %s, 1)
                        """,
                        (stock['code'], stock['name'], stock['market'])
                    )
                    success_count += 1
                
                logger.info(f"成功保存 {success_count} 只股票到数据库")
                return True
                
            except Exception as e:
                logger.error(f"保存股票列表失败: {str(e)}")
                return False
            
        except Exception as e:
            logger.error(f"保存股票列表失败: {str(e)}")
            return False

    def get_active_stocks(self) -> List[Dict[str, str]]:
        """
        获取数据库中的活跃股票列表
        """
        try:
            db = Database.Create()
            query = """
            SELECT code, name, market 
            FROM stock_list 
            WHERE status = 1 
            ORDER BY code
            """
            results = db.fetch_all(query)
            return results
        except Exception as e:
            logger.error(f"获取活跃股票列表失败: {str(e)}")
            return []
        finally:
            db.close()

    def get_stock_list(self):
        """
        更新股票列表
        1. 获取最新的股票列表
        2. 保存到数据库
        """
        try:
            # 获取最新股票列表
            db = Database.Create()
            result = self.get_all_a_stocks()
            if not result or not result.get('stocks'):
                return False
                
            new_stocks = result['stocks']
            self.needUpdate = not result['isSameDay']
            self.stock_list = new_stocks
            print("update_stock_list:", self.stock_list)
            return self.stock_list
        except Exception as e:
            logger.error(f"更新股票列表失败: {str(e)}")
            return False
        finally:
            db.close()  

    def update_stock_list(self, isCheckSingle:bool, checkFunc) -> bool:
        """
        更新股票列表
        1. 获取最新的股票列表
        2. 保存到数据库
        """
        try:
            # 获取最新股票列表
            db = Database.Create()
            result = self.get_all_a_stocks()
            if not result or not result.get('stocks'):
                return False
                
            new_stocks = result['stocks']
            self.needUpdate = not result['isSameDay']
            self.stock_list = new_stocks
            print("update_stock_list:", self.stock_list)
            
            # 保存到数据库
            #saveSocksSuccess = self.save_to_database(db)
            #更新所有股票数据到本地数据库
            saveSocksSuccess = True
            outMessage = ""
            if saveSocksSuccess:
                index = 1
                maxNum =  len(self.stock_list)
                for stock in self.stock_list:
                    logger.info(f"{index}/{maxNum}更新股票：{stock['code']} -- {stock['name']}")
                    self.update_stock_history(stock['code'])
                    index = index + 1
                    signalMsg = ""
                    if isCheckSingle:
                        signalMsg = checkFunc(stock['code'], self)# check_signal.CheckSingle(stock['code'], self)
                    if signalMsg != None and signalMsg != "":
                        outMessage = outMessage + signalMsg + "\n"
                    #if index == 10:
                    #    break
            return saveSocksSuccess, outMessage
            
        except Exception as e:
            logger.error(f"更新股票列表失败: {str(e)}")
            return False
        finally:
            db.close()  

    def _get_stock_table_name(self, code: str) -> str:
            """获取股票对应的数据表名"""
            # 根据股票代码判断市场 (SH=上海, SZ=深圳)
            market = 'SH' if code.startswith(('6', '9')) else 'SZ'
            return f"stock_{code}_{market}"

    def _create_stock_table(self, table_name: str) -> bool:
        """确保股票数据表存在"""
        try:
            db = Database.Create()
            create_table_sql = f"""
            CREATE TABLE {table_name} (
                        trade_date DATE PRIMARY KEY,
                        code VARCHAR(10) NOT NULL,
                        open DECIMAL(10,2),
                        high DECIMAL(10,2),
                        low DECIMAL(10,2),
                        close DECIMAL(10,2),
                        volume BIGINT,
                        amount DECIMAL(20,2),
                        amplitude DECIMAL(10,2),
                        pct_change DECIMAL(10,2),
                        p_change DECIMAL(10,2),
                        turnover_rate DECIMAL(10,2),
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_trade_date (trade_date)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            
            """
            db.execute(create_table_sql)
            logger.info(f"股票数据表 {table_name} 创建或已存在")
            return True
        except Exception as e:
            logger.error(f"创建股票数据表 {table_name} 失败: {str(e)}")
            return False
        finally:
            db.close()


    #更新单只股票的历史数据
    def update_stock_history(self, stock_id):
        """
        更新股票历史数据
        :param stock_id: 股票代码（如：600000.SH）
        :param database: MySQL数据库连接对象
        :return: True 如果更新成功，False 如果失败
        """
        cursor = None
        try:
            db = Database.Create()
            table_name = self._get_stock_table_name(stock_id)
            # 检查表是否存在
            sqlquery = f"""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = '{table_name}'"""
            cursor = db.execute(sqlquery)
            result = cursor.fetchone()
            logger.info(f"table {table_name} is Exists  {result["COUNT(*)"]}")
            # 获取当前日期
            current_date = datetime.now().strftime('%Y%m%d')
            update_at = None
            if result["COUNT(*)"] == 0:
                #没有对应股票的表格，则创建股票独立表格
                self._create_stock_table(table_name)
                logger.info(f"创建表 {table_name}")
                
                need_full_history = True
                last_Updated_date = None
            else:
                # 获取最新的交易日期
                cursor = db.execute(f"SELECT trade_date,updated_at  FROM {table_name} WHERE trade_date = (SELECT MAX(trade_date) FROM {table_name})")
                last_date = None
                fetch_result = cursor.fetchone()
                if fetch_result != None and fetch_result["trade_date"] is not None:
                    last_date = fetch_result["trade_date"]
                    last_Updated_date = fetch_result["updated_at"]
                need_full_history = last_date  is None

            # 确定股票市场
            market = 'A股'
            """if '.SH' in stock_id or '.SS' in stock_id:
                symbol = stock_id.split('.')[0]
                market = 'A股'
            elif '.SZ' in stock_id:
                symbol = stock_id.split('.')[0]
                market = 'A股'
            elif '.HK' in stock_id:
                symbol = stock_id.replace('.HK', '')
                market = '港股'
            else:
                symbol = stock_id
                market = '美股'"""

            try:
                needUpdate = False
                needUpdateCurrentDate = False
                if market == 'A股':
                    if need_full_history:
                        logger.info(f"获取{stock_id}股票所有数据")
                        df = ak.stock_zh_a_hist(symbol=stock_id, period="daily", 
                                              adjust="qfq", start_date='19900101')
                        needUpdate = True
                    else:
                        # 将时间设置为当天 15:00:00
                        threshold_time = datetime.now().replace(hour=15, minute=0, second=0)

                        # 判断 last_date 是否在当天 15 点之前
                        if int(last_date.strftime('%Y%m%d')) < int(current_date):
                            start_date = (last_date + timedelta(days=1)).strftime('%Y%m%d')
                            logger.info(f"获取{stock_id}股票数据{start_date}到今天的")
                            df = ak.stock_zh_a_hist(symbol=stock_id, period="daily", 
                                                adjust="qfq", start_date=start_date)
                            needUpdate = True
                        elif last_Updated_date < threshold_time:
                            start_date = (last_Updated_date).strftime('%Y%m%d')
                            logger.info(f"获取{stock_id}股票数据{start_date}到今天的")
                            df = ak.stock_zh_a_hist(symbol=stock_id, period="daily", 
                                                adjust="qfq", start_date=start_date)
                            needUpdateCurrentDate = True
                            needUpdate = True
                if needUpdate:
                    df = df.rename(columns={
                        '日期': 'trade_date',
                        '股票代码': 'code',
                        '开盘': 'open',
                        '最高': 'high',
                        '最低': 'low',
                        '收盘': 'close',
                        '成交量': 'volume',
                        '成交额': 'amount',
                        '振幅': 'amplitude',
                        '涨跌幅': 'pct_change',
                        '涨跌额': 'p_change',
                        '换手率': 'turnover_rate'
                    })
                    if len(df) > 0:
                        # 确保日期格式统一
                        tradeTime =  pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')[0]
                        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
                        sql = ""
                        # 使用批量插入
                        values = df.to_dict('records')
                        placeholders = ', '.join(['%s'] * len(df.columns))
                        columns = ', '.join(df.columns)
                        data = None
                        if needUpdateCurrentDate:
                            # 提取当前行的值
                            trade_date_value = df['trade_date']
                            # 构建更新语句
                            update_stmt = ', '.join([f"{col} = %s" for col in df.columns if col != 'trade_date'])
                            update_stmt = update_stmt + ", updated_at = CURRENT_TIMESTAMP "
                             # 设定条件，确保只更新当天的记录
                            condition = f"trade_date = '{tradeTime}'"
                            sql = f"""
                                    UPDATE {table_name}
                                    SET {update_stmt}
                                    WHERE {condition}
                                """
                            # 提取其他列的值
                            #data = [df.columns[col] for col in df.columns if col != 'trade_date']
                             # 准备数据
                              # 准备数据
                            data = [[row[col] for col in df.columns] for row in values]
                            print(data)
                            print("~~~~~~~~~~~~~~")
                            data = [[row[col] for col in df.columns if col != 'trade_date'] for row in values]
                            #data[0].append(tradeTime)
                            print(data)
                            print("~~~~~~~~~~~~~~") 
                            print(sql)                            
                        else:
                            # 构建INSERT ON DUPLICATE KEY UPDATE语句
                            update_stmt = ', '.join([f"{col}=VALUES({col})" 
                                                for col in df.columns if col != 'trade_date'])
                                
                            sql = f"""
                                INSERT INTO {table_name} ({columns})
                                VALUES ({placeholders})
                                ON DUPLICATE KEY UPDATE {update_stmt}
                            """
                            # 准备数据
                            data = [[row[col] for col in df.columns] for row in values]
                           
                        
                           
                        # 执行批量插入
                        cursor.executemany(sql, data)
                        db.commit()
                        
                        logger.info(f"成功更新股票 {stock_id} 的历史数据，新增/更新 {len(df)} 条记录")
                        return True
                    else:
                        logger.info(f"股票 {stock_id} 没有新数据需要更新")
                        return True

                else:
                    logger.info(f"股票 {stock_id} 没有新数据需要更新")
                    return True
            except Exception as e:
                logger.error(f"获取股票 {stock_id} 数据时出错: {str(e)}", exc_info=True)
                db.rollback()
                return False

        except Exception as e:
            logger.error(f"更新股票 {stock_id} 历史数据时出错: {str(e)}", exc_info=True)
            if db.is_connected():
                db.rollback()
            return False

        finally:
            if cursor:
                cursor.close()
            db.close()

    def get_stock_data(self, stock_id, days = 365):
        """
        获取股票历史数据
        :param stock_id: 股票代码
        :param start_date: 开始日期（可选）
        :param end_date: 结束日期（可选）
        :return: DataFrame 包含股票数据
        """
        try:
            db = Database.Create()
            table_name = self._get_stock_table_name(stock_id)
            
            query = f"SELECT * FROM {table_name}"
            conditions = []
            params = []
            
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
            end_date = datetime.now().strftime('%Y%m%d')

            if start_date:
                conditions.append("trade_date >= %s")
                params.append(start_date)
            if end_date:
                conditions.append("trade_date <= %s")
                params.append(end_date)
                
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
                
            query += " ORDER BY trade_date"
            
            # 使用Database类方法获取数据
            results = db.fetch_all(query, params)
            if results:
                df = pd.DataFrame(results)
                # 确保日期格式统一
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date'])
                return df
            return None
            
        except Exception as e:
            logger.error(f"获取股票 {stock_id} 数据时出错: {str(e)}", exc_info=True)
            return None
        finally:
            db.close()

