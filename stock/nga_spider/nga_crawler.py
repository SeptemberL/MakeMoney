# -*- coding: UTF-8 -*-
"""
NGA 帖子爬虫核心
- 单帖增量爬取（从 DB 记录的上次进度页码开始）
- 解析 NGA JSON 响应，提取楼层信息
- 存库 + 监控用户触发微信推送
"""
import re
import json
import time
import math
import random
import logging
import platform
from typing import List, Optional

import requests

import nga_db
import nga_parser

logger = logging.getLogger(__name__)


class NGACrawler:
    """单个帖子的爬虫实例"""

    BASE_URL = 'https://bbs.nga.cn/read.php'
    DEFAULT_USER_AGENT = 'Nga_Official/80023'

    def __init__(self, tid: int, thread_cfg: dict, auth_cfg: dict, wx=None, user_agent: str = None):
        """
        :param tid:         帖子 ID
        :param thread_cfg:  来自 nga.yaml 的单条帖子配置 dict
        :param auth_cfg:    来自 nga.yaml 的 auth 节点 dict
        :param wx:          wxauto.WeChat 实例（None 则不推送）
        :param user_agent:  HTTP User-Agent，未传时使用 DEFAULT_USER_AGENT
        """
        self.tid              = tid
        self.name             = thread_cfg.get('name', str(tid))
        self.watch_author_ids = set(thread_cfg.get('watch_author_ids') or [])
        self.message_group_id = thread_cfg.get('message_group_id')
        self.wx               = wx
        self.headers          = {'User-agent': user_agent or self.DEFAULT_USER_AGENT}

        self.cookies = {
            'ngaPassportUid': str(auth_cfg.get('ngaPassportUid', '')),
            'ngaPassportCid': str(auth_cfg.get('ngaPassportCid', '')),
            'lastvisit':      '0',
            'lastpath':       f'/read.php?tid={tid}',
        }

        # 从 DB 恢复进度
        progress = nga_db.get_progress(tid)
        self.last_floor_num = progress['last_floor_num']
        self.last_page      = progress['last_page']
        logger.info(f'[{self.name}] 恢复进度: last_floor={self.last_floor_num}, last_page={self.last_page}')

    # ─────────────────────────── 公开接口 ────────────────────────────────────

    def crawl_once(self) -> None:
        """
        执行一次增量爬取：
        从 last_page 开始，爬到最新页为止
        """
        page = self.last_page
        while True:
            result = self._fetch_page(page)
            if result is None:
                logger.warning(f'[{self.name}] 第 {page} 页请求失败，本次跳过')
                break

            floors, max_pages = result
            new_floors = self._save_floors(floors)

            # 对新楼层中的监控用户进行推送
            for floor in new_floors:
                self._maybe_notify(floor)

            # 更新进度
            if floors:
                last = floors[-1]
                self.last_floor_num = last['floor_num']
                nga_db.save_progress(
                    self.tid,
                    last['floor_num'],
                    last['pid'],
                    page
                )

            logger.info(f'[{self.name}] 第 {page}/{max_pages} 页，'
                        f'新增 {len(new_floors)} 楼')

            if page >= max_pages:
                # 已到最后一页，记录最后一页供下次从这里开始
                nga_db.save_progress(
                    self.tid,
                    self.last_floor_num,
                    0,
                    max_pages          # 下次从最后页继续，新回复会出现在这一页
                )
                break

            page += 1
            time.sleep(0.3)  # 翻页间礼貌等待

    # ─────────────────────────── 私有：请求 ──────────────────────────────────

    def _fetch_page(self, page: int, retries: int = 3):
        """
        请求 NGA 单页并解析，返回 (floors_list, max_pages) 或 None
        """
        self.cookies['lastvisit'] = str(int(time.time()) - random.randint(5, 30))

        for attempt in range(retries):
            try:
                resp = requests.get(
                    self.BASE_URL,
                    headers=self.cookies and self.headers,
                    params={'tid': self.tid, 'page': page, 'lite': 'js'},
                    cookies=self.cookies,
                    timeout=15
                )
                resp.encoding = 'GBK'
                text = resp.text.replace('\t', '')

                if '服务器忙' in text:
                    logger.warning(f'[{self.name}] 服务器忙，等待重试...')
                    time.sleep(5)
                    continue

                return self._parse_page(text)

            except Exception as e:
                logger.error(f'[{self.name}] 请求第 {page} 页失败 (attempt {attempt+1}): {e}')
                time.sleep(3)

        return None

    # ─────────────────────────── 私有：解析 ──────────────────────────────────

    def _parse_page(self, text: str):
        """
        解析 NGA GBK 响应文本，返回 (floors, max_pages)
        floors 是 list of dict
        """
        try:
            user_text  = re.search(r',"__U":(.+?),"__R":', text, flags=re.S).group(1)
            reply_text = re.search(r',"__R":(.+?),"__T":', text, flags=re.S).group(1)
            rows_str   = re.search(r'"__ROWS":(\d+?),',    text, flags=re.S).group(1)
            rpage_str  = re.search(r'"__R__ROWS_PAGE":(\d+?),', text, flags=re.S).group(1)
        except AttributeError as e:
            logger.error(f'[{self.name}] 页面解析失败，字段缺失: {e}')
            return None

        # 匿名用户名转换
        user_text  = nga_parser.anony(user_text)

        try:
            user_dict  = json.loads(user_text,  strict=False)
            reply_dict = json.loads(reply_text, strict=False)
        except json.JSONDecodeError as e:
            logger.error(f'[{self.name}] JSON 解析失败: {e}')
            return None

        max_pages = math.ceil(int(rows_str) / int(rpage_str))

        # ── 解析楼层 ──────────────────────────────────────────────────────────
        floors = []
        comment_buf = {}  # pid -> list of 评论 floor dict

        for i in range(len(reply_dict)):
            item = reply_dict.get(str(i))
            if item is None:
                continue

            # 评论楼层（挂在父楼下的子回复）
            if 'comment' in item:
                for ckey in item['comment']:
                    c = item['comment'][ckey]
                    c_author_id = int(c['authorid'])
                    c_uname = self._get_username(user_dict, c_author_id)
                    comment_buf[int(c['pid'])] = {
                        'tid':         self.tid,
                        'pid':         int(c['pid']),
                        'floor_num':   int(item.get('lou', 0)),  # 归属到父楼层号
                        'author_id':   c_author_id,
                        'author_name': c_uname,
                        'post_date':   c.get('postdate', ''),
                        'content_raw': '[评论] ' + str(c.get('content', '')),
                        'score':       int(c.get('score', 0)),
                    }

            if 'content' in item:
                # 正经楼层
                author_id = int(item.get('authorid', 0))
                floor_data = {
                    'tid':         self.tid,
                    'pid':         int(item['pid']),
                    'floor_num':   int(item.get('lou', 0)),
                    'author_id':   author_id,
                    'author_name': self._get_username(user_dict, author_id),
                    'post_date':   item.get('postdate', ''),
                    'content_raw': str(item['content']),
                    'score':       int(item.get('score', 0)),
                }
                floors.append(floor_data)
            else:
                # 评论楼层本体（无 content，从 comment_buf 取）
                pid = int(item['pid'])
                if pid in comment_buf:
                    floors.append(comment_buf.pop(pid))

        return floors, max_pages

    # ─────────────────────────── 私有：存库 ──────────────────────────────────

    def _save_floors(self, floors: list) -> list:
        """
        将楼层列表写入数据库，跳过已存在的，返回新插入的楼层列表
        同时只返回楼层号 > last_floor_num 的新楼层（断点续爬不重复处理）
        """
        new_floors = []
        for f in floors:
            # 只处理上次进度之后的楼层（避免最后一页重复推送）
            if f['floor_num'] <= self.last_floor_num:
                continue

            raw = f['content_raw']

            # 提取辅助信息
            images       = nga_parser.extract_images(raw)
            quote_pid, quote_text = nga_parser.extract_quote(raw)
            content_text = nga_parser.strip_bbcode(raw)

            # 去掉原始 BBCode 里的 [quote] 块再做纯文本，避免引用内容污染正文
            raw_no_quote = re.sub(r'\[quote\].+?\[/quote\]', '', raw, flags=re.S)
            content_text = nga_parser.strip_bbcode(raw_no_quote)

            is_new = nga_db.save_floor(
                tid          = self.tid,
                pid          = f['pid'],
                floor_num    = f['floor_num'],
                author_id    = f['author_id'],
                author_name  = f['author_name'],
                post_date    = f['post_date'],
                content_raw  = raw,
                content_text = content_text,
                quote_pid    = quote_pid,
                quote_text   = quote_text,
                images       = json.dumps(images, ensure_ascii=False),
                score        = f['score'],
            )

            if is_new:
                f['content_text'] = content_text
                f['quote_pid']    = quote_pid
                f['quote_text']   = quote_text
                f['images']       = images
                new_floors.append(f)

        return new_floors

    # ─────────────────────────── 私有：推送 ──────────────────────────────────

    def _maybe_notify(self, floor: dict) -> None:
        """
        判断是否需要推送：
        1. watch_author_ids 为空 → 推送所有人
        2. watch_author_ids 非空 → 只推送列表内的 author_id
        且该 (pid, group_id) 未发送过
        """
        author_id = floor['author_id']
        pid       = floor['pid']

        # 过滤监控用户
        if self.watch_author_ids and author_id not in self.watch_author_ids:
            return

        group_id = self.message_group_id
        if group_id is None:
            return

        # 防止重复发送
        if nga_db.is_sent(pid, group_id):
            return

        msg = nga_parser.build_wx_message(
            tid          = self.tid,
            floor_num    = floor['floor_num'],
            pid          = pid,
            author_name  = floor['author_name'],
            post_date    = floor.get('post_date', ''),
            content_text = floor.get('content_text', ''),
            quote_text   = floor.get('quote_text'),
            images       = floor.get('images', []),
            thread_name  = self.name,
        )

        self._send_wx(msg, group_id)
        nga_db.mark_sent(self.tid, pid, group_id)

    def _send_wx(self, msg: str, group_id) -> None:
        """通过 WXGroupManager 发送微信消息到对应群组"""
        try:
            import sys, os
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from Managers.wx_group_manager import WXGroupManager
            mgr = WXGroupManager()
            chat_list = mgr.find_wx_group(group_id)

            if not chat_list:
                logger.warning(f'群组 {group_id} 未找到对应聊天列表，跳过推送')
                return

            if self.wx is None:
                logger.info(f'[模拟推送] 群组{group_id}:\n{msg}')
                return

            for chat in chat_list:
                try:
                    self.wx.SendMsg(msg, who=chat)
                    logger.info(f'已推送到 {chat}: pid={msg[:30]}...')
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f'发送到 {chat} 失败: {e}')

        except Exception as e:
            logger.error(f'微信推送失败: {e}')

    # ─────────────────────────── 工具 ────────────────────────────────────────

    @staticmethod
    def _get_username(user_dict: dict, author_id: int) -> str:
        uid_str = str(author_id)
        if uid_str in user_dict and 'username' in user_dict[uid_str]:
            return str(user_dict[uid_str]['username'])
        return f'uid:{author_id}'
