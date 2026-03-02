# -*- coding: UTF-8 -*-
"""
NGA 爬虫单次测试脚本
- 使用 configs/nga.yaml 配置
- 只爬取配置中的第一个启用帖子，执行一次 crawl_once
- 不启动微信推送（仅爬取并落库）
"""
import sys
import logging
from pathlib import Path

# 项目根目录（stock/）
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

import yaml
import nga_db
from nga_crawler import NGACrawler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger('nga_test')


def load_config(config_path: str = None) -> dict:
    """加载 nga.yaml，默认使用项目 configs/nga.yaml"""
    path = config_path or str(_PROJECT_DIR / 'configs' / 'nga.yaml')
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def main():
    config_path = str(_PROJECT_DIR / 'configs' / 'nga.yaml')
    logger.info('使用配置: %s', config_path)

    cfg = load_config(config_path)
    auth_cfg = cfg.get('auth', {})
    threads = cfg.get('threads', [])

    if not threads:
        logger.warning('nga.yaml 中 threads 为空，无帖子可爬')
        return

    # 取第一个启用的帖子
    thread_cfg = None
    for th in threads:
        if th.get('enabled', True):
            thread_cfg = th
            break

    if thread_cfg is None:
        logger.warning('没有启用的帖子')
        return

    tid = int(thread_cfg['tid'])
    logger.info('爬取帖子: tid=%s, name=%s', tid, thread_cfg.get('name', tid))

    nga_db.init_tables()
    crawler = NGACrawler(tid=tid, thread_cfg=thread_cfg, auth_cfg=auth_cfg, wx=None)
    crawler.crawl_once()
    logger.info('单次爬取完成')


if __name__ == '__main__':
    main()
