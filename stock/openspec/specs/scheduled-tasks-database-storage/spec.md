# 定时任务数据库存储（scheduled-tasks-database-storage）

本文档由变更 `scheduled-tasks-database-storage` 合并入主规格库。

## ADDED Requirements

### Requirement: 双引擎表结构一致

系统 MUST 为定时任务配置提供关系型存储，且在 **MySQL** 与 **SQLite** 两种模式下表名、列语义一致；建表或迁移逻辑 MUST 同时维护于项目数据库初始化路径中（与现有 `init_database` 模式一致），不得仅实现单一引擎。

#### Scenario: SQLite 部署可创建表

- **WHEN** 应用使用 `DB_TYPE=sqlite` 初始化数据库
- **THEN** `scheduled_task`（或等价命名）表 MUST 被创建且可插入与查询任务行

#### Scenario: MySQL 部署可创建表

- **WHEN** 应用使用 MySQL 初始化数据库
- **THEN** 同一套字段语义 MUST 在 MySQL 下可用，且与 SQLite 行为对业务层等价

### Requirement: 数据库为权威配置

进程在注册 APScheduler 任务时 MUST 以数据库中的任务记录为配置来源；用户通过 API 或管理界面进行的增删改 MUST 持久化到数据库，且 MUST NOT 要求修改 `tasks_config.yaml` 才能生效。

#### Scenario: 编辑后重启仍保留

- **WHEN** 用户在界面或 API 中修改某任务的触发器或启用状态并成功保存
- **THEN** 重启进程后从数据库加载 MUST 反映该修改，且不依赖 YAML 文件内容

### Requirement: 首次空库从 YAML 导入

当定时任务表在逻辑上为「无任何任务行」时，系统 MUST 读取项目约定的 `tasks_config.yaml`（或当前 `TaskManager` 使用的配置文件路径），将其中的全部任务条目插入数据库，然后再加载调度器。

#### Scenario: 新环境第一次启动

- **WHEN** 数据库已初始化但任务表为空且 YAML 中存在至少一条任务定义
- **THEN** 数据库 MUST 在加载调度器前包含对应记录，且调度器 MUST 按导入后的配置注册任务

### Requirement: 非空库时增量合并 YAML

当任务表中已有数据时，系统 MUST 解析同一 YAML 文件；对其中每个 `task_id`，若数据库中**不存在**该 ID，则 MUST 插入新行；若已存在，则 MUST **不**用 YAML 覆盖已有行（以数据库为准）。

#### Scenario: YAML 新增任务 ID

- **WHEN** 运维在 YAML 中增加新的 `task_id` 而数据库中尚无该 ID
- **THEN** 下次启动（或约定的同步时机）MUST 将该任务写入数据库并参与调度加载

#### Scenario: YAML 与数据库冲突

- **WHEN** 某 `task_id` 同时出现在 YAML 与数据库但字段内容不同
- **THEN** 系统 MUST 使用数据库中的配置作为调度依据，YAML 中同 ID 的修改 MUST NOT 自动覆盖数据库

### Requirement: 字段覆盖 TaskConfig

数据库中每条任务记录 MUST 能无损表达现有 `TaskConfig` 所需字段，至少包括：`task_id`、`task_name`、`module_path`、`function_name`、`trigger_type`、可序列化的 `trigger_args`、`enabled`，以及 `max_instances`、`misfire_grace_time`、`coalesce`、`description`（若代码路径使用 `args`/`kwargs`，则以其序列化策略在设计与实现中明确）。

#### Scenario: 从行重建 TaskConfig

- **WHEN** 从数据库读取一行构造 `TaskConfig` 并调用 `add_task`
- **THEN** 行为 MUST 与此前从 YAML 反序列化得到的等价配置一致（同一字段值下）
