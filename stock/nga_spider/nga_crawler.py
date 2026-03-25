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
from typing import List, Optional

import requests

from . import nga_db
from . import nga_parser

logger = logging.getLogger(__name__)


class NGACrawler:
    """单个帖子的爬虫实例"""

    BASE_URL = 'https://bbs.nga.cn/read.php'
    # 官方文档建议用 NGA_WP_JW 以正常获取数据，避免“访客不能直接访问”
    DEFAULT_USER_AGENT = 'NGA_WP_JW'

    def __init__(self, tid: int, thread_cfg: dict, auth_cfg: dict, wx=None, user_agent: str = None, settings: dict = None):
        """
        :param tid:         帖子 ID
        :param thread_cfg:  来自 nga.yaml 的单条帖子配置 dict
        :param auth_cfg:    来自 nga.yaml 的 auth 节点 dict
        :param wx:          wxauto.WeChat 实例（None 则不推送）
        :param user_agent:  HTTP User-Agent，未传时使用 DEFAULT_USER_AGENT
        :param settings:    来自 nga.yaml 的 settings（含 debug_floor_log 等）
        """
        self.tid              = tid
        self.name             = thread_cfg.get('name', str(tid))
        self.watch_author_ids = set(thread_cfg.get('watch_author_ids') or [])
        self.message_group_id = thread_cfg.get('message_group_id')
        self.wx               = wx
        _settings             = settings or {}
        self.debug_floor_log  = bool(_settings.get('debug_floor_log', 0))
        # Referer 模拟从站内访问，避免“访客不能直接访问页面”
        self.headers          = {
            'User-Agent': user_agent or self.DEFAULT_USER_AGENT,
            'Referer':    'https://bbs.nga.cn/',
        }

        self.cookies = {
            'ngaPassportUid': str(auth_cfg.get('ngaPassportUid', '')),
            'ngaPassportCid': str(auth_cfg.get('ngaPassportCid', '')),
            'lastvisit':      '0',
            'lastpath':       f'/read.php?tid={tid}',
        }

        # 从 DB 恢复进度
        progress = nga_db.get_progress(tid)
        self.last_floor_num = progress['last_floor_num']
        self.last_pid       = progress.get('last_pid') or 0
        self.last_page      = progress['last_page']
        logger.info(f'[{self.name}] 恢复进度: last_floor={self.last_floor_num}, last_page={self.last_page}')

    # ─────────────────────────── 公开接口 ────────────────────────────────────

    def crawl_once(self) -> None:
        """
        执行一次增量爬取：
        从 nga_progress 的 last_page 开始，一页页向后爬，直到当前最新页，再继续爬新数据。
        不快进到最后一页，保证中间页都会被爬取。
        """
        # 每轮开始时从 DB 恢复进度
        progress = nga_db.get_progress(self.tid)
        self.last_floor_num = progress['last_floor_num']
        self.last_pid       = progress.get('last_pid') or 0
        self.last_page      = progress['last_page']

        if self.debug_floor_log:
            logger.debug(
                f'[{self.name}] [debug_floor] crawl_once 起点: last_floor_num={self.last_floor_num}, '
                f'last_pid={self.last_pid}, last_page={self.last_page}'
            )

        # 获取当前帖子总页数（仅用于日志），不用于快进
        current_max = self._get_max_pages()
        if current_max is not None and current_max > self.last_page:
            logger.info(f'[{self.name}] 帖子共 {current_max} 页，从第 {self.last_page} 页起逐页补爬至最新')

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

            # 更新进度：每页成功解析后都写入
            if floors:
                last = floors[-1]
                self.last_floor_num = last['floor_num']
                self.last_pid = last['pid']
            else:
                self.last_pid = 0
            nga_db.save_progress(
                self.tid,
                self.last_floor_num,
                self.last_pid,
                page
            )

            if self.debug_floor_log and not floors and page < max_pages:
                logger.debug(
                    f'[{self.name}] [debug_floor] 第 {page} 页解析到 0 条楼层，但未到末页 (max_pages={max_pages})，可能漏楼'
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
                
                resp = requests.post(
                    self.BASE_URL,
                    headers=self.headers,
                    params={'tid': self.tid, 'page': page, 'lite': 'js'},
                    cookies=self.cookies,
                    timeout=15
                )
                #校验响应体是否完整（requests 默认不校验 Content-Length）
                content_length = resp.headers.get('Content-Length')
                if content_length is not None:
                    try:
                        expected_len = int(content_length)
                        if len(resp.content) != expected_len:
                            logger.warning(
                                f'[{self.name}] 第 {page} 页响应不完整: '
                                f'收到 {len(resp.content)} 字节, Content-Length={expected_len}'
                            )
                            time.sleep(2)
                            continue
                    except ValueError:
                        pass
                # 用 content 按 GBK 严格解码，截断的多字节会抛错触发重试
                try:
                    text = resp.content.decode('gbk', errors='strict').replace('	', '')
                except UnicodeDecodeError as e:
                    logger.warning(
                        f'[{self.name}] 第 {page} 页 GBK 解码失败(可能响应被截断): {e}'
                    )
                    time.sleep(2)
                    continue

                if '访客不能直接访问' in text or '访客不能直接访问页面' in text:
                    logger.warning(
                        f'[{self.name}] 收到“访客不能直接访问”，请检查 nga.yaml 中 auth 的 '
                        'ngaPassportUid / ngaPassportCid 是否从浏览器登录后复制且未过期'
                    )
                    return None

                if '服务器忙' in text:
                    logger.warning(f'[{self.name}] 服务器忙，等待重试...')
                    time.sleep(5)
                    continue

                return self._parse_page(text)

            except Exception as e:
                logger.error(f'[{self.name}] 请求第 {page} 页失败 (attempt {attempt+1}): {e}')
                time.sleep(3)

        return None

    def _get_max_pages(self) -> Optional[int]:
        """请求第 1 页仅解析总页数，用于启动时快进到最后一页，返回当前 max_pages 或 None"""
        self.cookies['lastvisit'] = str(int(time.time()) - random.randint(5, 30))
        try:
            resp = requests.get(
                self.BASE_URL,
                headers=self.headers,
                params={'tid': self.tid, 'page': 1, 'lite': 'js'},
                cookies=self.cookies,
                timeout=15
            )
            resp.encoding = 'GBK'
            text = resp.text.replace('\t', '')
            if '访客不能直接访问' in text or '服务器忙' in text:
                return None
            m_rows = re.search(r'"__ROWS":(\d+?),', text, flags=re.S)
            m_rpage = re.search(r'"__R__ROWS_PAGE":(\d+?),', text, flags=re.S)
            if m_rows and m_rpage:
                return math.ceil(int(m_rows.group(1)) / int(m_rpage.group(1)))
        except Exception as e:
            logger.debug(f'[{self.name}] 获取总页数失败: {e}')
        return None

    # ─────────────────────────── 私有：解析 ──────────────────────────────────

    def _parse_page(self, text: str):
        """
        解析 NGA GBK 响应文本，返回 (floors, max_pages)
        floors 是 list of dict
        """
        def _extract(pat: str, name: str):
            m = re.search(pat, text, flags=re.S)
            if m is None:
                raise AttributeError(f'正则未匹配: {name}')
            return m.group(1)

        try:
            user_text  = _extract(r',"__U":(.+?),"__R":', '__U')
            reply_text = _extract(r',"__R":(.+?),"__T":', '__R')
            rows_str   = _extract(r'"__ROWS":(\d+?),', '__ROWS')
            rpage_str  = _extract(r'"__R__ROWS_PAGE":(\d+?),', '__R__ROWS_PAGE')
        except AttributeError as e:
            logger.error(f'[{self.name}] 页面解析失败，字段缺失: {e}')
            snippet = (text[:500] + '...') if len(text) > 500 else text
            logger.warning(f'[{self.name}] 响应片段(供排查): {snippet}')
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

        reply_keys = sorted(reply_dict.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
        if self.debug_floor_log:
            expected_indices = set(range(len(reply_dict)))
            actual_indices = set(int(k) for k in reply_keys if str(k).isdigit())
            if expected_indices != actual_indices:
                missing = expected_indices - actual_indices
                extra = actual_indices - expected_indices
                logger.debug(
                    f'[{self.name}] [debug_floor] __R 键与 range(len) 不一致: '
                    f'缺失下标={missing}, 多出下标={extra}, keys={reply_keys[:30]}...'
                )

        for i in range(len(reply_dict)):
            item = reply_dict.get(str(i))
            if item is None:
                if self.debug_floor_log:
                    logger.debug(f'[{self.name}] [debug_floor] 第 {i} 项 reply_dict.get(str(i)) 为 None，跳过')
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
                elif self.debug_floor_log:
                    logger.debug(
                        f'[{self.name}] [debug_floor] 无 content 且 pid={pid} 不在 comment_buf，'
                        f'该楼层被跳过（可能漏楼）'
                    )

        if self.debug_floor_log and comment_buf:
            logger.debug(
                f'[{self.name}] [debug_floor] 解析结束后 comment_buf 未清空，以下 pid 未被挂到楼层: '
                f'{list(comment_buf.keys())}'
            )
        if self.debug_floor_log and floors:
            floor_nums = [f['floor_num'] for f in floors]
            logger.debug(
                f'[{self.name}] [debug_floor] 本页解析楼层数={len(floors)}, '
                f'floor_num 范围=[{min(floor_nums)}..{max(floor_nums)}], pids={[f["pid"] for f in floors][:20]}...'
            )

        return floors, max_pages

    # ─────────────────────────── 私有：存库 ──────────────────────────────────

    def _save_floors(self, floors: list) -> list:
        """
        将楼层列表写入数据库，跳过已存在的，返回新插入的楼层列表
        同时只返回楼层号 > last_floor_num 的新楼层（断点续爬不重复处理）
        使用单连接批量写入，减少数据库卡顿。
        """
        rows = []
        skipped_by_floor = []
        for f in floors:
            if f['floor_num'] <= self.last_floor_num:
                if self.debug_floor_log:
                    skipped_by_floor.append((f['pid'], f['floor_num']))
                continue
            raw = f['content_raw']
            images = nga_parser.extract_images(raw)
            quote_pid, quote_text, quote_name = nga_parser.extract_quote(raw)
            content_text = nga_parser.strip_bbcode(raw)
            raw_no_quote = re.sub(r'\[quote\].+?\[/quote\]', '', raw, flags=re.S)
            content_text = nga_parser.strip_bbcode(raw_no_quote)
            r = {
                'pid': f['pid'],
                'floor_num': f['floor_num'],
                'author_id': f['author_id'],
                'author_name': f['author_name'],
                'post_date': f['post_date'],
                'content_raw': raw,
                'content_text': content_text,
                'quote_pid': quote_pid,
                'quote_name': quote_name or '',
                'quote_text': quote_text or '',
                'images': json.dumps(images, ensure_ascii=False),
                'score': f['score'],
            }
            rows.append(r)
        if self.debug_floor_log and skipped_by_floor:
            logger.debug(
                f'[{self.name}] [debug_floor] _save_floors 因 floor_num<={self.last_floor_num} 跳过: '
                f'last_floor_num={self.last_floor_num}, 跳过 {len(skipped_by_floor)} 条: {skipped_by_floor[:15]}...'
            )
        if not rows:
            return []
        new_floors = nga_db.save_floors_batch(self.tid, rows)
        if self.debug_floor_log and len(new_floors) != len(rows):
            logger.debug(
                f'[{self.name}] [debug_floor] 本页待写入 {len(rows)} 条，实际新插入 {len(new_floors)} 条 '
                f'（重复 pid 被 INSERT IGNORE 忽略）'
            )
        for f in new_floors:
            if isinstance(f.get('images'), str):
                try:
                    f['images'] = json.loads(f['images'])
                except Exception:
                    f['images'] = []
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
        # 0 / '0' / None 均视为未配置群组，不发送
        if group_id is None or group_id == 0 or group_id == '0':
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
            quote_name   = floor.get('quote_name'),
            images       = floor.get('images', []),
            thread_name  = self.name,
        )

        self._send_wx(msg, group_id)
        nga_db.mark_sent(self.tid, pid, group_id)

    def _send_wx(self, msg: str, group_id) -> None:
        """按 NOTIFY.channel 走统一通知（飞书 / 微信）。"""
        try:
            import sys
            import os

            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from Managers.notify_channel import send_notify_to_group

            send_notify_to_group(int(group_id), msg)
            logger.info("NGA 已投递通知 group_id=%s pid=%s", group_id, msg[:40] if msg else "")
        except Exception as e:
            logger.error("NGA 通知投递失败: %s", e, exc_info=True)

    # ─────────────────────────── 工具 ────────────────────────────────────────

    @staticmethod
    def _get_username(user_dict: dict, author_id: int) -> str:
        uid_str = str(author_id)
        if uid_str in user_dict and 'username' in user_dict[uid_str]:
            return str(user_dict[uid_str]['username'])
        return f'uid:{author_id}'
