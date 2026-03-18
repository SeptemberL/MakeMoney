import os
import sqlite3
import logging
import json
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

try:
    import mysql.connector
    from mysql.connector.pooling import MySQLConnectionPool
    _HAS_MYSQL = True
except ImportError:
    _HAS_MYSQL = False

logger = logging.getLogger(__name__)

_USE_POOL_TYPES = ('mysql', 'mariadb')
_SQLITE_TYPES = ('sqlite', 'sqlite3')
_connection_pool = None


def _get_pool():
    """懒加载创建 MySQL 连接池，复用连接避免频繁建连导致卡顿"""
    global _connection_pool
    if _connection_pool is None:
        if not _HAS_MYSQL:
            raise ImportError(
                "mysql-connector-python 未安装，请 pip install mysql-connector-python 或切换 DB_TYPE=sqlite"
            )
        cfg = Config()
        _connection_pool = MySQLConnectionPool(
            pool_name="stock_pool",
            pool_size=10,
            host=cfg.get('DATABASE', 'DB_HOST'),
            port=cfg.get_int('DATABASE', 'DB_PORT'),
            database=cfg.get('DATABASE', 'DB_NAME'),
            user=cfg.get('DATABASE', 'DB_USER'),
            password=cfg.get('DATABASE', 'DB_PASSWORD'),
            charset='utf8mb4',
        )
        logger.info("MySQL 连接池已创建 (pool_size=10)")
    return _connection_pool


