## Why

将定时任务配置从「以 YAML 为主、页面写文件」改为「以数据库为唯一真相」，可避免多进程/多写者下文件竞态，便于与现有 MySQL/SQLite 双引擎体系一致地做备份与查询。保留 `tasks_config.yaml` 仅作**首次或增量种子**：库为空时导入；后续若 YAML 出现新条目而库中尚无，则合并写入数据库。

## What Changes

- 新增业务表（MySQL 与 SQLite **同步建表**）存储 APScheduler 任务配置字段（与现有 `TaskConfig` 语义对齐：`task_id`、名称、模块/函数、触发类型与参数 JSON、`enabled`、调度选项等）。
- `TaskManager`（或数据访问层）从数据库加载任务列表并注册到调度器；**不再**将日常编辑写回 `tasks_config.yaml`。
- **引导逻辑**：进程启动或首次访问管理逻辑时，若表中无任何任务行，则读取 `configs/tasks_config.yaml` 全量插入数据库后再加载调度器。
- **增量同步**：若表中已有数据，仍扫描 YAML 中条目：对 `task_id` 在库中不存在的项执行 **INSERT**（「打开没有则新增的都放入数据库」），已存在的以数据库为准（不自动用 YAML 覆盖，除非另定策略；见 `design.md`）。
- 定时任务 Web API/页面（含变更 `scheduled-tasks-management-page` 中的实现）改为**只读写数据库**；YAML 可选保留为只读模板或导出用途。

## Capabilities

### New Capabilities

- `scheduled-tasks-database-storage`: 定时任务表结构、双引擎建表、DB 为权威存储、YAML 种子与增量导入规则。

### Modified Capabilities

- （无已合并入主规格库的同名 spec）与进行中变更 `scheduled-tasks-management-page` 的关系：**实现该页时应以本变更为准**，持久化从 YAML 切换为数据库；若两变更合并开发，应优先完成本变更的表结构与加载路径。

## Impact

- **数据库**：`database/database.py` 中 `_init_database_mysql` / `_init_database_sqlite` 及必要的 `ALTER`/列检测迁移（若采用演进式加列）。
- **调度**：`Managers/scheduler_system.py`、`main.py` 启动流程：`load_configs` 数据源改为 DB + 上述引导/同步。
- **配置**：`configs/tasks_config.yaml` 降级为可选种子文件；文档与运维说明需更新。
- **兼容性**：现有部署首次启动执行种子导入；仅改 YAML 不再影响运行中配置（除非执行显式「从 YAML 再导入」功能，本提案不强制）。
