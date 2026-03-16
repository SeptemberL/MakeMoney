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
        self.needUpdate = True  # 是否需写入库，由 get_all_a_stocks 的 isSameDay 决定

    #检查stock_list表是否已经存在
    def _ensure_table_exists(self, db = None) -> bool:
        """
        确保stock_list表存在（MySQL/SQLite 双模式）
        """
        if db is None:
            db = Database.Create()
        try:
            if db.is_sqlite:
                create_table_sql = """
                CREATE TABLE IF NOT EXISTS stock_list (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    market TEXT NOT NULL,
                    status INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
                db.execute(create_table_sql)
                db.execute("CREATE INDEX IF NOT EXISTS idx_stock_list_code ON stock_list (code)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_stock_list_status ON stock_list (status)")
            else:
                create_table_sql = """
                CREATE TABLE IF NOT EXISTS stock_list (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    code VARCHAR(10) NOT NULL UNIQUE,
                    name VARCHAR(50) NOT NULL,
                    market VARCHAR(10) NOT NULL,
                    status TINYINT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_code (code),
                    INDEX idx_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
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
        1. 保留主板(00/60)、创业板(300)、科创板(688)的股票
        返回: 股票列表和isSameDay标志(表示数据是否当天更新过)
        """
        # 检查数据是否当天更新过
        isSameDay = False
        db = None
        try:
            db = Database.Create()
            result = db.fetch_one("SELECT updated_at FROM stock_list LIMIT 1")
            if result and 'updated_at' in result:
                last_update = result['updated_at']
                if isinstance(last_update, str):
                    last_update = datetime.strptime(last_update, '%Y-%m-%d %H:%M:%S')
                current_date = datetime.now()
                isSameDay = last_update.date() == current_date.date()
        except Exception as e:
            logger.warning("检查更新日期失败: %s", str(e))
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass
        try:
            # 获取所有A股列表（易失败的外部调用）
            logger.info("正在从 akshare 拉取全市场 A 股列表…")
            df = ak.stock_info_a_code_name()
            
            # 确保代码列为字符串类型
            df['code'] = df['code'].astype(str)
            
            # 筛选主板(00/60)、创业板(300)、科创板(688)的股票
            mask = df['code'].str.startswith(('00', '30', '60', '688'))
            df = df[mask].copy()
            
            # 添加市场信息：00/30开头属于深圳(SZ)，60/688开头属于上海(SH)
            df['market'] = df['code'].apply(
                lambda x: 'SZ' if x.startswith(('00', '30')) else 'SH'
            )
            
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
            df = df[~df['name'].str.contains('退')]
            
            
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
            logger.error(f"获取股票列表失败: {str(e)}", exc_info=True)
            return {'stocks': [], 'isSameDay': False}

    def save_to_database(self) -> bool:
        """
        将股票列表保存到数据库
        """
        db = None
        try:
            db = Database.Create()
            if not self.stock_list:
                result = self.get_all_a_stocks()
                if not result or not result.get('stocks'):
                    logger.warning("save_to_database: 无股票列表可保存")
                    return False
                self.stock_list = result['stocks']
                self.needUpdate = not result.get('isSameDay', True)
            
            # 确保表存在
            if not self._ensure_table_exists(db):
                return False

            if not self.needUpdate:
                logger.info("股票列表今日已更新，跳过写入")
                return True

            success_count = 0
            db.execute("UPDATE stock_list SET status = 0")
            for stock in self.stock_list:
                try:
                    db.execute(
                        """
                        REPLACE INTO stock_list 
                        (code, name, market, status) 
                        VALUES (%s, %s, %s, 1)
                        """,
                        (stock['code'], stock['name'], stock['market'])
                    )
                    success_count += 1
                except Exception as e:
                    logger.warning("写入股票 %s 失败: %s", stock.get('code'), str(e))
            logger.info("成功保存 %s 只股票到数据库", success_count)
            return True
        except Exception as e:
            logger.error(f"保存股票列表失败: {str(e)}", exc_info=True)
            return False
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    def get_active_stocks(self) -> List[Dict[str, str]]:
        """
        获取数据库中的活跃股票列表
        """
        db = None
        try:
            db = Database.Create()
            query = """
            SELECT code, name, market 
            FROM stock_list 
            WHERE status = 1 
            ORDER BY code
            """
            return db.fetch_all(query)
        except Exception as e:
            logger.error("获取活跃股票列表失败: %s", str(e), exc_info=True)
            return []
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    def get_stock_list(self):
        """
        获取最新股票列表（不写库），更新内存中的 self.stock_list。
        返回 list 或 False。
        """
        try:
            result = self.get_all_a_stocks()
            if not result or not result.get('stocks'):
                return False
            self.needUpdate = not result.get('isSameDay', True)
            self.stock_list = result['stocks']
            logger.info("get_stock_list: 共 %s 只股票", len(self.stock_list))
            return self.stock_list
        except Exception as e:
            logger.error(f"更新股票列表失败: {str(e)}", exc_info=True)
            return False  

    def update_stock_list(
        self,
        isCheckSingle: bool,
        checkFunc,
        progressFunc=None,
        limit: int = None,
    ):
        """
        更新股票列表并可选更新历史数据。
        1. 获取最新股票列表并 save_to_database 写入库
        2. 若 limit 有值则只处理前 limit 只（便于小规模验收），否则处理全部
        返回: (success: bool, outMessage: str)
        """
        db = None
        outMessage = ""
        try:
            result = self.get_all_a_stocks()
            if not result or not result.get('stocks'):
                logger.warning("update_stock_list: 未获取到股票列表")
                return False, ""

            self.stock_list = result['stocks']
            self.needUpdate = not result.get('isSameDay', True)
            logger.info("update_stock_list: 共 %s 只股票，limit=%s", len(self.stock_list), limit)

            saveSocksSuccess = self.save_to_database()
            if not saveSocksSuccess:
                return False, ""

            to_process = self.stock_list[:limit] if limit is not None else self.stock_list
            maxNum = len(to_process)
            outMessage = ""
            for index, stock in enumerate(to_process, start=1):
                try:
                    logger.info("%s/%s 更新股票：%s -- %s", index, maxNum, stock['code'], stock['name'])
                    if progressFunc:
                        progressFunc(index, maxNum, stock)
                    self.update_stock_history(stock['code'])
                    if isCheckSingle and checkFunc:
                        signalMsg = checkFunc(stock['code'], self)
                        if signalMsg:
                            outMessage = outMessage + signalMsg + "\n"
                except Exception as e:
                    logger.warning("更新股票 %s 失败: %s", stock.get('code'), str(e))
            return True, outMessage
        except Exception as e:
            logger.error("更新股票列表失败: %s", str(e), exc_info=True)
            return False, str(e)
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass  

    def _get_stock_table_name(self, code: str) -> str:
            """获取股票对应的数据表名"""
            # 根据股票代码判断市场 (SH=上海, SZ=深圳)
            market = 'SH' if code.startswith(('6', '9')) else 'SZ'
            return f"stock_{code}_{market}"

    def _create_stock_table(self, table_name: str) -> bool:
        """确保股票数据表存在（MySQL/SQLite 双模式）"""
        db = None
        try:
            db = Database.Create()
            if db.is_sqlite:
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    trade_date DATE PRIMARY KEY,
                    code TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL,
                    volume INTEGER, amount REAL,
                    amplitude REAL, pct_change REAL, p_change REAL, turnover_rate REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
                db.execute(create_table_sql)
                db.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_trade_date ON {table_name} (trade_date)")
            else:
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    trade_date DATE PRIMARY KEY,
                    code VARCHAR(10) NOT NULL,
                    open DECIMAL(10,2), high DECIMAL(10,2), low DECIMAL(10,2), close DECIMAL(10,2),
                    volume BIGINT, amount DECIMAL(20,2),
                    amplitude DECIMAL(10,2), pct_change DECIMAL(10,2), p_change DECIMAL(10,2),
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
            if db:
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
            # 检查表是否存在（兼容 MySQL/SQLite）
            table_exists = db.table_exists(table_name)
            logger.info("表 %s 存在检查: %s", table_name, table_exists)
            # 获取当前日期
            current_date = datetime.now().strftime('%Y%m%d')
            update_at = None
            if not table_exists:
                #没有对应股票的表格，则创建股票独立表格
                self._create_stock_table(table_name)
                logger.info(f"创建表 {table_name}")
                
                need_full_history = True
                last_Updated_date = None
            else:
                # 获取最新的交易日期
                last_Updated_date = None
                cursor = db.execute(f"SELECT trade_date,updated_at  FROM {table_name} WHERE trade_date = (SELECT MAX(trade_date) FROM {table_name})")
                last_date = None
                fetch_result = cursor.fetchone()
                if fetch_result and fetch_result.get("trade_date") is not None:
                    last_date = fetch_result["trade_date"]
                    last_Updated_date = fetch_result.get("updated_at")
                need_full_history = last_date is None

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
                        now = datetime.now()
                        if now.hour < 15 or (now.hour == 15 and now.minute < 30):
                            end_date = (now - timedelta(days=1)).strftime('%Y%m%d')
                        else:
                            end_date = now.strftime('%Y%m%d')
                        df = ak.stock_zh_a_hist(symbol=stock_id, period="daily", 
                                              adjust="qfq", start_date='19900101', end_date=end_date)
                        needUpdate = True
                    else:
                        # 若更新股票数据库时间早于当天 15:30，只获取到前一天的数据
                        threshold_time = datetime.now().replace(hour=15, minute=30, second=0)
                        now = datetime.now()
                        if now < threshold_time:
                            end_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                        else:
                            end_date = current_date

                        # 判断 last_date 是否在当天 15 点之前
                        if last_date is not None and int(last_date.strftime('%Y%m%d')) < int(current_date):
                            start_date = (last_date + timedelta(days=1)).strftime('%Y%m%d')
                            logger.info(f"获取{stock_id}股票数据{start_date}到{end_date}")
                            df = ak.stock_zh_a_hist(symbol=stock_id, period="daily", 
                                                adjust="qfq", start_date=start_date, end_date=end_date)
                            needUpdate = True
                        elif last_Updated_date is not None and last_Updated_date < threshold_time:
                            start_date = (last_Updated_date).strftime('%Y%m%d')
                            logger.info(f"获取{stock_id}股票数据{start_date}到{end_date}")
                            df = ak.stock_zh_a_hist(symbol=stock_id, period="daily", 
                                                adjust="qfq", start_date=start_date, end_date=end_date)
                            needUpdateCurrentDate = (end_date == current_date)
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


if __name__ == "__main__":
    # 阶段 1.3 小规模验收：仅更新前 2 只股票，验证列表保存 + 历史更新流程
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    manager = StockListManager()
    success, msg = manager.update_stock_list(False, None, limit=2)
    print("成功" if success else "失败", msg or "")

