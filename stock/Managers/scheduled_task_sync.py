"""
定时任务：YAML 种子导入数据库 + 行与 TaskConfig 互转。
运行期权威数据在数据库表 scheduled_task；YAML 仅在空表或新 task_id 时合并。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


def row_to_task_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """scheduled_task 行 -> TaskConfig.from_dict 可用字典。"""
    ta = row.get('trigger_args')
    if isinstance(ta, str):
        ta = json.loads(ta) if (ta or '').strip() else {}
    if not isinstance(ta, dict):
        ta = {}
    args: tuple = ()
    kwargs: Dict[str, Any] = {}
    aj = row.get('args_json')
    if aj:
        if isinstance(aj, str):
            args = tuple(json.loads(aj))
        else:
            args = tuple(aj)
    kj = row.get('kwargs_json')
    if kj:
        if isinstance(kj, str):
            kwargs = json.loads(kj)
        elif isinstance(kj, dict):
            kwargs = kj
    mg = row.get('misfire_grace_time')
    if mg is not None:
        mg = int(mg)
    return {
        'task_id': (row.get('task_id') or '').strip(),
        'task_name': (row.get('task_name') or '').strip(),
        'module_path': (row.get('module_path') or '').strip(),
        'function_name': (row.get('function_name') or '').strip(),
        'trigger_type': (row.get('trigger_type') or 'cron').strip(),
        'trigger_args': ta,
        'enabled': bool(row.get('enabled')),
        'run_once_per_day': bool(row.get('run_once_per_day', 0)),
        'max_instances': int(row.get('max_instances') or 1),
        'misfire_grace_time': mg,
        'coalesce': bool(row.get('job_coalesce', 1)),
        'description': (row.get('description') or '').strip(),
        'args': args,
        'kwargs': kwargs,
    }


def task_config_to_storage_dict(cfg) -> Dict[str, Any]:
    """TaskConfig -> 可写入 upsert_scheduled_task 的字典（含 args/kwargs）。"""
    d = cfg.to_dict()
    d['args'] = list(cfg.args) if cfg.args else []
    d['kwargs'] = cfg.kwargs if cfg.kwargs is not None else {}
    return d


def sync_scheduled_tasks_yaml_to_db(db, yaml_path: Path) -> None:
    """
    若表为空：将 YAML 全部任务写入数据库。
    若表非空：仅对 YAML 中存在而数据库中不存在的 task_id 执行 INSERT。
    """
    db.ensure_scheduled_task_tables()
    path = Path(yaml_path)
    if not path.is_file():
        logger.debug('scheduled_task 种子: YAML 不存在，跳过: %s', path)
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning('读取 YAML 失败，跳过种子: %s', e)
        return
    tasks = data.get('tasks') or []
    n = db.count_scheduled_tasks()
    if n == 0:
        for t in tasks:
            if not isinstance(t, dict):
                continue
            try:
                db.upsert_scheduled_task(t)
            except Exception as e:
                logger.warning('scheduled_task 种子导入失败: %s', e)
        logger.info('scheduled_task: 空表，已从 YAML 导入 %d 条', len(tasks))
        return
    added = 0
    updated_run_once = 0
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = (t.get('task_id') or '').strip()
        if not tid:
            continue
        if db.scheduled_task_exists(tid):
            # 仅同步“安全字段”：run_once_per_day（避免覆盖数据库中更权威的其它配置）
            try:
                db.ensure_scheduled_task_tables()
                want = 1 if bool(t.get("run_once_per_day", False)) else 0
                row = db.fetch_one(
                    "SELECT run_once_per_day AS v FROM scheduled_task WHERE task_id = %s LIMIT 1",
                    (tid,),
                )
                cur = int(row.get("v") or 0) if row else 0
                if cur != want:
                    db.execute(
                        "UPDATE scheduled_task SET run_once_per_day = %s WHERE task_id = %s",
                        (want, tid),
                    )
                    updated_run_once += 1
            except Exception as e:
                logger.debug("scheduled_task 同步 run_once_per_day 失败（忽略）task_id=%s err=%s", tid, e)
            continue
        try:
            db.upsert_scheduled_task(t)
            added += 1
        except Exception as e:
            logger.warning('scheduled_task 增量导入失败 task_id=%s: %s', tid, e)
    if added:
        logger.info('scheduled_task: 从 YAML 增量新增 %d 条（已有 ID 不覆盖）', added)
    if updated_run_once:
        logger.info("scheduled_task: 已同步 run_once_per_day %d 条", updated_run_once)
