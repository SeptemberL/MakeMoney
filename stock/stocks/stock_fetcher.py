import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
import logging
from database.database import Database
from typing import List, Dict, Optional, Union

logger = logging.getLogger(__name__)

class StockFetcher:
    def __init__(self):
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """确保股票表存在（MySQL/SQLite 双模式）"""
        db = Database.Create()
        try:
            if db.is_sqlite:
                create_table_sql = """
                CREATE TABLE IF NOT EXISTS stocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    alert_enabled INTEGER DEFAULT 0,
                    alert_upper_threshold REAL DEFAULT NULL,
                    alert_lower_threshold REAL DEFAULT NULL
                )
                """
                db.execute(create_table_sql)
                db.execute("CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks (code)")
            else:
                create_table_sql = """
                CREATE TABLE IF NOT EXISTS stocks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    code VARCHAR(10) NOT NULL UNIQUE,
                    name VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    alert_enabled BOOLEAN DEFAULT FALSE,
                    alert_upper_threshold DECIMAL(10,2) DEFAULT NULL,
                    alert_lower_threshold DECIMAL(10,2) DEFAULT NULL,
                    INDEX idx_code (code)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
                db.execute(create_table_sql)
            logger.info("股票表创建或已存在")
        except Exception as e:
            logger.error(f"创建股票表时出错: {str(e)}")
            raise
        finally:
            db.close()

    def get_stock_list(self) -> List[Dict[str, str]]:
        """获取所有股票列表"""
        cursor = None
        try:
            db = Database.Create()
            query = "SELECT code, name FROM stocks ORDER BY code"
            results = db.fetch_all(query)
            
            # 处理查询结果
            stocks = []
            for row in results:
                # 根据返回类型处理结果
                if isinstance(row, dict):
                    # 如果已经是字典格式
                    stocks.append({'code': row['code'], 'name': row['name']})
                else:
                    # 如果是元组格式
                    stocks.append({'code': row[0], 'name': row[1]})
            return stocks
            
        except Exception as e:
            logger.error(f"获取股票列表失败: {str(e)}")
            return []
        finally:
            db.close()

    def add_stock(self, code: str, name: str = None) -> bool:
        """添加新股票"""
        try:
            db = Database.Create()
            # 如果没有提供名称，尝试从 akshare 获取
            if not name:
                try:
                    # 这里可以添加从 akshare 获取股票名称的代码
                    # 示例: name = ak.stock_info_a_code_name()...
                    pass
                except Exception as e:
                    logger.error(f"从 akshare 获取股票名称失败: {str(e)}")
                    return False

            # 检查股票是否已存在
            check_query = "SELECT code FROM stocks WHERE code = %s"
            existing = db.fetch_one(check_query, (code,))
            
            if existing:
                # 更新现有记录
                update_query = """
                UPDATE stocks 
                SET name = %s, updated_at = CURRENT_TIMESTAMP
                WHERE code = %s
                """
                db.execute(update_query, (name, code))
            else:
                # 插入新记录
                insert_query = """
                INSERT INTO stocks (code, name) 
                VALUES (%s, %s)
                """
                db.execute(insert_query, (code, name))

            return True

        except Exception as e:
            logger.error(f"添加股票失败: {str(e)}")
            return False
        finally:
            db.close()

    def delete_stock(self, code: str) -> bool:
        """删除股票"""
        try:
            db = Database.Create()
            query = "DELETE FROM stocks WHERE code = %s"
            db.execute(query, (code,))
            return True
        except Exception as e:
            logger.error(f"删除股票失败: {str(e)}")
            return False
        finally:
            db.close()

    def get_stock_data(self, code: str, days: int = -1) -> Optional[pd.DataFrame]:
        """获取股票历史数据"""
        try:
            # 确保股票数据表存在
            if not self._ensure_stock_table_exists(code):
                return None
            db = Database.Create()
            # 检查股票是否有历史数据
            has_data = self._stock_has_data(code)
            latest_date = self._get_latest_stock_date(code) if has_data else None

            # 确定获取数据的日期范围
            if has_data and latest_date:
                start_date = latest_date.strftime('%Y%m%d')
                new_data_only = True
            else:
                start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
                new_data_only = False

            # 使用 akshare 获取股票数据
            df = ak.stock_zh_a_hist(symbol=code, period="daily", 
                                  start_date=start_date,
                                  end_date=datetime.now().strftime('%Y%m%d'),
                                  adjust="qfq")
            
            if df is None or df.empty:
                return None

            # 处理数据
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
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            
            numeric_columns = ['open', 'close', 'high', 'low', 'volume', 'amount']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # 存储新数据
            self._store_stock_data(code, df)

            # 如果需要获取完整数据（包括已有数据）
            if not new_data_only:
                return df
            else:
                # 从数据库获取完整数据
                table_name = self._get_stock_table_name(code)
                query = f"""
                SELECT trade_date, open, high, low, close, volume, amount 
                FROM {table_name}
                ORDER BY trade_date
                """
                db_data = db.fetch_all(query)
                return pd.DataFrame(db_data) if db_data else df
            
        except Exception as e:
            logger.error(f"获取股票 {code} 数据失败: {str(e)}")
            return None
        finally:
            db.close()


    def _stock_has_data(self, code: str) -> bool:
        """检查股票是否有历史数据"""
        try:
            db = Database.Create()
            table_name = self._get_stock_table_name(code)
            query = f"SELECT 1 FROM {table_name} LIMIT 1"
            result = db.fetch_one(query)
            return result is not None
        except Exception as e:
            logger.error(f"检查股票 {code} 历史数据失败: {str(e)}")
            return False
        finally:
            db.close()
        

    def _get_latest_stock_date(self, code: str) -> Optional[datetime]:
        """获取股票最新的数据日期"""
        try:
            table_name = self._get_stock_table_name(code)
            query = f"SELECT MAX(trade_date) FROM {table_name}"
            result = db.fetch_one(query)
            return result[0] if result and result[0] else None
        except Exception as e:
            logger.error(f"获取股票 {code} 数据失败: {str(e)}")
            return None
        finally:
            db.close()

    def _store_stock_data(self, code: str, df: pd.DataFrame) -> bool:
        """存储股票数据到数据库"""
        table_name = self._get_stock_table_name(code)
        try:
            db = Database.Create()
            # 准备数据
            data_to_insert = []
            for _, row in df.iterrows():
                data_to_insert.append((
                    row['trade_date'],
                    row['code'],
                    row['open'],
                    row['high'],
                    row['low'],
                    row['close'],
                    row['volume'],
                    row['amount'],
                    row['amplitude'],
                    row['pct_change'],
                    row['p_change'],
                    row['turnover_rate']
                ))

            # 批量插入
            insert_query = f"""
            INSERT INTO {table_name} 
            (trade_date, code, open, high, low, close, volume, amount, amplitude, pct_change, p_change, turnover_rate)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                open = VALUES(open),
                high = VALUES(high),
                low = VALUES(low),
                close = VALUES(close),
                volume = VALUES(volume),
                amount = VALUES(amount)
            """
            db.execute(insert_query, data_to_insert, many=True)
            return True
        except Exception as e:
            logger.error(f"存储股票数据失败: {str(e)}")
            return False
        finally:
            db.close()

