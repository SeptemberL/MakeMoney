import mysql.connector
from config import Config
import logging
import json
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)

class Database:
    _instance = None
    _connection = None

    @staticmethod
    def Create():
        db = Database()
        db.connect()
        return db   

    """def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
        return cls._instance"""

    def __init__(self):
        self.config = Config()
        self._connection = None

    def connect(self):
        """连接到数据库"""
        try:
            if self._connection and self._connection.is_connected():
                return True
            self._connection = mysql.connector.connect(
                    host=self.config.get('DATABASE', 'DB_HOST'),
                    port=self.config.get_int('DATABASE', 'DB_PORT'),
                    database=self.config.get('DATABASE', 'DB_NAME'),
                    user=self.config.get('DATABASE', 'DB_USER'),
                    password=self.config.get('DATABASE', 'DB_PASSWORD'),
                    charset='utf8mb4',
                    buffered = True
                )

            logger.info(f"数据库连接成功 - 类型: {self.config.get('DATABASE', 'DB_TYPE')}")
            return True
        except Exception as e:
            logger.error(f"数据库连接失败: {str(e)}")
            return False

    def get_connection(self):
        """获取数据库连接"""
        if not self._connection or (
            self.config.get('DATABASE', 'DB_TYPE').lower() == 'mysql' and 
            not self._connection.is_connected()
        ):
            self.connect()
        return self._connection

    def close(self):
        """关闭数据库连接"""
        if self._connection:
            if self.config.get('DATABASE', 'DB_TYPE').lower() == 'mysql':
                if self._connection.is_connected():
                    self._connection.close()
            else:
                self._connection.close()
            self._connection = None
            logger.info("数据库连接已关闭")

    def execute(self, query, params=None):
        """执行SQL查询"""
        cursor = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)  # 使用字典游标
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
                
            conn.commit()
            return cursor
        except Exception as e:
            logger.error(f"执行SQL查询失败: {str(e)}")
            if conn:
                conn.rollback()
            raise

    def fetch_all(self, query, params=None):
        """执行查询并返回所有结果"""
        cursor = None
        try:
            cursor = self.execute(query, params)
            result = cursor.fetchall()
            cursor.close()  # 确保关闭游标
            return result
        except Exception as e:
            logger.error(f"执行查询失败: {str(e)}")
            raise
        finally:
            if cursor:
                cursor.close()  # 确保在出错时也关闭游标

    def fetch_one(self, query, params=None):
        """执行查询并返回一个结果"""
        cursor = self.execute(query, params)
        result = cursor.fetchone()
        cursor.close()
        return result

    def begin_transaction(self):
        """开始事务"""
        self.get_connection().start_transaction()

    def commit(self):
        """提交事务"""
        self.get_connection().commit()

    def rollback(self):
        """回滚事务"""
        self.get_connection().rollback()

    def init_database(self):
        conn = self.get_connection()
        c = conn.cursor()
        
        # 创建股票配置表
        c.execute('''
        CREATE TABLE IF NOT EXISTS stock_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL UNIQUE,
            stock_name TEXT,
            is_active INTEGER DEFAULT 1,
            alert_enabled INTEGER DEFAULT 0,
            alert_upper_threshold REAL DEFAULT 0,
            alert_lower_threshold REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 创建股票数据表
        c.execute('''
        CREATE TABLE IF NOT EXISTS stock_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            turnover REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, trade_date)
        )
        ''')

        # 创建报警历史表
        c.execute('''
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            alert_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 创建股票表
        c.execute('''
        CREATE TABLE IF NOT EXISTS stocks (
            code TEXT PRIMARY KEY,
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 创建用户表
        c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            settings TEXT
        )
        ''')
        
        conn.commit()
        conn.close()

    def create_user(self, username: str, password: str, email: str = None) -> bool:
        """创建新用户"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            hashed_password = generate_password_hash(password)
            print(len((username, hashed_password, email)))  # 应该是3
            # 对密码进行哈希处理
            if isinstance(hashed_password, bytes):
                hashed_password = hashed_password.decode('utf-8')
            print(len(hashed_password))
            print(f"Username: {username}, Hashed Password: {hashed_password}, Email: {email}")
            cursor.execute(
                'INSERT INTO users (username, password, email) VALUES (%s,%s, %s)',
                (username, hashed_password, email)
            )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"创建用户失败: {str(e)}")
            return False

    def verify_user(self, username: str, password: str) -> dict:
        """验证用户登录"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT id, username, password, settings FROM users WHERE username = %s', (username,))
            user = cursor.fetchone()
            
            if user and check_password_hash(user[2], password):
                # 更新最后登录时间
                cursor.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s', (user[0],))
                conn.commit()
                
                return {
                    'success': True,
                    'user_id': user[0],
                    'username': user[1],
                    'settings': user[3]
                }
            
            return {'success': False, 'message': '用户名或密码错误'}
        except Exception as e:
            logger.error(f"验证用户失败: {str(e)}")
            return {'success': False, 'message': '登录失败'}
        finally:
            conn.close()

    def update_user_settings(self, user_id: int, settings: dict) -> bool:
        """更新用户设置"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # 将设置转换为JSON字符串
            settings_json = json.dumps(settings)
            
            cursor.execute(
                'UPDATE users SET settings = ? WHERE id = ?',
                (settings_json, user_id)
            )
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"更新用户设置失败: {str(e)}")
            return False

    def get_user_settings(self, user_id: int) -> dict:
        """获取用户设置"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT settings FROM users WHERE id = %s', (user_id,))
            result = cursor.fetchone()
            
            if result and result[0]:
                return json.loads(result[0])
            return {}
        except Exception as e:
            logger.error(f"获取用户设置失败: {str(e)}")
            return {}
        finally:
            conn.close() 