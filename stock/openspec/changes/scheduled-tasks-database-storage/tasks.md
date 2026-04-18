## 1. 数据库表与双引擎

- [x] 1.1 在 `database/database.py` 的 `_init_database_mysql` 与 `_init_database_sqlite` 中增加 `scheduled_task` 表（或最终命名）的 `CREATE TABLE`，列类型在两引擎间语义对齐；必要时用 `column_exists` 做增量加列迁移
- [x] 1.2 在 `Database` 类中增加定时任务的查询/插入/更新/按 `task_id` 删除等方法（或独立 `scheduled_task_repository` 模块，经 `Database` 执行 SQL）

## 2. 种子与同步逻辑

- [x] 2.1 实现「表为空则全量从 `configs/tasks_config.yaml` 导入」函数
- [x] 2.2 实现「表非空则仅对 YAML 中存在而 DB 中不存在的 `task_id` 执行 INSERT」函数
- [x] 2.3 在 `TaskManager` 初始化或 `main.py` 启动链中，于 `load_configs` 之前调用上述逻辑（顺序：`init_database` → 种子/增量 → 从 DB 加载）

## 3. TaskManager 与持久化切换

- [x] 3.1 将 `load_configs`（或等价入口）改为从数据库构建 `TaskConfig` 列表并注册调度任务
- [x] 3.2 移除或废弃「日常保存写回 YAML」路径；新增/更新任务改为写数据库并 `remove_task` + `add_task`（或等效热更新）
- [x] 3.3 确保 `TaskConfig.from_dict` 与 DB 行往返一致（含 `trigger_args` JSON）

## 4. API 与页面（若已存在）

- [x] 4.1 将定时任务 REST 与页面数据源改为数据库访问层
- [x] 4.2 更新说明：运维以 DB 或管理页为准；YAML 仅作初始/增量种子

## 5. 验证

- [ ] 5.1 分别在 SQLite 与 MySQL 配置下验证：空库导入、增量 YAML、编辑持久化、重启后一致（需在本地配置两种 DB_TYPE 手测）
- [ ] 5.2 验证「同 ID YAML 不覆盖 DB」场景（手测）
