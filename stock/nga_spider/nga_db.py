# -*- coding: UTF-8 -*-
"""
NGA 爬虫 数据库操作封装
复用项目的 database.Database 连接，管理 NGA 相关表
"""
import json
import logging
import sys
import os

# 将项目根目录加入路径，以便复用 database.py
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from database.database import Database

logger = logging.getLogger(__name__)


def init_tables():
    """
    初始化 NGA 相关数据库表，幂等操作（不存在才创建）
    """
    db = Database.Create()
    try:
        if db.is_sqlite:
            _init_tables_sqlite(db)
        else:
            _init_tables_mysql(db)
        db.commit()
        logger.info("NGA 数据库表初始化完成")
    except Exception as e:
        logger.error(f"初始化 NGA 表失败: {e}")
        raise
    finally:
        db.close()


def _init_tables_sqlite(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS nga_floors (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tid         INTEGER NOT NULL,
            pid         INTEGER NOT NULL UNIQUE,
            floor_num   INTEGER NOT NULL,
            author_id   INTEGER NOT NULL,
            author_name TEXT    NOT NULL,
            post_date   TEXT,
            content_raw TEXT,
            content_text TEXT,
            quote_pid   INTEGER DEFAULT NULL,
            quote_name  TEXT    DEFAULT NULL,
            quote_text  TEXT,
            images      TEXT,
            score       INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_tid_floor ON nga_floors (tid, floor_num)")
    except Exception:
        pass
    db.execute("""
        CREATE TABLE IF NOT EXISTS nga_sent_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            tid              INTEGER NOT NULL,
            pid              INTEGER NOT NULL,
            message_group_id TEXT    NOT NULL,
            sent_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pid, message_group_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS nga_progress (
            tid             INTEGER PRIMARY KEY,
            last_floor_num  INTEGER DEFAULT 0,
            last_pid        INTEGER DEFAULT 0,
            last_page       INTEGER DEFAULT 1,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS nga_thread_config (
            tid              INTEGER PRIMARY KEY,
            name             TEXT    DEFAULT '',
            watch_author_ids TEXT,
            message_group_id TEXT    DEFAULT '0',
            auto_run         INTEGER DEFAULT 1,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _init_tables_mysql(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS nga_floors (
            id          BIGINT AUTO_INCREMENT PRIMARY KEY,
            tid         BIGINT      NOT NULL COMMENT '帖子ID',
            pid         BIGINT      NOT NULL COMMENT '楼层pid（NGA唯一）',
            floor_num   INT         NOT NULL COMMENT '楼层号（0=主楼）',
            author_id   BIGINT      NOT NULL COMMENT '发言人authorId',
            author_name VARCHAR(64) NOT NULL COMMENT '发言人昵称（含匿名转换后）',
            post_date   VARCHAR(32) COMMENT '发言时间字符串',
            content_raw TEXT        COMMENT '原始BBCode内容',
            content_text TEXT       COMMENT '去除BBCode后的纯文本摘要',
            quote_pid   BIGINT      DEFAULT NULL COMMENT '引用的pid（若有）',
            quote_name  VARCHAR(64) DEFAULT NULL COMMENT '被引用楼层作者名',
            quote_text  TEXT        COMMENT '引用内容摘要',
            images      TEXT        COMMENT '图片URL列表，JSON格式',
            score       INT         DEFAULT 0 COMMENT '赞数',
            created_at  TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_pid (pid)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='NGA帖子楼层';
    """)
    try:
        db.execute("CREATE INDEX idx_tid_floor ON nga_floors (tid, floor_num)")
    except Exception:
        pass
    try:
        db.execute("""
            ALTER TABLE nga_floors
            ADD COLUMN quote_name VARCHAR(64) DEFAULT NULL COMMENT '被引用楼层作者名' AFTER quote_pid
        """)
    except Exception:
        pass
    db.execute("""
        CREATE TABLE IF NOT EXISTS nga_sent_log (
            id              BIGINT AUTO_INCREMENT PRIMARY KEY,
            tid             BIGINT      NOT NULL COMMENT '帖子ID',
            pid             BIGINT      NOT NULL COMMENT '楼层pid',
            message_group_id VARCHAR(32) NOT NULL COMMENT '发送的群组ID',
            sent_at         TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_pid_group (pid, message_group_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='NGA消息推送记录';
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS nga_progress (
            tid             BIGINT      PRIMARY KEY COMMENT '帖子ID',
            last_floor_num  INT         DEFAULT 0 COMMENT '最后爬取的楼层号',
            last_pid        BIGINT      DEFAULT 0 COMMENT '最后爬取的pid',
            last_page       INT         DEFAULT 1 COMMENT '最后爬取的页码',
            updated_at      TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='NGA爬取进度';
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS nga_thread_config (
            tid                 BIGINT      PRIMARY KEY COMMENT '帖子ID',
            name                VARCHAR(255) DEFAULT '' COMMENT '帖子备注名',
            watch_author_ids    TEXT        COMMENT '关注的authorId列表，JSON数组',
            message_group_id    VARCHAR(32) DEFAULT '0' COMMENT '消息群组ID',
            auto_run            TINYINT(1)  DEFAULT 1 COMMENT '1=程序启动后默认运行监控，0=不自动运行',
            created_at          TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
            updated_at          TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='NGA帖子监控配置';
    """)


# ─────────────────────────── 楼层操作 ───────────────────────────────────────

def save_floor(tid: int, pid: int, floor_num: int, author_id: int,
               author_name: str, post_date: str, content_raw: str,
               content_text: str, quote_pid: int, quote_name: str, quote_text: str,
               images: str, score: int) -> bool:
    """
    保存一个楼层，已存在（同 pid）则忽略（INSERT IGNORE）
    返回 True 表示新插入，False 表示已存在
    """
    db = Database.Create()
    try:
        sql = """
            INSERT IGNORE INTO nga_floors
                (tid, pid, floor_num, author_id, author_name, post_date,
                 content_raw, content_text, quote_pid, quote_name, quote_text, images, score)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        cursor = db.execute(sql, (
            tid, pid, floor_num, author_id, author_name, post_date,
            content_raw, content_text, quote_pid, quote_name or None, quote_text, images, score
        ))
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"保存楼层失败 pid={pid}: {e}")
        return False
    finally:
        db.close()


def save_floors_batch(tid: int, rows: list) -> list:
    """
    批量写入楼层，单连接单事务，减少连接与 commit 次数。
    rows: 每项为 dict，含 pid, floor_num, author_id, author_name, post_date,
          content_raw, content_text, quote_pid, quote_name, quote_text, images(JSON str), score。
    返回本次新插入的 floor 列表（与 rows 中项为同一引用，便于调用方打推送）。
    """
    if not rows:
        return []
    db = Database.Create()
    cursor = None
    try:
        conn = db.get_connection()
        if db.is_sqlite:
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(dictionary=True, buffered=True)
        sql = db.adapt_sql("""
            INSERT IGNORE INTO nga_floors
                (tid, pid, floor_num, author_id, author_name, post_date,
                 content_raw, content_text, quote_pid, quote_name, quote_text, images, score)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """)
        new_floors = []
        for r in rows:
            cursor.execute(sql, (
                tid,
                r['pid'],
                r['floor_num'],
                r['author_id'],
                r['author_name'],
                r['post_date'],
                r['content_raw'],
                r['content_text'],
                r.get('quote_pid') or 0,
                r.get('quote_name') or None,
                r.get('quote_text') or '',
                r.get('images') or '[]',
                r.get('score', 0),
            ))
            if cursor.rowcount > 0:
                new_floors.append(r)
        conn.commit()
        return new_floors
    except Exception as e:
        logger.error(f"批量保存楼层失败 tid={tid}: {e}")
        if db and db.get_connection():
            try:
                db.rollback()
            except Exception:
                pass
        return []
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        db.close()


def floor_exists(pid: int) -> bool:
    """检查 pid 是否已存在"""
    db = Database.Create()
    try:
        row = db.fetch_one("SELECT 1 FROM nga_floors WHERE pid=%s LIMIT 1", (pid,))
        return row is not None
    finally:
        db.close()


# ─────────────────────────── 发送记录 ────────────────────────────────────────

def is_sent(pid: int, message_group_id) -> bool:
    """检查某楼层是否已推送过指定群组"""
    db = Database.Create()
    try:
        row = db.fetch_one(
            "SELECT 1 FROM nga_sent_log WHERE pid=%s AND message_group_id=%s LIMIT 1",
            (pid, str(message_group_id))
        )
        return row is not None
    finally:
        db.close()


def mark_sent(tid: int, pid: int, message_group_id) -> None:
    """标记某楼层已推送指定群组"""
    db = Database.Create()
    try:
        db.execute(
            "INSERT IGNORE INTO nga_sent_log (tid, pid, message_group_id) VALUES (%s,%s,%s)",
            (tid, pid, str(message_group_id))
        )
    except Exception as e:
        logger.error(f"记录发送日志失败 pid={pid}: {e}")
    finally:
        db.close()


# ─────────────────────────── 进度管理 ────────────────────────────────────────

def get_progress(tid: int) -> dict:
    """
    获取某帖子的爬取进度
    返回 {'last_floor_num': int, 'last_pid': int, 'last_page': int}
    """
    db = Database.Create()
    try:
        row = db.fetch_one("SELECT * FROM nga_progress WHERE tid=%s", (tid,))
        if row:
            return {
                'last_floor_num': int(row['last_floor_num'] or 0),
                'last_pid':       int(row['last_pid'] or 0),
                'last_page':      int(row['last_page'] or 1),
            }
        return {'last_floor_num': 0, 'last_pid': 0, 'last_page': 1}
    finally:
        db.close()


def save_progress(tid: int, last_floor_num: int, last_pid: int, last_page: int) -> None:
    """更新爬取进度（UPSERT），且仅当新进度更大时才更新，避免被小页码覆盖导致重复爬前几页"""
    db = Database.Create()
    try:
        if db.is_sqlite:
            db.execute("""
                INSERT INTO nga_progress (tid, last_floor_num, last_pid, last_page)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(tid) DO UPDATE SET
                    last_floor_num = MAX(nga_progress.last_floor_num, excluded.last_floor_num),
                    last_pid       = CASE WHEN excluded.last_page > nga_progress.last_page
                                          THEN excluded.last_pid ELSE nga_progress.last_pid END,
                    last_page      = MAX(nga_progress.last_page, excluded.last_page)
            """, (tid, last_floor_num, last_pid, last_page))
        else:
            db.execute("""
                INSERT INTO nga_progress (tid, last_floor_num, last_pid, last_page)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    last_floor_num = GREATEST(last_floor_num, VALUES(last_floor_num)),
                    last_pid       = IF(VALUES(last_page) > last_page, VALUES(last_pid), last_pid),
                    last_page      = GREATEST(last_page, VALUES(last_page))
            """, (tid, last_floor_num, last_pid, last_page))
    except Exception as e:
        logger.error(f"保存进度失败 tid={tid}: {e}")
    finally:
        db.close()


# ─────────────────────────── 帖子监控配置（nga_thread_config）────────────────

def get_thread_configs(only_auto_run: bool = True):
    """
    从数据库读取帖子监控配置，返回与 nga.yaml 中单条 thread 结构兼容的 list[dict]。
    :param only_auto_run: True 只返回 auto_run=1 的帖子（用于程序启动后自动监控）
    """
    db = Database.Create()
    try:
        if only_auto_run:
            rows = db.fetch_all(
                "SELECT tid, name, watch_author_ids, message_group_id FROM nga_thread_config WHERE auto_run = 1 ORDER BY created_at ASC"
            )
        else:
            rows = db.fetch_all(
                "SELECT tid, name, watch_author_ids, message_group_id, auto_run FROM nga_thread_config ORDER BY created_at ASC"
            )
        out = []
        for row in rows:
            watch_ids = []
            if row.get('watch_author_ids'):
                try:
                    watch_ids = json.loads(row['watch_author_ids'])
                except (TypeError, json.JSONDecodeError):
                    pass
            out.append({
                'tid': int(row['tid']),
                'name': row.get('name') or '',
                'watch_author_ids': watch_ids,
                'message_group_id': row.get('message_group_id'),
                'enabled': True,
            })
            if not only_auto_run and 'auto_run' in row:
                out[-1]['auto_run'] = bool(row['auto_run'])
        return out
    finally:
        db.close()


# ─────────────────────────── 已抓取楼层查询（含发送状态） ─────────────────────

def get_floors_with_sent_for_group(tid: int, message_group_id, limit: int = 200, offset: int = 0) -> list:
    """
    查询某帖子的楼层列表，并标记在指定群组下是否已发送。
    返回按 floor_num 倒序排列的 list[dict]，每项包含：
      - tid, pid, floor_num, author_id, author_name, post_date,
        content_text, quote_text, images(list), score, created_at
      - sent: True/False （该群组下是否已发送）
    """
    db = Database.Create()
    try:
        sql = """
            SELECT
                f.*,
                CASE WHEN s.id IS NULL THEN 0 ELSE 1 END AS sent
            FROM nga_floors f
            LEFT JOIN nga_sent_log s
              ON f.pid = s.pid
             AND s.message_group_id = %s
            WHERE f.tid = %s
            ORDER BY f.floor_num DESC
            LIMIT %s OFFSET %s
        """
        rows = db.fetch_all(sql, (str(message_group_id), tid, limit, offset))
        out = []
        for r in rows:
            images = []
            if r.get('images'):
                try:
                    images = json.loads(r['images'])
                except (TypeError, json.JSONDecodeError):
                    images = []
            out.append({
                'tid': int(r['tid']),
                'pid': int(r['pid']),
                'floor_num': int(r['floor_num']),
                'author_id': int(r['author_id']),
                'author_name': r.get('author_name') or '',
                'post_date': r.get('post_date') or '',
                'content_text': r.get('content_text') or '',
                'quote_text': r.get('quote_text') or '',
                'images': images,
                'score': int(r.get('score') or 0),
                'created_at': r.get('created_at'),
                'sent': bool(r.get('sent')),
            })
        return out
    finally:
        db.close()


def get_floor_by_tid_pid(tid: int, pid: int) -> dict | None:
    """
    获取单个楼层记录，若不存在返回 None。
    返回字段结构与 get_floors_with_sent_for_group 中单条一致（但不含 sent）。
    """
    db = Database.Create()
    try:
        row = db.fetch_one(
            "SELECT * FROM nga_floors WHERE tid = %s AND pid = %s LIMIT 1",
            (tid, pid)
        )
        if not row:
            return None
        images = []
        if row.get('images'):
            try:
                images = json.loads(row['images'])
            except (TypeError, json.JSONDecodeError):
                images = []
        return {
            'tid': int(row['tid']),
            'pid': int(row['pid']),
            'floor_num': int(row['floor_num']),
            'author_id': int(row['author_id']),
            'author_name': row.get('author_name') or '',
            'post_date': row.get('post_date') or '',
            'content_text': row.get('content_text') or '',
            'quote_text': row.get('quote_text') or '',
            'images': images,
            'score': int(row.get('score') or 0),
            'created_at': row.get('created_at'),
        }
    finally:
        db.close()


def get_thread_config(tid: int):
    """
    获取单条帖子监控配置，不存在返回 None。
    返回与 get_thread_configs 中单条结构一致的 dict（含 tid, name, watch_author_ids, message_group_id, auto_run）。
    """
    db = Database.Create()
    try:
        row = db.fetch_one(
            "SELECT tid, name, watch_author_ids, message_group_id, auto_run FROM nga_thread_config WHERE tid = %s",
            (tid,)
        )
        if not row:
            return None
        watch_ids = []
        if row.get('watch_author_ids'):
            try:
                watch_ids = json.loads(row['watch_author_ids'])
            except (TypeError, json.JSONDecodeError):
                pass
        return {
            'tid': int(row['tid']),
            'name': row.get('name') or '',
            'watch_author_ids': watch_ids,
            'message_group_id': row.get('message_group_id'),
            'auto_run': bool(row.get('auto_run')),
        }
    finally:
        db.close()


def save_thread_config(tid: int, name: str = '', watch_author_ids=None, message_group_id=None, auto_run: bool = True) -> None:
    """保存或更新一条帖子监控配置（UPSERT）"""
    if watch_author_ids is None:
        watch_author_ids = []
    db = Database.Create()
    try:
        ids_json = json.dumps(watch_author_ids, ensure_ascii=False)
        params = (tid, name, ids_json, message_group_id or 0, 1 if auto_run else 0)
        if db.is_sqlite:
            db.execute("""
                INSERT INTO nga_thread_config (tid, name, watch_author_ids, message_group_id, auto_run)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(tid) DO UPDATE SET
                    name = excluded.name,
                    watch_author_ids = excluded.watch_author_ids,
                    message_group_id = excluded.message_group_id,
                    auto_run = excluded.auto_run
            """, params)
        else:
            db.execute("""
                INSERT INTO nga_thread_config (tid, name, watch_author_ids, message_group_id, auto_run)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    watch_author_ids = VALUES(watch_author_ids),
                    message_group_id = VALUES(message_group_id),
                    auto_run = VALUES(auto_run)
            """, params)
    except Exception as e:
        logger.error(f"保存帖子配置失败 tid={tid}: {e}")
    finally:
        db.close()


def sync_threads_from_yaml(threads: list) -> None:
    """
    将 nga.yaml 中的 threads 列表同步到数据库（按 tid 插入或更新）。
    用于首次启动或从 yaml 迁移到 DB。
    """
    for th in threads:
        tid = int(th['tid'])
        name = th.get('name', '')
        watch_author_ids = th.get('watch_author_ids') or []
        message_group_id = th.get('message_group_id', 0)
        auto_run = bool(th.get('enabled', True))
        save_thread_config(tid=tid, name=name, watch_author_ids=watch_author_ids,
                          message_group_id=message_group_id, auto_run=auto_run)
    logger.info("已从 yaml 同步 %d 条帖子配置到数据库", len(threads))


def set_thread_auto_run(tid: int):
    """
    切换帖子的 auto_run 状态，返回切换后的新状态（True/False）。
    若 tid 不存在返回 None。
    """
    db = Database.Create()
    try:
        row = db.fetch_one("SELECT auto_run FROM nga_thread_config WHERE tid = %s", (tid,))
        if not row:
            return None
        current = bool(row.get('auto_run'))
        new = not current
        db.execute("UPDATE nga_thread_config SET auto_run = %s WHERE tid = %s", (1 if new else 0, tid))
        return new
    except Exception as e:
        logger.error(f"切换 auto_run 失败 tid={tid}: {e}")
        return None
    finally:
        db.close()


def delete_thread_config(tid: int) -> bool:
    """
    删除一条帖子监控配置。成功返回 True，不存在或失败返回 False。
    """
    db = Database.Create()
    try:
        cursor = db.execute("DELETE FROM nga_thread_config WHERE tid = %s", (tid,))
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"删除帖子配置失败 tid={tid}: {e}")
        return False
    finally:
        db.close()