def _sqlite_dict_factory(cursor, row):
    """SQLite row_factory：让 fetchone/fetchall 返回 dict"""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


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
        self._db_type = (self.config.get('DATABASE', 'DB_TYPE') or 'mysql').lower()

    # ─────────────────────────── 类型判断 ────────────────────────────────────

    @property
    def is_sqlite(self) -> bool:
        return self._db_type in _SQLITE_TYPES

    @property
    def db_type(self) -> str:
        return self._db_type

    def adapt_sql(self, query: str) -> str:
        """将业务代码中统一使用的 MySQL 风格 SQL 适配为当前数据库方言。
        业务层统一写 %s 占位符 + INSERT IGNORE，此方法在 SQLite 时自动转换。"""
        if not self.is_sqlite:
            return query
        query = query.replace('%s', '?')
        query = query.replace('INSERT IGNORE', 'INSERT OR IGNORE')
        return query

    def table_exists(self, table_name: str) -> bool:
        """判断表是否存在。MySQL 用 information_schema，SQLite 用 sqlite_master。"""
        if self.is_sqlite:
            r = self.fetch_one(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            return r is not None
        r = self.fetch_one(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
            (table_name,)
        )
        return r is not None

    # ─────────────────────────── 连接管理 ────────────────────────────────────

    def connect(self):
        """连接到数据库（MySQL 从连接池取连接；SQLite 直连文件）"""
        try:
            if self.is_sqlite:
                if self._connection is not None:
                    return True
                db_path = self.config.get('DATABASE', 'DB_PATH') or 'database/stock.db'
                if not os.path.isabs(db_path):
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    db_path = os.path.join(project_root, db_path)
                os.makedirs(os.path.dirname(db_path), exist_ok=True)
                self._connection = sqlite3.connect(db_path, check_same_thread=False)
                self._connection.row_factory = _sqlite_dict_factory
                self._connection.execute('PRAGMA journal_mode=WAL')
                self._connection.execute('PRAGMA foreign_keys=ON')
                logger.info(f"SQLite 已连接: {db_path}")
                return True
            else:
                if not _HAS_MYSQL:
                    raise ImportError(
                        "mysql-connector-python 未安装，请 pip install mysql-connector-python 或切换 DB_TYPE=sqlite"
                    )
                if self._connection and self._connection.is_connected():
                    return True
                if self._db_type in _USE_POOL_TYPES:
                    self._connection = _get_pool().get_connection()
                else:
                    self._connection = mysql.connector.connect(
                        host=self.config.get('DATABASE', 'DB_HOST'),
                        port=self.config.get_int('DATABASE', 'DB_PORT'),
                        database=self.config.get('DATABASE', 'DB_NAME'),
                        user=self.config.get('DATABASE', 'DB_USER'),
                        password=self.config.get('DATABASE', 'DB_PASSWORD'),
                        charset='utf8mb4',
                        buffered=True,
                    )
                return True
        except Exception as e:
            logger.error(f"数据库连接失败: {str(e)}")
            return False

    def get_connection(self):
        """获取数据库连接"""
        if self.is_sqlite:
            if self._connection is None:
                self.connect()
            if self._connection is None:
                raise RuntimeError("SQLite 连接失败，请检查 DB_PATH 配置")
        else:
            if not self._connection or (
                self._db_type in _USE_POOL_TYPES
                and not self._connection.is_connected()
            ):
                self.connect()
            if self._connection is None:
                raise RuntimeError("数据库连接失败，请检查配置与 MySQL 服务是否正常")
        return self._connection

    def close(self):
        """关闭数据库连接（MySQL 时归还到连接池）"""
        if self._connection:
            try:
                if self.is_sqlite:
                    self._connection.close()
                elif self._db_type in _USE_POOL_TYPES and self._connection.is_connected():
                    self._connection.close()
                elif self._db_type not in _USE_POOL_TYPES:
                    self._connection.close()
            except Exception:
                pass
            self._connection = None

    # ─────────────────────────── SQL 执行 ────────────────────────────────────

    def execute(self, query, params=None):
        """执行SQL查询"""
        cursor = None
        conn = None
        try:
            conn = self.get_connection()
            query = self.adapt_sql(query)
            if self.is_sqlite:
                cursor = conn.cursor()
            else:
                cursor = conn.cursor(dictionary=True, buffered=True)

            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            conn.commit()
            return cursor
        except Exception as e:
            logger.error(f"执行SQL查询失败: {str(e)}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise

    def fetch_all(self, query, params=None):
        """执行查询并返回所有结果"""
        cursor = None
        try:
            cursor = self.execute(query, params)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"执行查询失败: {str(e)}")
            raise
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass

    def fetch_one(self, query, params=None):
        """执行查询并返回一个结果"""
        cursor = None
        try:
            cursor = self.execute(query, params)
            return cursor.fetchone()
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass

    def begin_transaction(self):
        """开始事务"""
        if self.is_sqlite:
            self.get_connection().execute('BEGIN')
        else:
            self.get_connection().start_transaction()

    def commit(self):
        """提交事务"""
        self.get_connection().commit()

    def rollback(self):
        """回滚事务"""
        self.get_connection().rollback()

    # ─────────────────────────── 建表 ────────────────────────────────────────

    def init_database(self):
        if self.is_sqlite:
            self._init_database_sqlite()
        else:
            self._init_database_mysql()

    def _init_database_sqlite(self):
        self.execute('''CREATE TABLE IF NOT EXISTS stock_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL UNIQUE,
            stock_name TEXT,
            is_active INTEGER DEFAULT 1,
            alert_enabled INTEGER DEFAULT 0,
            alert_upper_threshold REAL DEFAULT 0,
            alert_lower_threshold REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        self.execute('''CREATE TABLE IF NOT EXISTS stock_basic (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT,
            exchange TEXT,
            list_date TEXT,
            industry TEXT,
            area TEXT,
            status INTEGER DEFAULT 1,
            source TEXT DEFAULT 'akshare',
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        try:
            self.execute("CREATE INDEX IF NOT EXISTS idx_stock_basic_market ON stock_basic (market)")
        except Exception:
            pass
        self.execute('''CREATE TABLE IF NOT EXISTS stock_data (
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
        )''')
        self.execute('''CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            alert_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        self.execute('''CREATE TABLE IF NOT EXISTS stocks (
            code TEXT PRIMARY KEY,
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        self.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            settings TEXT
        )''')
        # 仓位相关表
        self.execute('''CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            quantity REAL NOT NULL,
            cost_price REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        self.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            action TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL,
            fee REAL DEFAULT 0,
            trade_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        self.execute('''CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_capital REAL DEFAULT 0,
            available_cash REAL DEFAULT 0,
            market_value REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        self._create_message_group_tables_sqlite()

    def _create_message_group_tables_sqlite(self):
        """聊天群列表表（SQLite）"""
        self.execute('''CREATE TABLE IF NOT EXISTS message_group (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            list_type VARCHAR(32) NOT NULL DEFAULT 'weixin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(list_type, group_id)
        )''')
        self.execute('''CREATE TABLE IF NOT EXISTS message_group_chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            chat_name VARCHAR(256) NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES message_group(id) ON DELETE CASCADE
        )''')

    def _init_database_mysql(self):
        self.execute('''CREATE TABLE IF NOT EXISTS stock_config (
            id INT AUTO_INCREMENT PRIMARY KEY,
            stock_code VARCHAR(32) NOT NULL UNIQUE,
            stock_name VARCHAR(128),
            is_active TINYINT DEFAULT 1,
            alert_enabled TINYINT DEFAULT 0,
            alert_upper_threshold DOUBLE DEFAULT 0,
            alert_lower_threshold DOUBLE DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS stock_basic (
            code VARCHAR(32) PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            market VARCHAR(16) DEFAULT NULL,
            exchange VARCHAR(16) DEFAULT NULL,
            list_date VARCHAR(16) DEFAULT NULL,
            industry VARCHAR(128) DEFAULT NULL,
            area VARCHAR(64) DEFAULT NULL,
            status TINYINT DEFAULT 1,
            source VARCHAR(32) DEFAULT 'akshare',
            raw_json JSON DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_stock_basic_market (market)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS stock_data (
            id INT AUTO_INCREMENT PRIMARY KEY,
            stock_code VARCHAR(32) NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            turnover DOUBLE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_code_date (stock_code, trade_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS alert_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            stock_code VARCHAR(32) NOT NULL,
            alert_type VARCHAR(64) NOT NULL,
            alert_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS stocks (
            code VARCHAR(32) PRIMARY KEY,
            name VARCHAR(128),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(64) UNIQUE NOT NULL,
            password VARCHAR(256) NOT NULL,
            email VARCHAR(128) UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP NULL,
            settings TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        # 仓位相关表
        self.execute('''CREATE TABLE IF NOT EXISTS positions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            stock_code VARCHAR(32) NOT NULL,
            stock_name VARCHAR(128),
            quantity DOUBLE NOT NULL,
            cost_price DOUBLE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            stock_code VARCHAR(32) NOT NULL,
            action VARCHAR(8) NOT NULL,
            price DOUBLE NOT NULL,
            quantity DOUBLE NOT NULL,
            fee DOUBLE DEFAULT 0,
            trade_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS portfolio (
            id INT AUTO_INCREMENT PRIMARY KEY,
            total_capital DOUBLE DEFAULT 0,
            available_cash DOUBLE DEFAULT 0,
            market_value DOUBLE DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self._create_message_group_tables_mysql()

    def _create_message_group_tables_mysql(self):
        """聊天群列表表（MySQL）"""
        self.execute('''CREATE TABLE IF NOT EXISTS message_group (
            id INT AUTO_INCREMENT PRIMARY KEY,
            group_id INT NOT NULL,
            list_type VARCHAR(32) NOT NULL DEFAULT 'weixin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_type_group (list_type, group_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS message_group_chat (
            id INT AUTO_INCREMENT PRIMARY KEY,
            group_id INT NOT NULL,
            chat_name VARCHAR(256) NOT NULL,
            sort_order INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            KEY idx_group_id (group_id),
            FOREIGN KEY (group_id) REFERENCES message_group(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    # ─────────────────────────── 聊天群列表 ────────────────────────────────────

    def ensure_message_group_tables(self):
        """确保 message_group 相关表存在（不依赖 init_database）"""
        if self.is_sqlite:
            self._create_message_group_tables_sqlite()
        else:
            self._create_message_group_tables_mysql()

    def get_all_message_groups(self, list_type=None):
        """获取所有群组；list_type 为 None 时返回所有类型。返回 [{id, group_id, list_type, chat_list: [str]}, ...]"""
        self.ensure_message_group_tables()
        if list_type is not None:
            rows = self.fetch_all(
                'SELECT id, group_id, list_type FROM message_group WHERE list_type = %s ORDER BY list_type, group_id',
                (list_type,)
            )
        else:
            rows = self.fetch_all(
                'SELECT id, group_id, list_type FROM message_group ORDER BY list_type, group_id'
            )
        out = []
        for r in rows:
            chats = self.fetch_all(
                'SELECT chat_name FROM message_group_chat WHERE group_id = %s ORDER BY sort_order, id',
                (r['id'],)
            )
            out.append({
                'id': r['id'],
                'group_id': r['group_id'],
                'list_type': r['list_type'] or 'weixin',
                'chat_list': [c['chat_name'] for c in chats],
            })
        return out

    def get_message_group_by_id(self, pk_id):
        """根据主键 id 获取一个群组（含 chat_list）"""
        self.ensure_message_group_tables()
        r = self.fetch_one('SELECT id, group_id, list_type FROM message_group WHERE id = %s', (pk_id,))
        if not r:
            return None
        chats = self.fetch_all(
            'SELECT chat_name FROM message_group_chat WHERE group_id = %s ORDER BY sort_order, id',
            (r['id'],)
        )
        return {
            'id': r['id'],
            'group_id': r['group_id'],
            'list_type': r['list_type'] or 'weixin',
            'chat_list': [c['chat_name'] for c in chats],
        }

    def create_message_group(self, group_id, list_type='weixin', chat_list=None):
        """创建群组并写入 chat_list。返回 (True, id) 或 (False, error_msg)。"""
        self.ensure_message_group_tables()
        chat_list = chat_list or []
        try:
            self.execute(
                'INSERT INTO message_group (group_id, list_type) VALUES (%s, %s)',
                (group_id, (list_type or 'weixin'))
            )
            if self.is_sqlite:
                row = self.fetch_one('SELECT last_insert_rowid() AS id')
                pk = row['id']
            else:
                row = self.fetch_one('SELECT LAST_INSERT_ID() AS id')
                pk = row['id']
            for i, name in enumerate(chat_list):
                self.execute(
                    'INSERT INTO message_group_chat (group_id, chat_name, sort_order) VALUES (%s, %s, %s)',
                    (pk, (name or '').strip(), i)
                )
            return (True, pk)
        except Exception as e:
            logger.error(f"创建 message_group 失败: {str(e)}")
            if 'UNIQUE' in str(e) or 'Duplicate' in str(e):
                return (False, '该类型下 group_id 已存在')
            return (False, str(e))

    def update_message_group(self, pk_id, group_id=None, list_type=None, chat_list=None):
        """更新群组。chat_list 若提供则整体替换。返回 (True, None) 或 (False, error_msg)。"""
        self.ensure_message_group_tables()
        try:
            if group_id is not None:
                self.execute(
                    'UPDATE message_group SET group_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (group_id, pk_id)
                )
            if list_type is not None:
                self.execute(
                    'UPDATE message_group SET list_type = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (list_type, pk_id)
                )
            if chat_list is not None:
                self.execute('DELETE FROM message_group_chat WHERE group_id = %s', (pk_id,))
                for i, name in enumerate(chat_list):
                    self.execute(
                        'INSERT INTO message_group_chat (group_id, chat_name, sort_order) VALUES (%s, %s, %s)',
                        (pk_id, (name or '').strip(), i)
                    )
            return (True, None)
        except Exception as e:
            logger.error(f"更新 message_group 失败: {str(e)}")
            return (False, str(e))

    def delete_message_group(self, pk_id):
        """删除群组（级联删除 chat）。返回 True/False。"""
        self.ensure_message_group_tables()
        try:
            self.execute('DELETE FROM message_group WHERE id = %s', (pk_id,))
            return True
        except Exception as e:
            logger.error(f"删除 message_group 失败: {str(e)}")
            return False

    # ─────────────────────────── 用户管理 ────────────────────────────────────

    def create_user(self, username: str, password: str, email: str = None):
        """创建新用户。成功返回 (True, None)，用户名/邮箱已存在返回 (False, 'duplicate')，其他失败返回 (False, 'error')。"""
        try:
            hashed_password = generate_password_hash(password)
            if isinstance(hashed_password, bytes):
                hashed_password = hashed_password.decode('utf-8')
            self.execute(
                'INSERT INTO users (username, password, email) VALUES (%s, %s, %s)',
                (username, hashed_password, email or None)
            )
            return (True, None)
        except Exception as e:
            # 唯一约束冲突（用户名或邮箱已存在）
            err_name = type(e).__name__
            if err_name == 'IntegrityError' or 'Duplicate' in str(e) or 'UNIQUE' in str(e).upper():
                logger.info(f"注册拒绝：用户名或邮箱已存在 - {username}")
                return (False, 'duplicate')
            logger.error(f"创建用户失败: {str(e)}")
            return (False, 'error')
        finally:
            self.close()

    def verify_user(self, username: str, password: str) -> dict:
        """验证用户登录"""
        try:
            row = self.fetch_one(
                'SELECT id, username, password, settings FROM users WHERE username = %s',
                (username,)
            )
            if row and check_password_hash(row['password'], password):
                self.execute(
                    'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s',
                    (row['id'],)
                )
                return {
                    'success': True,
                    'user_id': row['id'],
                    'username': row['username'],
                    'settings': row['settings']
                }
            return {'success': False, 'message': '用户名或密码错误'}
        except Exception as e:
            logger.error(f"验证用户失败: {str(e)}")
            return {'success': False, 'message': '登录失败'}
        finally:
            self.close()

    def update_user_settings(self, user_id: int, settings: dict) -> bool:
        """更新用户设置"""
        try:
            settings_json = json.dumps(settings)
            self.execute(
                'UPDATE users SET settings = %s WHERE id = %s',
                (settings_json, user_id)
            )
            return True
        except Exception as e:
            logger.error(f"更新用户设置失败: {str(e)}")
            return False

    def get_user_settings(self, user_id: int) -> dict:
        """获取用户设置"""
        try:
            row = self.fetch_one('SELECT settings FROM users WHERE id = %s', (user_id,))
            if row and row.get('settings'):
                return json.loads(row['settings'])
            return {}
        except Exception as e:
            logger.error(f"获取用户设置失败: {str(e)}")
            return {}
        finally:
            self.close()
