import os
import sqlite3
import logging
import json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from Managers.redis_kv import get_json as _redis_get_json, set_json as _redis_set_json, make_key as _redis_key
from Managers.runtime_settings import get_setting as _rt_get_setting

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

    def column_exists(self, table_name: str, column_name: str) -> bool:
        """判断表中是否已有某列（用于迁移）。"""
        try:
            if self.is_sqlite:
                rows = self.fetch_all(f'PRAGMA table_info({table_name})')
                for r in rows or []:
                    if isinstance(r, dict) and r.get('name') == column_name:
                        return True
                return False
            r = self.fetch_one(
                "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = %s AND COLUMN_NAME = %s LIMIT 1",
                (table_name, column_name),
            )
            return r is not None
        except Exception:
            return False

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
        self.ensure_etf_basic_tables()
        self.ensure_adj_factor_tables()
        self.ensure_nga_auto_summary_task_tables()
        self.ensure_nga_author_daily_summary_cache_tables()
        self.migrate_positions_transactions_portfolio_user_id()
        self.migrate_investment_calendar_item_remind_columns()
        self.ensure_investment_calendar_reminder_log_tables()

    # ─────────────────────────── 场内 ETF 基础信息（MySQL/SQLite 双引擎一致） ────────────────────────────

    def _create_etf_basic_tables_sqlite(self):
        """场内 ETF 基金基础信息表（SQLite）。仅存基本信息，用于持仓录入/展示。"""
        self.execute('''CREATE TABLE IF NOT EXISTS etf_basic (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT,
            exchange TEXT,
            list_date TEXT,
            source TEXT DEFAULT 'manual',
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        try:
            self.execute("CREATE INDEX IF NOT EXISTS idx_etf_basic_market ON etf_basic (market)")
        except Exception:
            pass

    def _create_etf_basic_tables_mysql(self):
        """场内 ETF 基金基础信息表（MySQL）。与 SQLite 语义一致。"""
        self.execute('''CREATE TABLE IF NOT EXISTS etf_basic (
            code VARCHAR(32) PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            market VARCHAR(16) DEFAULT NULL,
            exchange VARCHAR(16) DEFAULT NULL,
            list_date VARCHAR(16) DEFAULT NULL,
            source VARCHAR(32) DEFAULT 'manual',
            raw_json JSON DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_etf_basic_market (market)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    def ensure_etf_basic_tables(self):
        """确保 etf_basic 表存在（不依赖 init_database）。"""
        if self.is_sqlite:
            self._create_etf_basic_tables_sqlite()
        else:
            self._create_etf_basic_tables_mysql()

    def get_etf_basic_by_code(self, code: str):
        """按 code 查询 ETF 基础信息（不存在返回 None）。"""
        self.ensure_etf_basic_tables()
        c = (code or "").strip()
        if not c:
            return None
        return self.fetch_one(
            "SELECT code, name, market, exchange, list_date, source FROM etf_basic WHERE code=%s LIMIT 1",
            (c,),
        )

    def upsert_etf_basic(
        self,
        *,
        code: str,
        name: str,
        market: str | None = None,
        exchange: str | None = None,
        list_date: str | None = None,
        source: str | None = None,
        raw_json: str | None = None,
    ) -> bool:
        """写入或更新 ETF 基础信息（幂等）。"""
        self.ensure_etf_basic_tables()
        c = (code or "").strip()
        n = (name or "").strip()
        if not c or not n:
            raise ValueError("etf_basic.code/name 不能为空")
        src = (source or "manual").strip() or "manual"
        if self.is_sqlite:
            self.execute(
                '''INSERT INTO etf_basic (code, name, market, exchange, list_date, source, raw_json, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT(code) DO UPDATE SET
                       name=excluded.name,
                       market=excluded.market,
                       exchange=excluded.exchange,
                       list_date=excluded.list_date,
                       source=excluded.source,
                       raw_json=excluded.raw_json,
                       updated_at=CURRENT_TIMESTAMP''',
                (c, n, market, exchange, list_date, src, raw_json),
            )
        else:
            self.execute(
                '''INSERT INTO etf_basic (code, name, market, exchange, list_date, source, raw_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                       name=VALUES(name),
                       market=VALUES(market),
                       exchange=VALUES(exchange),
                       list_date=VALUES(list_date),
                       source=VALUES(source),
                       raw_json=VALUES(raw_json),
                       updated_at=CURRENT_TIMESTAMP''',
                (c, n, market, exchange, list_date, src, raw_json),
            )
        return True

    def migrate_positions_transactions_portfolio_user_id(self):
        """旧库为持仓/流水/组合表增加 user_id，历史数据归到首个用户（或默认 1）。"""
        try:
            row = self.fetch_one('SELECT MIN(id) AS id FROM users')
            fallback = int(row['id']) if row and row.get('id') is not None else 1
        except Exception:
            fallback = 1
        for tname in ('positions', 'transactions', 'portfolio'):
            try:
                if not self.table_exists(tname):
                    continue
                if self.column_exists(tname, 'user_id'):
                    continue
                if self.is_sqlite:
                    self.execute(
                        f'ALTER TABLE {tname} ADD COLUMN user_id INTEGER NOT NULL DEFAULT {int(fallback)}'
                    )
                else:
                    self.execute(
                        f'ALTER TABLE {tname} ADD COLUMN user_id INT NOT NULL DEFAULT {int(fallback)}'
                    )
            except Exception as e:
                logger.warning('迁移表 %s 增加 user_id 失败: %s', tname, e)

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
        self._create_adj_factor_tables_sqlite()
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
        self.ensure_investment_calendar_tables()
        # 仓位相关表（按 user_id 隔离，仅当前登录用户可见）
        self.execute('''CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            quantity REAL NOT NULL,
            cost_price REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, stock_code)
        )''')
        self.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            action TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL,
            fee REAL DEFAULT 0,
            trade_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )''')
        self.execute('''CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total_capital REAL DEFAULT 0,
            available_cash REAL DEFAULT 0,
            market_value REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )''')
        self._create_message_group_tables_sqlite()
        self._create_signal_rule_tables_sqlite()
        self._create_signal_rule_state_tables_sqlite()
        self._create_user_watchlist_tables_sqlite()
        self._create_scheduled_task_tables_sqlite()
        self._create_system_settings_tables_sqlite()

    def _create_scheduled_task_tables_sqlite(self):
        """APScheduler 业务任务配置（SQLite），与 MySQL 语义一致。"""
        self.execute('''CREATE TABLE IF NOT EXISTS scheduled_task (
            task_id TEXT PRIMARY KEY,
            task_name TEXT NOT NULL,
            module_path TEXT NOT NULL,
            function_name TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_args TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            run_once_per_day INTEGER NOT NULL DEFAULT 0,
            max_instances INTEGER NOT NULL DEFAULT 1,
            misfire_grace_time INTEGER,
            job_coalesce INTEGER NOT NULL DEFAULT 1,
            description TEXT,
            args_json TEXT,
            kwargs_json TEXT
        )''')

    def _create_user_watchlist_tables_sqlite(self):
        """用户自选列表（SQLite），按账号跨设备同步"""
        self.execute('''CREATE TABLE IF NOT EXISTS user_watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, stock_code)
        )''')
        try:
            self.execute('CREATE INDEX IF NOT EXISTS idx_user_watchlist_user ON user_watchlist (user_id)')
        except Exception:
            pass

    def _create_message_group_tables_sqlite(self):
        """聊天群列表表（SQLite）"""
        self.execute('''CREATE TABLE IF NOT EXISTS message_group (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            list_type VARCHAR(32) NOT NULL DEFAULT 'weixin',
            name VARCHAR(128) DEFAULT NULL,
            send_mode VARCHAR(32) NOT NULL DEFAULT '',
            chat_id VARCHAR(128) DEFAULT NULL,
            webhook_url TEXT DEFAULT NULL,
            sign_secret TEXT DEFAULT NULL,
            app_id VARCHAR(128) DEFAULT NULL,
            app_secret TEXT DEFAULT NULL,
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
        self._create_adj_factor_tables_mysql()
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
        self.ensure_investment_calendar_tables()
        # 仓位相关表（按 user_id 隔离）
        self.execute('''CREATE TABLE IF NOT EXISTS positions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            stock_code VARCHAR(32) NOT NULL,
            stock_name VARCHAR(128),
            quantity DOUBLE NOT NULL,
            cost_price DOUBLE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_positions_user_stock (user_id, stock_code),
            KEY idx_positions_user (user_id),
            CONSTRAINT fk_positions_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            stock_code VARCHAR(32) NOT NULL,
            action VARCHAR(8) NOT NULL,
            price DOUBLE NOT NULL,
            quantity DOUBLE NOT NULL,
            fee DOUBLE DEFAULT 0,
            trade_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            KEY idx_transactions_user (user_id),
            CONSTRAINT fk_transactions_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self.execute('''CREATE TABLE IF NOT EXISTS portfolio (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            total_capital DOUBLE DEFAULT 0,
            available_cash DOUBLE DEFAULT 0,
            market_value DOUBLE DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_portfolio_user (user_id),
            CONSTRAINT fk_portfolio_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        self._create_message_group_tables_mysql()
        self._create_signal_rule_tables_mysql()
        self._create_signal_rule_state_tables_mysql()
        self._create_user_watchlist_tables_mysql()
        self._create_scheduled_task_tables_mysql()
        self._create_system_settings_tables_mysql()

    # ─────────────────────────── 系统设置（DB 优先） ────────────────────────────

    def _create_system_settings_tables_sqlite(self):
        """系统设置键值表（SQLite），用于 settings_console 等页面持久化配置。"""
        self.execute('''CREATE TABLE IF NOT EXISTS system_settings (
            section TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (section, key)
        )''')

    def _create_system_settings_tables_mysql(self):
        """系统设置键值表（MySQL），与 SQLite 语义一致。"""
        self.execute('''CREATE TABLE IF NOT EXISTS system_settings (
            section VARCHAR(64) NOT NULL,
            `key` VARCHAR(128) NOT NULL,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (section, `key`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    # ─────────────────────────── 复权因子（MySQL/SQLite 双引擎一致） ────────────────────────────

    def _create_adj_factor_tables_sqlite(self):
        """复权因子表（SQLite）。按交易日存前复权/后复权因子（尽量每天有值）。"""
        self.execute('''CREATE TABLE IF NOT EXISTS adj_factor (
            stock_code TEXT NOT NULL,
            trade_date DATE NOT NULL,
            -- 兼容字段：历史上 adj_factor 表示前复权因子（qfq_factor）
            adj_factor REAL,
            qfq_factor REAL,
            hfq_factor REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (stock_code, trade_date)
        )''')
        try:
            self.execute("CREATE INDEX IF NOT EXISTS idx_adj_factor_code_date ON adj_factor (stock_code, trade_date)")
        except Exception:
            pass

    def _create_adj_factor_tables_mysql(self):
        """复权因子表（MySQL）。与 SQLite 语义一致。"""
        self.execute('''CREATE TABLE IF NOT EXISTS adj_factor (
            stock_code VARCHAR(32) NOT NULL,
            trade_date DATE NOT NULL,
            -- 兼容字段：历史上 adj_factor 表示前复权因子（qfq_factor）
            adj_factor DOUBLE NULL,
            qfq_factor DOUBLE NULL,
            hfq_factor DOUBLE NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (stock_code, trade_date),
            KEY idx_adj_factor_code_date (stock_code, trade_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    def ensure_adj_factor_tables(self):
        """确保 adj_factor 表存在（不依赖 init_database）。"""
        if self.is_sqlite:
            self._create_adj_factor_tables_sqlite()
        else:
            self._create_adj_factor_tables_mysql()
        self._migrate_adj_factor_schema()

    def _migrate_adj_factor_schema(self):
        """
        复权因子表迁移：
        - 新增 qfq_factor / hfq_factor
        - 将历史 adj_factor 回填到 qfq_factor（若为空）
        """
        try:
            if not self.column_exists("adj_factor", "qfq_factor"):
                if self.is_sqlite:
                    self.execute("ALTER TABLE adj_factor ADD COLUMN qfq_factor REAL")
                else:
                    self.execute("ALTER TABLE adj_factor ADD COLUMN qfq_factor DOUBLE NULL")
            if not self.column_exists("adj_factor", "hfq_factor"):
                if self.is_sqlite:
                    self.execute("ALTER TABLE adj_factor ADD COLUMN hfq_factor REAL")
                else:
                    self.execute("ALTER TABLE adj_factor ADD COLUMN hfq_factor DOUBLE NULL")
        except Exception:
            # 迁移尽力而为，不阻断主流程
            pass

        # 回填：qfq_factor 为空时用 adj_factor
        try:
            if self.column_exists("adj_factor", "adj_factor") and self.column_exists("adj_factor", "qfq_factor"):
                if self.is_sqlite:
                    self.execute(
                        "UPDATE adj_factor SET qfq_factor = adj_factor "
                        "WHERE qfq_factor IS NULL AND adj_factor IS NOT NULL"
                    )
                else:
                    self.execute(
                        "UPDATE adj_factor SET qfq_factor = adj_factor "
                        "WHERE qfq_factor IS NULL AND adj_factor IS NOT NULL"
                    )
        except Exception:
            pass

    def get_latest_adj_factor_row(self, stock_code: str):
        """返回某股票最新一条复权因子行：{trade_date, qfq_factor, hfq_factor, adj_factor}，不存在返回 None。"""
        self.ensure_adj_factor_tables()
        sc = (stock_code or "").strip()
        if not sc:
            return None
        return self.fetch_one(
            "SELECT trade_date, adj_factor, qfq_factor, hfq_factor "
            "FROM adj_factor WHERE stock_code = %s ORDER BY trade_date DESC LIMIT 1",
            (sc,),
        )

    def upsert_adj_factor(
        self,
        stock_code: str,
        trade_date: str,
        adj_factor: float,
        qfq_factor: float | None = None,
        hfq_factor: float | None = None,
    ) -> bool:
        """幂等写入一条复权因子（同一股票同一交易日覆盖更新）。"""
        self.ensure_adj_factor_tables()
        sc = (stock_code or "").strip()
        td = (trade_date or "").strip()
        if not sc or not td:
            raise ValueError("stock_code/trade_date 不能为空")
        # 兼容：若只传了 adj_factor，则视为 qfq_factor
        af = float(adj_factor) if adj_factor is not None else None
        qfq = float(qfq_factor) if qfq_factor is not None else (float(af) if af is not None else None)
        hfq = float(hfq_factor) if hfq_factor is not None else None
        if self.is_sqlite:
            self.execute(
                '''INSERT INTO adj_factor (stock_code, trade_date, adj_factor, qfq_factor, hfq_factor, updated_at)
                   VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                       adj_factor=excluded.adj_factor,
                       qfq_factor=excluded.qfq_factor,
                       hfq_factor=excluded.hfq_factor,
                       updated_at=CURRENT_TIMESTAMP''',
                (sc, td, qfq, qfq, hfq),
            )
        else:
            self.execute(
                '''INSERT INTO adj_factor (stock_code, trade_date, adj_factor, qfq_factor, hfq_factor)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                       adj_factor=VALUES(adj_factor),
                       qfq_factor=VALUES(qfq_factor),
                       hfq_factor=VALUES(hfq_factor),
                       updated_at=CURRENT_TIMESTAMP''',
                (sc, td, qfq, qfq, hfq),
            )
        return True

    def get_max_adj_factor_trade_date(self, stock_code: str):
        """返回某股票 adj_factor 表中最大的 trade_date（字符串），无数据返回 None。"""
        self.ensure_adj_factor_tables()
        sc = (stock_code or "").strip()
        if not sc:
            return None
        row = self.fetch_one(
            "SELECT MAX(trade_date) AS d FROM adj_factor WHERE stock_code = %s",
            (sc,),
        )
        if not row:
            return None
        v = row.get("d")
        if v is None:
            return None
        # MySQL 可能返回 date/datetime；SQLite 多为 str
        try:
            return str(v)[:10]
        except Exception:
            return None

    def get_adj_factors(
        self,
        *,
        stock_codes: list[str],
        start_trade_date: str,
        end_trade_date: str,
    ) -> list[dict]:
        """
        批量读取 adj_factor 区间数据。

        Returns:
            rows: [{stock_code, trade_date, adj_factor}, ...]
        """
        self.ensure_adj_factor_tables()
        codes = [str(c).strip() for c in (stock_codes or []) if str(c).strip()]
        if not codes:
            return []
        start_td = str(start_trade_date or "").strip()
        end_td = str(end_trade_date or "").strip()
        if not start_td or not end_td:
            raise ValueError("start_trade_date/end_trade_date 不能为空")

        select_cols = "stock_code, trade_date, adj_factor, qfq_factor, hfq_factor"

        if self.is_sqlite:
            placeholders = ",".join(["?"] * len(codes))
            sql = (
                f"SELECT {select_cols} FROM adj_factor "
                f"WHERE stock_code IN ({placeholders}) AND trade_date BETWEEN ? AND ?"
            )
            params = tuple(codes + [start_td, end_td])
            return self.fetch_all(sql, params) or []

        placeholders = ",".join(["%s"] * len(codes))
        sql = (
            f"SELECT {select_cols} FROM adj_factor "
            f"WHERE stock_code IN ({placeholders}) AND trade_date BETWEEN %s AND %s"
        )
        params = tuple(codes + [start_td, end_td])
        return self.fetch_all(sql, params) or []

    @staticmethod
    def stock_table_name_for_code(code: str) -> str:
        """
        与 StockListManager._get_stock_table_name 保持一致：
        - 6/9 开头视为 SH，否则 SZ
        - 表名格式：stock_{code}_{SH|SZ}
        """
        c = str(code or "").strip()
        if "." in c:
            c = c.split(".", 1)[0].strip()
        if not c:
            raise ValueError("code 不能为空")
        market = "SH" if c.startswith(("6", "9")) else "SZ"
        return f"stock_{c}_{market}"

    def get_latest_daily_close_map(self, stock_codes: list[str]) -> dict[str, dict]:
        """
        批量读取每只股票“最新交易日”的 raw close。

        Returns:
            {stock_code: {"trade_date": "YYYY-MM-DD", "close": float}}
        """
        out: dict[str, dict] = {}
        codes = [str(c).strip() for c in (stock_codes or []) if str(c).strip()]
        if not codes:
            return out

        # Redis 缓存（可开关）：适用于信号扫描等“频繁读、短 TTL”的场景
        try:
            ttl_raw = _rt_get_setting("REDIS", "latest_close_ttl_seconds", "0")
            ttl = int(float(ttl_raw)) if ttl_raw is not None else 0
        except Exception:
            ttl = 0
        cache_key = None
        if ttl > 0:
            try:
                cache_key = _redis_key(
                    "cache",
                    "latest_daily_close_map",
                    self.db_type,
                    ",".join(sorted(codes)),
                )
                cached = _redis_get_json(cache_key)
                if isinstance(cached, dict) and cached:
                    return cached
            except Exception:
                cache_key = None

        for sc in codes:
            try:
                table = self.stock_table_name_for_code(sc)
            except Exception:
                continue
            if not self.table_exists(table):
                continue
            row = self.fetch_one(
                f"SELECT trade_date, close FROM {table} ORDER BY trade_date DESC LIMIT 1"
            )
            if not row:
                continue
            td = row.get("trade_date")
            close_v = row.get("close")
            if td is None or close_v is None:
                continue
            try:
                out[sc] = {"trade_date": str(td)[:10], "close": float(close_v)}
            except Exception:
                continue

        if cache_key and out:
            try:
                _redis_set_json(cache_key, out, ttl_seconds=ttl)
            except Exception:
                pass
        return out

    def ensure_system_settings_tables(self):
        """确保 system_settings 表存在（不依赖 init_database）。"""
        if self.is_sqlite:
            self._create_system_settings_tables_sqlite()
        else:
            self._create_system_settings_tables_mysql()
        self._migrate_system_settings_schema()

    def _system_settings_columns(self) -> tuple[str, str, str]:
        """
        返回 system_settings 的列名映射：(section_col, key_col, value_col)。
        兼容历史表结构：
        - 新：section + key + value
        - 旧：group_name + setting_key + setting_value（或 val）
        """
        # section/group
        if self.column_exists("system_settings", "section"):
            section_col = "section"
        elif self.column_exists("system_settings", "group_name"):
            section_col = "group_name"
        else:
            section_col = "section"

        # key
        if self.column_exists("system_settings", "key"):
            key_col = "key"
        elif self.column_exists("system_settings", "setting_key"):
            key_col = "setting_key"
        else:
            key_col = "key"

        # value
        if self.column_exists("system_settings", "value"):
            value_col = "value"
        elif self.column_exists("system_settings", "setting_value"):
            value_col = "setting_value"
        elif self.column_exists("system_settings", "val"):
            value_col = "val"
        else:
            value_col = "value"

        return section_col, key_col, value_col

    def _quote_ident(self, ident: str) -> str:
        """最小化标识符 quoting：仅对 key 这类可能冲突的列做处理。"""
        if not ident:
            return ident
        if self.is_sqlite:
            # SQLite 中 key 不强制保留；用双引号也可，但保持简单
            return ident
        # MySQL
        if ident.lower() in ("key",):
            return f"`{ident}`"
        return ident

    def _migrate_system_settings_schema(self):
        """
        兼容旧版本 system_settings 表结构（历史上可能不存在 value 字段）。
        必须同时兼容 MySQL + SQLite（语义一致）。
        """
        try:
            if not self.table_exists("system_settings"):
                return

            # 若已是旧结构（group_name/setting_key/setting_value），不强行改表，只在查询/写入时做适配
            # 若缺少 value 字段但也不存在 setting_value/val，则补一个 value 字段以保证可用
            has_value = self.column_exists("system_settings", "value")
            has_legacy_value = self.column_exists("system_settings", "setting_value") or self.column_exists(
                "system_settings", "val"
            )
            if (not has_value) and (not has_legacy_value):
                if self.is_sqlite:
                    self.execute("ALTER TABLE system_settings ADD COLUMN value TEXT")
                else:
                    self.execute("ALTER TABLE system_settings ADD COLUMN value TEXT")
        except Exception as e:
            # 迁移失败不应影响主流程，尽力而为
            logger.warning("system_settings 表结构迁移失败（已忽略）: %s", e)

    def get_system_setting(self, section: str, key: str):
        """读取单条系统设置；不存在返回 None。"""
        self.ensure_system_settings_tables()
        sec = (section or '').strip()
        k = (key or '').strip()
        if not sec or not k:
            return None
        section_col, key_col, value_col = self._system_settings_columns()
        row = self.fetch_one(
            f'SELECT {self._quote_ident(value_col)} AS value FROM system_settings '
            f'WHERE {self._quote_ident(section_col)} = %s AND {self._quote_ident(key_col)} = %s LIMIT 1',
            (sec, k),
        )
        if not row:
            return None
        return row.get('value')

    def upsert_system_setting(self, section: str, key: str, value) -> bool:
        """写入或更新单条系统设置（value 统一存 TEXT）。"""
        self.ensure_system_settings_tables()
        sec = (section or '').strip()
        k = (key or '').strip()
        if not sec or not k:
            raise ValueError('section/key 不能为空')
        v = None if value is None else str(value)
        section_col, key_col, value_col = self._system_settings_columns()
        sec_q = self._quote_ident(section_col)
        key_q = self._quote_ident(key_col)
        val_q = self._quote_ident(value_col)
        if self.is_sqlite:
            self.execute(
                f'''INSERT INTO system_settings ({sec_q}, {key_q}, {val_q}, updated_at)
                   VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT({sec_q}, {key_q}) DO UPDATE SET
                       {val_q}=excluded.{val_q},
                       updated_at=CURRENT_TIMESTAMP''',
                (sec, k, v),
            )
        else:
            self.execute(
                f'''INSERT INTO system_settings ({sec_q}, {key_q}, {val_q})
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE {val_q}=VALUES({val_q}), updated_at=CURRENT_TIMESTAMP''',
                (sec, k, v),
            )
        return True

    def _create_scheduled_task_tables_mysql(self):
        """APScheduler 业务任务配置（MySQL）。"""
        self.execute('''CREATE TABLE IF NOT EXISTS scheduled_task (
            task_id VARCHAR(128) PRIMARY KEY,
            task_name VARCHAR(256) NOT NULL,
            module_path VARCHAR(256) NOT NULL,
            function_name VARCHAR(128) NOT NULL,
            trigger_type VARCHAR(32) NOT NULL,
            trigger_args TEXT NOT NULL,
            enabled TINYINT NOT NULL DEFAULT 1,
            run_once_per_day TINYINT NOT NULL DEFAULT 0,
            max_instances INT NOT NULL DEFAULT 1,
            misfire_grace_time INT NULL,
            job_coalesce TINYINT NOT NULL DEFAULT 1,
            description TEXT,
            args_json TEXT,
            kwargs_json TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    def _create_scheduled_task_run_daily_tables_sqlite(self):
        """每日只跑一次：任务运行记录（SQLite）。"""
        self.execute('''CREATE TABLE IF NOT EXISTS scheduled_task_run_daily (
            task_id TEXT NOT NULL,
            run_date TEXT NOT NULL,
            ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (task_id, run_date)
        )''')

    def _create_scheduled_task_run_daily_tables_mysql(self):
        """每日只跑一次：任务运行记录（MySQL）。"""
        self.execute('''CREATE TABLE IF NOT EXISTS scheduled_task_run_daily (
            task_id VARCHAR(128) NOT NULL,
            run_date DATE NOT NULL,
            ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (task_id, run_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    def _create_user_watchlist_tables_mysql(self):
        """用户自选列表（MySQL）"""
        self.execute('''CREATE TABLE IF NOT EXISTS user_watchlist (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            stock_code VARCHAR(32) NOT NULL,
            stock_name VARCHAR(128),
            sort_order INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_user_watchlist_user_stock (user_id, stock_code),
            KEY idx_user_watchlist_user (user_id),
            CONSTRAINT fk_user_watchlist_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    def _create_message_group_tables_mysql(self):
        """聊天群列表表（MySQL）"""
        self.execute('''CREATE TABLE IF NOT EXISTS message_group (
            id INT AUTO_INCREMENT PRIMARY KEY,
            group_id INT NOT NULL,
            list_type VARCHAR(32) NOT NULL DEFAULT 'weixin',
            name VARCHAR(128) DEFAULT NULL,
            send_mode VARCHAR(32) NOT NULL DEFAULT '',
            chat_id VARCHAR(128) DEFAULT NULL,
            webhook_url TEXT DEFAULT NULL,
            sign_secret TEXT DEFAULT NULL,
            app_id VARCHAR(128) DEFAULT NULL,
            app_secret TEXT DEFAULT NULL,
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

    def _create_signal_rule_tables_sqlite(self):
        """信号规则表（SQLite）。signal_type 为自由文本，含 price_range / fibonacci_retrace / price_level_interval（到价提醒）等。"""
        self.execute('''CREATE TABLE IF NOT EXISTS signal_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            group_ids_json TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            params_json TEXT NOT NULL,
            message_template TEXT NOT NULL,
            send_type TEXT NOT NULL DEFAULT 'on_trigger',
            send_interval_seconds INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        try:
            self.execute("CREATE INDEX IF NOT EXISTS idx_signal_rule_stock_code ON signal_rule (stock_code)")
        except Exception:
            pass
        try:
            self.execute("CREATE INDEX IF NOT EXISTS idx_signal_rule_active ON signal_rule (is_active)")
        except Exception:
            pass

    def _create_signal_rule_tables_mysql(self):
        """信号规则表（MySQL）。signal_type 为自由文本，含 price_range / fibonacci_retrace / price_level_interval（到价提醒）等。"""
        self.execute('''CREATE TABLE IF NOT EXISTS signal_rule (
            id INT AUTO_INCREMENT PRIMARY KEY,
            stock_code VARCHAR(32) NOT NULL,
            stock_name VARCHAR(128),
            group_ids_json TEXT NOT NULL,
            signal_type VARCHAR(64) NOT NULL,
            params_json TEXT NOT NULL,
            message_template TEXT NOT NULL,
            send_type VARCHAR(32) NOT NULL DEFAULT 'on_trigger',
            send_interval_seconds INT NOT NULL DEFAULT 0,
            is_active TINYINT NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_signal_rule_stock_code (stock_code),
            KEY idx_signal_rule_active (is_active)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    def _create_signal_rule_state_tables_sqlite(self):
        """信号规则状态表（SQLite）"""
        self.execute('''CREATE TABLE IF NOT EXISTS signal_rule_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id INTEGER NOT NULL UNIQUE,
            state_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rule_id) REFERENCES signal_rule(id) ON DELETE CASCADE
        )''')
        try:
            self.execute("CREATE INDEX IF NOT EXISTS idx_signal_rule_state_rule_id ON signal_rule_state (rule_id)")
        except Exception:
            pass

    def _create_signal_rule_state_tables_mysql(self):
        """信号规则状态表（MySQL）"""
        self.execute('''CREATE TABLE IF NOT EXISTS signal_rule_state (
            id INT AUTO_INCREMENT PRIMARY KEY,
            rule_id INT NOT NULL,
            state_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_signal_rule_state_rule_id (rule_id),
            CONSTRAINT fk_signal_rule_state_rule
                FOREIGN KEY (rule_id) REFERENCES signal_rule(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    # ─────────────────────────── 聊天群列表 ────────────────────────────────────

    def ensure_message_group_tables(self):
        """确保 message_group 相关表存在（不依赖 init_database）"""
        if self.is_sqlite:
            self._create_message_group_tables_sqlite()
        else:
            self._create_message_group_tables_mysql()
        # 兼容旧库：补列（MySQL/SQLite 语义保持一致）
        try:
            if not self.column_exists("message_group", "name"):
                self.execute("ALTER TABLE message_group ADD COLUMN name VARCHAR(128) DEFAULT NULL")
        except Exception as e:
            logger.warning("message_group 补列 name 失败（已忽略）: %s", e)
        try:
            if not self.column_exists("message_group", "send_mode"):
                self.execute("ALTER TABLE message_group ADD COLUMN send_mode VARCHAR(32) NOT NULL DEFAULT ''")
        except Exception as e:
            logger.warning("message_group 补列 send_mode 失败（已忽略）: %s", e)
        try:
            if not self.column_exists("message_group", "chat_id"):
                self.execute("ALTER TABLE message_group ADD COLUMN chat_id VARCHAR(128) DEFAULT NULL")
        except Exception as e:
            logger.warning("message_group 补列 chat_id 失败（已忽略）: %s", e)
        try:
            if not self.column_exists("message_group", "webhook_url"):
                self.execute("ALTER TABLE message_group ADD COLUMN webhook_url TEXT DEFAULT NULL")
        except Exception as e:
            logger.warning("message_group 补列 webhook_url 失败（已忽略）: %s", e)
        try:
            if not self.column_exists("message_group", "sign_secret"):
                self.execute("ALTER TABLE message_group ADD COLUMN sign_secret TEXT DEFAULT NULL")
        except Exception as e:
            logger.warning("message_group 补列 sign_secret 失败（已忽略）: %s", e)
        try:
            if not self.column_exists("message_group", "app_id"):
                self.execute("ALTER TABLE message_group ADD COLUMN app_id VARCHAR(128) DEFAULT NULL")
        except Exception as e:
            logger.warning("message_group 补列 app_id 失败（已忽略）: %s", e)
        try:
            if not self.column_exists("message_group", "app_secret"):
                self.execute("ALTER TABLE message_group ADD COLUMN app_secret TEXT DEFAULT NULL")
        except Exception as e:
            logger.warning("message_group 补列 app_secret 失败（已忽略）: %s", e)

    def _create_nga_auto_summary_task_tables_sqlite(self):
        self.execute(
            '''CREATE TABLE IF NOT EXISTS nga_auto_summary_task (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tid INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            message_group_id VARCHAR(32) NOT NULL,
            run_time VARCHAR(5) NOT NULL,
            extra_prompt TEXT DEFAULT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tid, author_id, run_time)
        )'''
        )
        try:
            self.execute(
                "CREATE INDEX IF NOT EXISTS idx_nga_auto_summary_task_tid ON nga_auto_summary_task (tid)"
            )
        except Exception:
            pass

    def _create_nga_auto_summary_task_tables_mysql(self):
        self.execute(
            '''CREATE TABLE IF NOT EXISTS nga_auto_summary_task (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            tid INT NOT NULL,
            author_id INT NOT NULL,
            message_group_id VARCHAR(32) NOT NULL,
            run_time VARCHAR(5) NOT NULL,
            extra_prompt TEXT NULL,
            enabled TINYINT NOT NULL DEFAULT 1,
            last_run_at DATETIME NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_nga_auto_sum_tid_author_time (tid, author_id, run_time),
            KEY idx_nga_auto_summary_task_tid (tid)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''
        )

    def ensure_nga_auto_summary_task_tables(self):
        """NGA 关注作者时段总结：每日定时自动任务（MySQL / SQLite 一致）。"""
        if self.is_sqlite:
            self._create_nga_auto_summary_task_tables_sqlite()
        else:
            self._create_nga_auto_summary_task_tables_mysql()

    # ─────────────────────────── NGA 作者时段总结缓存（429 回退） ────────────────────────────

    def _create_nga_author_daily_summary_cache_tables_sqlite(self):
        self.execute(
            '''CREATE TABLE IF NOT EXISTS nga_author_daily_summary_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            tid INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            summary_date TEXT NOT NULL,
            data TEXT NOT NULL,
            http_status INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(task_id, summary_date)
        )'''
        )
        try:
            self.execute(
                "CREATE INDEX IF NOT EXISTS idx_nga_author_daily_summary_cache_tid ON nga_author_daily_summary_cache (tid)"
            )
        except Exception:
            pass
        try:
            self.execute(
                "CREATE INDEX IF NOT EXISTS idx_nga_author_daily_summary_cache_task ON nga_author_daily_summary_cache (task_id)"
            )
        except Exception:
            pass

    def _create_nga_author_daily_summary_cache_tables_mysql(self):
        self.execute(
            '''CREATE TABLE IF NOT EXISTS nga_author_daily_summary_cache (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            task_id BIGINT NOT NULL,
            tid INT NOT NULL,
            author_id INT NOT NULL,
            summary_date DATE NOT NULL,
            data MEDIUMTEXT NOT NULL,
            http_status INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_nga_author_daily_summary_cache_task_date (task_id, summary_date),
            KEY idx_nga_author_daily_summary_cache_tid (tid),
            KEY idx_nga_author_daily_summary_cache_task (task_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''
        )

    def ensure_nga_author_daily_summary_cache_tables(self):
        """当 Gemini 命中 429 时，将“当日总结材料/结果”落库，供页面弹窗回看（MySQL / SQLite 一致）。"""
        if self.is_sqlite:
            self._create_nga_author_daily_summary_cache_tables_sqlite()
        else:
            self._create_nga_author_daily_summary_cache_tables_mysql()

    def upsert_nga_author_daily_summary_cache(
        self,
        *,
        task_id: int,
        tid: int,
        author_id: int,
        summary_date: str,
        data: str,
        http_status: int = 0,
    ) -> bool:
        """写入或更新某 task_id 在某日期的缓存内容（幂等，一天一行）。"""
        self.ensure_nga_author_daily_summary_cache_tables()
        t_id = int(task_id)
        if t_id < 0:
            t_id = 0
        td = int(tid)
        aid = int(author_id)
        d = str(summary_date or "").strip()
        if not d:
            raise ValueError("summary_date 不能为空")
        body = (data or "").strip()
        if not body:
            raise ValueError("data 不能为空")
        hs = int(http_status or 0)
        if self.is_sqlite:
            self.execute(
                '''INSERT INTO nga_author_daily_summary_cache (task_id, tid, author_id, summary_date, data, http_status, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT(task_id, summary_date) DO UPDATE SET
                       tid=excluded.tid,
                       author_id=excluded.author_id,
                       data=excluded.data,
                       http_status=excluded.http_status,
                       updated_at=CURRENT_TIMESTAMP''',
                (t_id, td, aid, d, body, hs),
            )
        else:
            # MySQL summary_date 为 DATE；直接传 YYYY-MM-DD 字符串即可
            self.execute(
                '''INSERT INTO nga_author_daily_summary_cache (task_id, tid, author_id, summary_date, data, http_status)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                       tid=VALUES(tid),
                       author_id=VALUES(author_id),
                       data=VALUES(data),
                       http_status=VALUES(http_status),
                       updated_at=CURRENT_TIMESTAMP''',
                (t_id, td, aid, d, body, hs),
            )
        return True

    def list_nga_author_daily_summary_cache(self, *, tid: int, task_id: int, limit: int = 60) -> list[dict]:
        """按 tid+task_id 列出缓存（日期倒序）。"""
        self.ensure_nga_author_daily_summary_cache_tables()
        lim = int(limit or 60)
        if lim < 1:
            lim = 1
        if lim > 365:
            lim = 365
        rows = self.fetch_all(
            f"SELECT id, task_id, tid, author_id, summary_date, http_status, created_at, updated_at "
            f"FROM nga_author_daily_summary_cache WHERE tid=%s AND task_id=%s "
            f"ORDER BY summary_date DESC, id DESC LIMIT {lim}",
            (int(tid), int(task_id)),
        )
        out = []
        for r in rows or []:
            out.append(
                {
                    "id": int(r.get("id")),
                    "task_id": int(r.get("task_id")),
                    "tid": int(r.get("tid")),
                    "author_id": int(r.get("author_id")),
                    "summary_date": str(r.get("summary_date") or "")[:10],
                    "http_status": int(r.get("http_status") or 0),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                }
            )
        return out

    def get_nga_author_daily_summary_cache(self, *, cache_id: int) -> dict | None:
        """读取单条缓存（含 data）。"""
        self.ensure_nga_author_daily_summary_cache_tables()
        row = self.fetch_one(
            "SELECT id, task_id, tid, author_id, summary_date, data, http_status, created_at, updated_at "
            "FROM nga_author_daily_summary_cache WHERE id=%s LIMIT 1",
            (int(cache_id),),
        )
        if not row:
            return None
        return {
            "id": int(row.get("id")),
            "task_id": int(row.get("task_id")),
            "tid": int(row.get("tid")),
            "author_id": int(row.get("author_id")),
            "summary_date": str(row.get("summary_date") or "")[:10],
            "data": row.get("data") or "",
            "http_status": int(row.get("http_status") or 0),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def list_nga_auto_summary_tasks_by_tid(self, tid: int) -> list:
        self.ensure_nga_auto_summary_task_tables()
        return (
            self.fetch_all(
                "SELECT id, tid, author_id, message_group_id, run_time, extra_prompt, enabled, "
                "last_run_at, created_at FROM nga_auto_summary_task WHERE tid = %s ORDER BY run_time, id",
                (int(tid),),
            )
            or []
        )

    def list_nga_auto_summary_tasks_enabled(self) -> list:
        self.ensure_nga_auto_summary_task_tables()
        return (
            self.fetch_all(
                "SELECT id, tid, author_id, message_group_id, run_time, extra_prompt, enabled, "
                "last_run_at, created_at FROM nga_auto_summary_task WHERE enabled = 1 ORDER BY tid, id"
            )
            or []
        )

    def insert_nga_auto_summary_task(
        self,
        tid: int,
        author_id: int,
        message_group_id: str,
        run_time: str,
        extra_prompt: str | None = None,
        enabled: int = 1,
    ) -> tuple[bool, str | int]:
        """插入一条自动任务，成功返回 (True, id)，失败 (False, error_msg)。"""
        self.ensure_nga_auto_summary_task_tables()
        try:
            ep = (extra_prompt or "").strip() or None
            self.execute(
                "INSERT INTO nga_auto_summary_task "
                "(tid, author_id, message_group_id, run_time, extra_prompt, enabled) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (int(tid), int(author_id), str(message_group_id), str(run_time), ep, int(enabled or 0)),
            )
            if self.is_sqlite:
                row = self.fetch_one("SELECT last_insert_rowid() AS id")
            else:
                row = self.fetch_one("SELECT LAST_INSERT_ID() AS id")
            return (True, int(row["id"]))
        except Exception as e:
            err = str(e)
            if "UNIQUE" in err.upper() or "unique" in err:
                return (False, "该作者在相同每日执行时间下已有自动任务")
            logger.error("insert_nga_auto_summary_task 失败: %s", e, exc_info=True)
            return (False, err)

    def get_nga_auto_summary_task_by_id(self, task_id: int) -> dict | None:
        self.ensure_nga_auto_summary_task_tables()
        return self.fetch_one(
            "SELECT id, tid, author_id, message_group_id, run_time, extra_prompt, enabled, "
            "last_run_at, created_at FROM nga_auto_summary_task WHERE id = %s LIMIT 1",
            (int(task_id),),
        )

    def delete_nga_auto_summary_task(self, task_id: int) -> bool:
        self.ensure_nga_auto_summary_task_tables()
        self.execute("DELETE FROM nga_auto_summary_task WHERE id = %s", (int(task_id),))
        return True

    def update_nga_auto_summary_task_last_run(self, task_id: int, when) -> None:
        self.ensure_nga_auto_summary_task_tables()
        self.execute(
            "UPDATE nga_auto_summary_task SET last_run_at = %s WHERE id = %s",
            (when, int(task_id)),
        )

    def ensure_signal_rule_tables(self):
        """确保 signal_rule 表存在（不依赖 init_database）"""
        if self.is_sqlite:
            self._create_signal_rule_tables_sqlite()
        else:
            self._create_signal_rule_tables_mysql()

    def ensure_signal_rule_state_tables(self):
        """确保 signal_rule_state 表存在（不依赖 init_database）"""
        self.ensure_signal_rule_tables()
        if self.is_sqlite:
            self._create_signal_rule_state_tables_sqlite()
        else:
            self._create_signal_rule_state_tables_mysql()

    def ensure_user_watchlist_tables(self):
        """确保 user_watchlist 表存在"""
        if self.is_sqlite:
            self._create_user_watchlist_tables_sqlite()
        else:
            self._create_user_watchlist_tables_mysql()

    def ensure_scheduled_task_tables(self):
        """确保 scheduled_task 表存在（APScheduler 任务配置）。"""
        if self.is_sqlite:
            self._create_scheduled_task_tables_sqlite()
        else:
            self._create_scheduled_task_tables_mysql()
        # 兼容旧库：补列
        try:
            if not self.column_exists("scheduled_task", "run_once_per_day"):
                if self.is_sqlite:
                    self.execute("ALTER TABLE scheduled_task ADD COLUMN run_once_per_day INTEGER NOT NULL DEFAULT 0")
                else:
                    self.execute("ALTER TABLE scheduled_task ADD COLUMN run_once_per_day TINYINT NOT NULL DEFAULT 0")
        except Exception as e:
            logger.warning("scheduled_task 补列 run_once_per_day 失败（已忽略）: %s", e)

    def ensure_scheduled_task_run_daily_tables(self):
        """确保 scheduled_task_run_daily 表存在（每日只跑一次运行记录）。"""
        if self.is_sqlite:
            self._create_scheduled_task_run_daily_tables_sqlite()
        else:
            self._create_scheduled_task_run_daily_tables_mysql()

    def has_scheduled_task_run_today(self, task_id: str, today: str | None = None) -> bool:
        """判断 task_id 在今天是否已成功跑过（存在记录即视为已跑）。"""
        self.ensure_scheduled_task_run_daily_tables()
        tid = (task_id or "").strip()
        if not tid:
            return False
        if today is None:
            today = datetime.now().strftime("%Y-%m-%d")
        row = self.fetch_one(
            "SELECT 1 AS x FROM scheduled_task_run_daily WHERE task_id = %s AND run_date = %s LIMIT 1",
            (tid, today),
        )
        return row is not None

    def mark_scheduled_task_ran_today(self, task_id: str, today: str | None = None) -> bool:
        """写入今日已执行标记（幂等）。"""
        self.ensure_scheduled_task_run_daily_tables()
        tid = (task_id or "").strip()
        if not tid:
            return False
        if today is None:
            today = datetime.now().strftime("%Y-%m-%d")
        self.execute(
            "INSERT IGNORE INTO scheduled_task_run_daily (task_id, run_date) VALUES (%s, %s)",
            (tid, today),
        )
        return True

    def count_scheduled_tasks(self) -> int:
        """scheduled_task 行数。"""
        self.ensure_scheduled_task_tables()
        row = self.fetch_one('SELECT COUNT(*) AS c FROM scheduled_task')
        if not row:
            return 0
        v = row.get('c')
        return int(v) if v is not None else 0

    def scheduled_task_exists(self, task_id: str) -> bool:
        self.ensure_scheduled_task_tables()
        tid = (task_id or '').strip()
        if not tid:
            return False
        row = self.fetch_one(
            'SELECT 1 AS x FROM scheduled_task WHERE task_id = %s LIMIT 1',
            (tid,),
        )
        return row is not None

    def fetch_all_scheduled_tasks(self):
        """返回 scheduled_task 全部行（dict），按 task_id 排序。"""
        self.ensure_scheduled_task_tables()
        return self.fetch_all(
            'SELECT task_id, task_name, module_path, function_name, trigger_type, trigger_args, '
            'enabled, run_once_per_day, max_instances, misfire_grace_time, job_coalesce, description, args_json, kwargs_json '
            'FROM scheduled_task ORDER BY task_id ASC'
        ) or []

    def upsert_scheduled_task(self, task_dict: dict) -> bool:
        """
        插入或更新一条任务配置。task_dict 与 tasks_config.yaml 中单条结构一致，
        trigger_args 可为 dict；args / kwargs 可选。
        """
        self.ensure_scheduled_task_tables()
        tid = (task_dict.get('task_id') or '').strip()
        if not tid:
            raise ValueError('task_id 不能为空')
        ta = task_dict.get('trigger_args')
        if isinstance(ta, str):
            ta = json.loads(ta) if ta.strip() else {}
        if not isinstance(ta, dict):
            ta = {}
        trigger_args_s = json.dumps(ta, ensure_ascii=False)
        args = task_dict.get('args', ())
        if isinstance(args, list):
            args = tuple(args)
        kwargs = task_dict.get('kwargs') if isinstance(task_dict.get('kwargs'), dict) else {}
        args_s = json.dumps(list(args), ensure_ascii=False) if args else None
        kwargs_s = json.dumps(kwargs, ensure_ascii=False)
        enabled = 1 if task_dict.get('enabled', True) else 0
        run_once = 1 if task_dict.get('run_once_per_day', False) else 0
        job_coalesce = 1 if task_dict.get('coalesce', True) else 0
        mg = task_dict.get('misfire_grace_time')
        if mg is not None:
            mg = int(mg)
        max_inst = int(task_dict.get('max_instances', 1))
        desc = task_dict.get('description') or ''
        tname = (task_dict.get('task_name') or tid).strip()
        mp = (task_dict.get('module_path') or '').strip()
        fn = (task_dict.get('function_name') or '').strip()
        tt = (task_dict.get('trigger_type') or 'cron').strip()
        if self.is_sqlite:
            sql = '''INSERT OR REPLACE INTO scheduled_task (
                task_id, task_name, module_path, function_name, trigger_type, trigger_args,
                enabled, run_once_per_day, max_instances, misfire_grace_time, job_coalesce, description, args_json, kwargs_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'''
            self.execute(
                sql,
                (
                    tid, tname, mp, fn, tt, trigger_args_s, enabled, run_once, max_inst, mg, job_coalesce, desc,
                    args_s, kwargs_s,
                ),
            )
        else:
            sql = '''INSERT INTO scheduled_task (
                task_id, task_name, module_path, function_name, trigger_type, trigger_args,
                enabled, run_once_per_day, max_instances, misfire_grace_time, job_coalesce, description, args_json, kwargs_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                task_name=VALUES(task_name), module_path=VALUES(module_path), function_name=VALUES(function_name),
                trigger_type=VALUES(trigger_type), trigger_args=VALUES(trigger_args), enabled=VALUES(enabled),
                run_once_per_day=VALUES(run_once_per_day),
                max_instances=VALUES(max_instances), misfire_grace_time=VALUES(misfire_grace_time),
                job_coalesce=VALUES(job_coalesce), description=VALUES(description),
                args_json=VALUES(args_json), kwargs_json=VALUES(kwargs_json)'''
            self.execute(
                sql,
                (
                    tid, tname, mp, fn, tt, trigger_args_s, enabled, run_once, max_inst, mg, job_coalesce, desc,
                    args_s, kwargs_s,
                ),
            )
        return True

    def delete_scheduled_task(self, task_id: str) -> bool:
        self.ensure_scheduled_task_tables()
        self.execute('DELETE FROM scheduled_task WHERE task_id = %s', ((task_id or '').strip(),))
        return True

    def get_user_watchlist(self, user_id: int):
        """返回当前用户的自选列表，按 sort_order 排序。"""
        self.ensure_user_watchlist_tables()
        rows = self.fetch_all(
            'SELECT stock_code, stock_name, sort_order FROM user_watchlist WHERE user_id = %s '
            'ORDER BY sort_order ASC, id ASC',
            (int(user_id),)
        )
        out = []
        for r in rows or []:
            out.append({
                'stock_code': (r.get('stock_code') or '').strip(),
                'stock_name': (r.get('stock_name') or '').strip(),
            })
        return out

    def replace_user_watchlist(self, user_id: int, items):
        """用新列表整体替换用户自选（先删后插）。"""
        self.ensure_user_watchlist_tables()
        uid = int(user_id)
        self.execute('DELETE FROM user_watchlist WHERE user_id = %s', (uid,))
        order = 0
        for it in items or []:
            sc = str((it or {}).get('stock_code') or '').strip()
            if not sc:
                continue
            sn = str((it or {}).get('stock_name') or '').strip()
            self.execute(
                'INSERT INTO user_watchlist (user_id, stock_code, stock_name, sort_order) '
                'VALUES (%s, %s, %s, %s)',
                (uid, sc, sn or None, order),
            )
            order += 1
        return True

    @staticmethod
    def _user_watchlist_basic_code(code: str) -> str:
        """与前端 normalizeBasicKey 一致：取点号前一段，用于 600000 / 600000.SH 等同码匹配。"""
        c = str(code or '').strip()
        if not c:
            return ''
        return c.split('.', 1)[0].strip()

    def remove_user_watchlist_item(self, user_id: int, stock_code: str) -> int:
        """删除当前用户自选中的一条；先精确匹配 stock_code，再按 basic code 匹配。返回删除行数。"""
        self.ensure_user_watchlist_tables()
        uid = int(user_id)
        sc = str(stock_code or '').strip()
        if not sc:
            return 0
        cursor = self.execute(
            'DELETE FROM user_watchlist WHERE user_id = %s AND stock_code = %s',
            (uid, sc),
        )
        n = int(getattr(cursor, 'rowcount', 0) or 0)
        if n:
            return n
        basic = Database._user_watchlist_basic_code(sc)
        if not basic:
            return 0
        rows = self.fetch_all(
            'SELECT stock_code FROM user_watchlist WHERE user_id = %s',
            (uid,),
        )
        for r in rows or []:
            db_sc = str(r.get('stock_code') or '').strip()
            if Database._user_watchlist_basic_code(db_sc) == basic:
                cursor2 = self.execute(
                    'DELETE FROM user_watchlist WHERE user_id = %s AND stock_code = %s',
                    (uid, db_sc),
                )
                return int(getattr(cursor2, 'rowcount', 0) or 0)
        return 0

    # ─────────────────────────── 投资日历（MySQL/SQLite 双引擎一致） ────────────────────────────

    def _create_investment_calendar_tables_sqlite(self):
        self.execute('''CREATE TABLE IF NOT EXISTS investment_calendar_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date DATE NOT NULL,
            content TEXT NOT NULL,
            reminder_group TEXT,
            reminder_message TEXT,
            remind_anchor_time TEXT NOT NULL DEFAULT '09:00',
            remind_advance_minutes INTEGER NOT NULL DEFAULT 0,
            remind_count_per_day INTEGER NOT NULL DEFAULT 1,
            remind_interval_minutes INTEGER NOT NULL DEFAULT 60,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )''')
        try:
            self.execute(
                "CREATE INDEX IF NOT EXISTS idx_inv_cal_item_user_date "
                "ON investment_calendar_item (user_id, date)"
            )
        except Exception:
            pass
        try:
            self.execute(
                '''CREATE TRIGGER IF NOT EXISTS trg_inv_cal_item_updated_at
                   AFTER UPDATE ON investment_calendar_item
                   FOR EACH ROW
                   WHEN NEW.updated_at = OLD.updated_at
                   BEGIN
                       UPDATE investment_calendar_item
                       SET updated_at = CURRENT_TIMESTAMP
                       WHERE id = NEW.id;
                   END'''
            )
        except Exception:
            pass

    def _create_investment_calendar_tables_mysql(self):
        self.execute('''CREATE TABLE IF NOT EXISTS investment_calendar_item (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            date DATE NOT NULL,
            content TEXT NOT NULL,
            reminder_group VARCHAR(128) DEFAULT NULL,
            reminder_message TEXT DEFAULT NULL,
            remind_anchor_time VARCHAR(5) NOT NULL DEFAULT '09:00',
            remind_advance_minutes INT NOT NULL DEFAULT 0,
            remind_count_per_day INT NOT NULL DEFAULT 1,
            remind_interval_minutes INT NOT NULL DEFAULT 60,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_inv_cal_item_user_date (user_id, date),
            CONSTRAINT fk_inv_cal_item_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    def migrate_investment_calendar_item_remind_columns(self):
        """为已有 investment_calendar_item 表补充提醒时间相关列（MySQL / SQLite 语义一致）。"""
        t = 'investment_calendar_item'
        try:
            self.ensure_investment_calendar_tables()
        except Exception:
            return
        if not self.table_exists(t):
            return
        if self.is_sqlite:
            pairs = [
                ('remind_anchor_time', "ALTER TABLE investment_calendar_item ADD COLUMN remind_anchor_time TEXT NOT NULL DEFAULT '09:00'"),
                ('remind_advance_minutes', 'ALTER TABLE investment_calendar_item ADD COLUMN remind_advance_minutes INTEGER NOT NULL DEFAULT 0'),
                ('remind_count_per_day', 'ALTER TABLE investment_calendar_item ADD COLUMN remind_count_per_day INTEGER NOT NULL DEFAULT 1'),
                ('remind_interval_minutes', 'ALTER TABLE investment_calendar_item ADD COLUMN remind_interval_minutes INTEGER NOT NULL DEFAULT 60'),
            ]
        else:
            pairs = [
                ("remind_anchor_time", "ALTER TABLE investment_calendar_item ADD COLUMN remind_anchor_time VARCHAR(5) NOT NULL DEFAULT '09:00'"),
                ('remind_advance_minutes', 'ALTER TABLE investment_calendar_item ADD COLUMN remind_advance_minutes INT NOT NULL DEFAULT 0'),
                ('remind_count_per_day', 'ALTER TABLE investment_calendar_item ADD COLUMN remind_count_per_day INT NOT NULL DEFAULT 1'),
                ('remind_interval_minutes', 'ALTER TABLE investment_calendar_item ADD COLUMN remind_interval_minutes INT NOT NULL DEFAULT 60'),
            ]
        for col, ddl in pairs:
            try:
                if self.column_exists(t, col):
                    continue
                self.execute(ddl)
            except Exception as e:
                logger.warning('迁移 investment_calendar_item 列 %s 失败: %s', col, e)

    def ensure_investment_calendar_tables(self):
        if self.is_sqlite:
            self._create_investment_calendar_tables_sqlite()
        else:
            self._create_investment_calendar_tables_mysql()

    def _create_investment_calendar_reminder_log_tables_sqlite(self):
        self.execute('''CREATE TABLE IF NOT EXISTS investment_calendar_reminder_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            remind_at TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, item_id, remind_at),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (item_id) REFERENCES investment_calendar_item(id) ON DELETE CASCADE
        )''')
        try:
            self.execute(
                "CREATE INDEX IF NOT EXISTS idx_inv_cal_rem_log_user_remind_at "
                "ON investment_calendar_reminder_log (user_id, remind_at)"
            )
        except Exception:
            pass

    def _create_investment_calendar_reminder_log_tables_mysql(self):
        self.execute('''CREATE TABLE IF NOT EXISTS investment_calendar_reminder_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            item_id INT NOT NULL,
            remind_at DATETIME NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_inv_cal_rem_log (user_id, item_id, remind_at),
            KEY idx_inv_cal_rem_log_user_remind_at (user_id, remind_at),
            CONSTRAINT fk_inv_cal_rem_log_user
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT fk_inv_cal_rem_log_item
                FOREIGN KEY (item_id) REFERENCES investment_calendar_item(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')

    def ensure_investment_calendar_reminder_log_tables(self):
        """确保投资日历提醒发送日志表存在（用于去重/幂等）。"""
        self.ensure_investment_calendar_tables()
        if self.is_sqlite:
            self._create_investment_calendar_reminder_log_tables_sqlite()
        else:
            self._create_investment_calendar_reminder_log_tables_mysql()

    def mark_investment_calendar_reminded(self, user_id: int, item_id: int, remind_at: str) -> bool:
        """记录一次提醒（幂等）。remind_at: 'YYYY-MM-DD HH:MM:SS'。"""
        self.ensure_investment_calendar_reminder_log_tables()
        uid = int(user_id)
        iid = int(item_id)
        if self.is_sqlite:
            sql = (
                "INSERT OR IGNORE INTO investment_calendar_reminder_log (user_id, item_id, remind_at) "
                "VALUES (%s, %s, %s)"
            )
        else:
            sql = (
                "INSERT IGNORE INTO investment_calendar_reminder_log (user_id, item_id, remind_at) "
                "VALUES (%s, %s, %s)"
            )
        self.execute(sql, (uid, iid, remind_at))
        return True

    def has_investment_calendar_reminded(self, user_id: int, item_id: int, remind_at: str) -> bool:
        """判断某次提醒是否已经发送记录过。"""
        self.ensure_investment_calendar_reminder_log_tables()
        row = self.fetch_one(
            "SELECT 1 AS x FROM investment_calendar_reminder_log WHERE user_id=%s AND item_id=%s AND remind_at=%s LIMIT 1",
            (int(user_id), int(item_id), remind_at),
        )
        return row is not None

    def list_investment_calendar_items(self, user_id: int, start_date: str, end_date: str):
        """按日期范围返回用户日历项，按 date ASC, id ASC 稳定排序。"""
        self.ensure_investment_calendar_tables()
        uid = int(user_id)
        rows = self.fetch_all(
            '''SELECT id, user_id, date, content, reminder_group, reminder_message,
                      remind_anchor_time, remind_advance_minutes, remind_count_per_day, remind_interval_minutes,
                      created_at, updated_at
               FROM investment_calendar_item
               WHERE user_id = %s AND date >= %s AND date <= %s
               ORDER BY date ASC, id ASC''',
            (uid, start_date, end_date),
        )
        out = []
        for r in rows or []:
            out.append(
                {
                    "id": int(r.get("id")),
                    "user_id": int(r.get("user_id")),
                    "date": str(r.get("date")),
                    "content": r.get("content") or "",
                    "reminder_group": r.get("reminder_group") or "",
                    "reminder_message": r.get("reminder_message") or "",
                    "remind_anchor_time": (r.get("remind_anchor_time") or "09:00")[:5],
                    "remind_advance_minutes": int(r.get("remind_advance_minutes") or 0),
                    "remind_count_per_day": int(r.get("remind_count_per_day") or 1),
                    "remind_interval_minutes": int(r.get("remind_interval_minutes") or 60),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                }
            )
        return out

    def get_investment_calendar_item(self, user_id: int, item_id: int):
        """读取单条日历项（带 user_id 隔离），不存在返回 None。"""
        self.ensure_investment_calendar_tables()
        uid = int(user_id)
        row = self.fetch_one(
            '''SELECT id, user_id, date, content, reminder_group, reminder_message,
                      remind_anchor_time, remind_advance_minutes, remind_count_per_day, remind_interval_minutes,
                      created_at, updated_at
               FROM investment_calendar_item
               WHERE id = %s AND user_id = %s
               LIMIT 1''',
            (int(item_id), uid),
        )
        if not row:
            return None
        return {
            "id": int(row.get("id")),
            "user_id": int(row.get("user_id")),
            "date": str(row.get("date")),
            "content": row.get("content") or "",
            "reminder_group": row.get("reminder_group") or "",
            "reminder_message": row.get("reminder_message") or "",
            "remind_anchor_time": (row.get("remind_anchor_time") or "09:00")[:5],
            "remind_advance_minutes": int(row.get("remind_advance_minutes") or 0),
            "remind_count_per_day": int(row.get("remind_count_per_day") or 1),
            "remind_interval_minutes": int(row.get("remind_interval_minutes") or 60),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def create_investment_calendar_item(
        self,
        *,
        user_id: int,
        date: str,
        content: str,
        reminder_group: str | None = None,
        reminder_message: str | None = None,
        remind_anchor_time: str = "09:00",
        remind_advance_minutes: int = 0,
        remind_count_per_day: int = 1,
        remind_interval_minutes: int = 60,
    ):
        """创建日历项并返回实体 dict。"""
        self.ensure_investment_calendar_tables()
        uid = int(user_id)
        self.execute(
            '''INSERT INTO investment_calendar_item (
                   user_id, date, content, reminder_group, reminder_message,
                   remind_anchor_time, remind_advance_minutes, remind_count_per_day, remind_interval_minutes
               )
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (
                uid,
                date,
                content,
                reminder_group,
                reminder_message,
                remind_anchor_time,
                int(remind_advance_minutes),
                int(remind_count_per_day),
                int(remind_interval_minutes),
            ),
        )
        if self.is_sqlite:
            row = self.fetch_one('SELECT last_insert_rowid() AS id')
        else:
            row = self.fetch_one('SELECT LAST_INSERT_ID() AS id')
        new_id = int(row["id"])
        return self.get_investment_calendar_item(uid, new_id)

    def update_investment_calendar_item(
        self,
        *,
        user_id: int,
        item_id: int,
        content: str,
        reminder_group: str | None,
        reminder_message: str | None,
        remind_anchor_time: str,
        remind_advance_minutes: int,
        remind_count_per_day: int,
        remind_interval_minutes: int,
    ) -> bool:
        """更新日历项业务字段，返回是否更新成功（找不到或越权返回 False）。"""
        self.ensure_investment_calendar_tables()
        uid = int(user_id)
        cursor = self.execute(
            '''UPDATE investment_calendar_item
               SET content=%s, reminder_group=%s, reminder_message=%s,
                   remind_anchor_time=%s, remind_advance_minutes=%s,
                   remind_count_per_day=%s, remind_interval_minutes=%s
               WHERE id=%s AND user_id=%s''',
            (
                content,
                reminder_group,
                reminder_message,
                remind_anchor_time,
                int(remind_advance_minutes),
                int(remind_count_per_day),
                int(remind_interval_minutes),
                int(item_id),
                uid,
            ),
        )
        return int(getattr(cursor, "rowcount", 0) or 0) > 0

    def delete_investment_calendar_item(self, user_id: int, item_id: int) -> int:
        """删除日历项，返回删除行数。"""
        self.ensure_investment_calendar_tables()
        uid = int(user_id)
        cursor = self.execute(
            'DELETE FROM investment_calendar_item WHERE id = %s AND user_id = %s',
            (int(item_id), uid),
        )
        return int(getattr(cursor, "rowcount", 0) or 0)

    def create_signal_rule(self, stock_code, stock_name, group_ids_json, signal_type,
                           params_json, message_template, send_type='on_trigger',
                           send_interval_seconds=0, is_active=1):
        """创建一条信号规则，返回 (True, id) 或 (False, error_msg)。"""
        self.ensure_signal_rule_tables()
        try:
            self.execute(
                '''INSERT INTO signal_rule
                   (stock_code, stock_name, group_ids_json, signal_type, params_json, message_template,
                    send_type, send_interval_seconds, is_active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                (
                    stock_code, stock_name, group_ids_json, signal_type, params_json,
                    message_template, send_type, int(send_interval_seconds or 0), int(is_active or 0)
                )
            )
            if self.is_sqlite:
                row = self.fetch_one('SELECT last_insert_rowid() AS id')
                return (True, row['id'])
            row = self.fetch_one('SELECT LAST_INSERT_ID() AS id')
            return (True, row['id'])
        except Exception as e:
            logger.error(f"创建 signal_rule 失败: {str(e)}")
            return (False, str(e))

    def update_signal_rule(self, rule_id: int, stock_name=None, group_ids_json=None,
                           params_json=None, message_template=None, send_type=None,
                           send_interval_seconds=None, is_active=None):
        """更新信号规则，支持部分字段更新。"""
        self.ensure_signal_rule_tables()
        updates = []
        params = []
        if stock_name is not None:
            updates.append("stock_name = %s")
            params.append(stock_name)
        if group_ids_json is not None:
            updates.append("group_ids_json = %s")
            params.append(group_ids_json)
        if params_json is not None:
            updates.append("params_json = %s")
            params.append(params_json)
        if message_template is not None:
            updates.append("message_template = %s")
            params.append(message_template)
        if send_type is not None:
            updates.append("send_type = %s")
            params.append(send_type)
        if send_interval_seconds is not None:
            updates.append("send_interval_seconds = %s")
            params.append(int(send_interval_seconds))
        if is_active is not None:
            updates.append("is_active = %s")
            params.append(int(is_active))
        if not updates:
            return True
        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = f"UPDATE signal_rule SET {', '.join(updates)} WHERE id = %s"
        params.append(int(rule_id))
        self.execute(sql, tuple(params))
        return True

    def get_signal_rules(self, stock_code=None, only_active=True):
        """查询信号规则列表。"""
        self.ensure_signal_rule_tables()
        where = []
        params = []
        if only_active:
            where.append('is_active = %s')
            params.append(1)
        if stock_code is not None:
            where.append('stock_code = %s')
            params.append(stock_code)
        sql = (
            'SELECT id, stock_code, stock_name, group_ids_json, signal_type, params_json,'
            ' message_template, send_type, send_interval_seconds, is_active, created_at, updated_at'
            ' FROM signal_rule'
        )
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY id DESC'
        return self.fetch_all(sql, tuple(params) if params else None)

    def set_signal_rule_active(self, rule_id: int, is_active: int):
        """启用/停用信号规则。"""
        self.ensure_signal_rule_tables()
        self.execute(
            'UPDATE signal_rule SET is_active = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
            (int(is_active), int(rule_id))
        )
        return True

    def delete_signal_rule(self, rule_id: int):
        """删除信号规则。"""
        self.ensure_signal_rule_tables()
        self.execute('DELETE FROM signal_rule WHERE id = %s', (int(rule_id),))
        return True

    def get_signal_rule_states(self, rule_ids):
        """批量读取规则状态，返回 {rule_id: state_json_str}。"""
        self.ensure_signal_rule_state_tables()
        rule_ids = [int(x) for x in (rule_ids or [])]
        if not rule_ids:
            return {}
        placeholders = ",".join(["%s"] * len(rule_ids))
        rows = self.fetch_all(
            f"SELECT rule_id, state_json FROM signal_rule_state WHERE rule_id IN ({placeholders})",
            tuple(rule_ids)
        )
        return {int(r['rule_id']): (r.get('state_json') or '{}') for r in (rows or [])}

    def upsert_signal_rule_state(self, rule_id: int, state_json: str):
        """写入或更新单条规则状态。"""
        self.ensure_signal_rule_state_tables()
        if self.is_sqlite:
            self.execute(
                '''INSERT INTO signal_rule_state (rule_id, state_json, updated_at)
                   VALUES (%s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT(rule_id) DO UPDATE SET
                       state_json=excluded.state_json,
                       updated_at=CURRENT_TIMESTAMP''',
                (int(rule_id), state_json)
            )
        else:
            self.execute(
                '''INSERT INTO signal_rule_state (rule_id, state_json)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE
                       state_json=VALUES(state_json),
                       updated_at=CURRENT_TIMESTAMP''',
                (int(rule_id), state_json)
            )
        return True

    def get_all_message_groups(self, list_type=None):
        """获取所有群组；list_type 为 None 时返回所有类型。返回 [{id, group_id, list_type, chat_list: [str], name?, send_mode?, chat_id?, webhook_url?, sign_secret?, app_id?, app_secret?}, ...]"""
        self.ensure_message_group_tables()
        if list_type is not None:
            rows = self.fetch_all(
                'SELECT id, group_id, list_type, name, send_mode, chat_id, webhook_url, sign_secret, app_id, app_secret '
                'FROM message_group WHERE list_type = %s ORDER BY list_type, group_id',
                (list_type,)
            )
        else:
            rows = self.fetch_all(
                'SELECT id, group_id, list_type, name, send_mode, chat_id, webhook_url, sign_secret, app_id, app_secret '
                'FROM message_group ORDER BY list_type, group_id'
            )
        out = []
        for r in rows:
            lt = (r.get('list_type') or 'weixin')
            chats = []
            if lt in ('weixin', 'wx', 'wechat'):
                chats = self.fetch_all(
                    'SELECT chat_name FROM message_group_chat WHERE group_id = %s ORDER BY sort_order, id',
                    (r['id'],)
                )
            out.append({
                'id': r['id'],
                'group_id': r['group_id'],
                'list_type': lt,
                'chat_list': [c['chat_name'] for c in chats],
                'name': r.get('name'),
                'send_mode': r.get('send_mode') or '',
                'chat_id': r.get('chat_id'),
                'webhook_url': r.get('webhook_url'),
                'sign_secret': r.get('sign_secret'),
                'app_id': r.get('app_id'),
                'app_secret': r.get('app_secret'),
            })
        return out

    def get_message_group_by_id(self, pk_id):
        """根据主键 id 获取一个群组（含 chat_list）"""
        self.ensure_message_group_tables()
        r = self.fetch_one(
            'SELECT id, group_id, list_type, name, send_mode, chat_id, webhook_url, sign_secret, app_id, app_secret '
            'FROM message_group WHERE id = %s',
            (pk_id,)
        )
        if not r:
            return None
        lt = (r.get('list_type') or 'weixin')
        chats = []
        if lt in ('weixin', 'wx', 'wechat'):
            chats = self.fetch_all(
                'SELECT chat_name FROM message_group_chat WHERE group_id = %s ORDER BY sort_order, id',
                (r['id'],)
            )
        return {
            'id': r['id'],
            'group_id': r['group_id'],
            'list_type': lt,
            'chat_list': [c['chat_name'] for c in chats],
            'name': r.get('name'),
            'send_mode': r.get('send_mode') or '',
            'chat_id': r.get('chat_id'),
            'webhook_url': r.get('webhook_url'),
            'sign_secret': r.get('sign_secret'),
            'app_id': r.get('app_id'),
            'app_secret': r.get('app_secret'),
        }

    def create_message_group(
        self,
        group_id,
        list_type='weixin',
        chat_list=None,
        *,
        name=None,
        send_mode=None,
        chat_id=None,
        webhook_url=None,
        sign_secret=None,
        app_id=None,
        app_secret=None,
    ):
        """创建群组并写入 chat_list（仅 weixin）。返回 (True, id) 或 (False, error_msg)。"""
        self.ensure_message_group_tables()
        chat_list = chat_list or []
        try:
            lt = (list_type or 'weixin')
            self.execute(
                'INSERT INTO message_group (group_id, list_type, name, send_mode, chat_id, webhook_url, sign_secret, app_id, app_secret) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (group_id, lt, name, (send_mode or ''), chat_id, webhook_url, sign_secret, app_id, app_secret)
            )
            if self.is_sqlite:
                row = self.fetch_one('SELECT last_insert_rowid() AS id')
                pk = row['id']
            else:
                row = self.fetch_one('SELECT LAST_INSERT_ID() AS id')
                pk = row['id']
            if lt in ('weixin', 'wx', 'wechat'):
                for i, chat_name in enumerate(chat_list):
                    self.execute(
                        'INSERT INTO message_group_chat (group_id, chat_name, sort_order) VALUES (%s, %s, %s)',
                        (pk, (chat_name or '').strip(), i)
                    )
            return (True, pk)
        except Exception as e:
            logger.error(f"创建 message_group 失败: {str(e)}")
            if 'UNIQUE' in str(e) or 'Duplicate' in str(e):
                return (False, '该类型下 group_id 已存在')
            return (False, str(e))

    def update_message_group(
        self,
        pk_id,
        group_id=None,
        list_type=None,
        chat_list=None,
        *,
        name=None,
        send_mode=None,
        chat_id=None,
        webhook_url=None,
        sign_secret=None,
        app_id=None,
        app_secret=None,
    ):
        """更新群组。chat_list 若提供则整体替换（仅 weixin）。返回 (True, None) 或 (False, error_msg)。"""
        self.ensure_message_group_tables()
        try:
            # 先拿当前类型，避免错误地操作 chat 表
            cur = self.fetch_one('SELECT list_type FROM message_group WHERE id = %s', (pk_id,))
            cur_lt = (cur.get('list_type') if isinstance(cur, dict) else None) or 'weixin'
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
                cur_lt = list_type or cur_lt
            if name is not None:
                self.execute(
                    'UPDATE message_group SET name = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (name, pk_id)
                )
            if send_mode is not None:
                self.execute(
                    'UPDATE message_group SET send_mode = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (send_mode, pk_id)
                )
            if chat_id is not None:
                self.execute(
                    'UPDATE message_group SET chat_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (chat_id, pk_id)
                )
            if webhook_url is not None:
                self.execute(
                    'UPDATE message_group SET webhook_url = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (webhook_url, pk_id)
                )
            if sign_secret is not None:
                self.execute(
                    'UPDATE message_group SET sign_secret = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (sign_secret, pk_id)
                )
            if app_id is not None:
                self.execute(
                    'UPDATE message_group SET app_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (app_id, pk_id)
                )
            if app_secret is not None:
                self.execute(
                    'UPDATE message_group SET app_secret = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (app_secret, pk_id)
                )
            if chat_list is not None:
                if (cur_lt or 'weixin') in ('weixin', 'wx', 'wechat'):
                    self.execute('DELETE FROM message_group_chat WHERE group_id = %s', (pk_id,))
                    for i, chat_name in enumerate(chat_list):
                        self.execute(
                            'INSERT INTO message_group_chat (group_id, chat_name, sort_order) VALUES (%s, %s, %s)',
                            (pk_id, (chat_name or '').strip(), i)
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
