# -*- coding: UTF-8 -*-
"""
NGA 爬虫 数据库操作封装
复用项目的 database.Database 连接，管理 NGA 相关表
"""
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
        # ── 楼层存储表 ──────────────────────────────────────────────────────────
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
                quote_text  TEXT        COMMENT '引用内容摘要',
                images      TEXT        COMMENT '图片URL列表，JSON格式',
                score       INT         DEFAULT 0 COMMENT '赞数',
                created_at  TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_pid (pid)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='NGA帖子楼层';
        """)

        # ── 消息发送记录表（防止重复推送）──────────────────────────────────────
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

        # ── 爬取进度表（记录每个帖子最后爬到的楼层，支持断点续爬）────────────
        db.execute("""
            CREATE TABLE IF NOT EXISTS nga_progress (
                tid             BIGINT      PRIMARY KEY COMMENT '帖子ID',
                last_floor_num  INT         DEFAULT 0 COMMENT '最后爬取的楼层号',
                last_pid        BIGINT      DEFAULT 0 COMMENT '最后爬取的pid',
                last_page       INT         DEFAULT 1 COMMENT '最后爬取的页码',
                updated_at      TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='NGA爬取进度';
        """)

        db.commit()
        logger.info("NGA 数据库表初始化完成")
    except Exception as e:
        logger.error(f"初始化 NGA 表失败: {e}")
        raise
    finally:
        db.close()


# ─────────────────────────── 楼层操作 ───────────────────────────────────────

def save_floor(tid: int, pid: int, floor_num: int, author_id: int,
               author_name: str, post_date: str, content_raw: str,
               content_text: str, quote_pid: int, quote_text: str,
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
                 content_raw, content_text, quote_pid, quote_text, images, score)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        cursor = db.execute(sql, (
            tid, pid, floor_num, author_id, author_name, post_date,
            content_raw, content_text, quote_pid, quote_text, images, score
        ))
        db.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"保存楼层失败 pid={pid}: {e}")
        return False
    finally:
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
        db.commit()
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
                'last_floor_num': row['last_floor_num'],
                'last_pid':       row['last_pid'],
                'last_page':      row['last_page'],
            }
        return {'last_floor_num': 0, 'last_pid': 0, 'last_page': 1}
    finally:
        db.close()


def save_progress(tid: int, last_floor_num: int, last_pid: int, last_page: int) -> None:
    """更新爬取进度（UPSERT）"""
    db = Database.Create()
    try:
        db.execute("""
            INSERT INTO nga_progress (tid, last_floor_num, last_pid, last_page)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                last_floor_num = VALUES(last_floor_num),
                last_pid       = VALUES(last_pid),
                last_page      = VALUES(last_page)
        """, (tid, last_floor_num, last_pid, last_page))
        db.commit()
    except Exception as e:
        logger.error(f"保存进度失败 tid={tid}: {e}")
    finally:
        db.close()
