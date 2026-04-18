## Context

- 当前 `TaskManager.load_configs()` 从 `configs/tasks_config.yaml` 读取；计划中的定时任务管理页拟写回 YAML。用户要求改为**数据库为唯一运行配置**，YAML 仅在库空或出现新 `task_id` 时作为种子。
- 项目 `database/database.py` 对 MySQL 与 SQLite 分别维护 `CREATE TABLE`，必须符合工作区「双引擎一致性」规则。

## Goals / Non-Goals

**Goals:**

- 定义一张（或一组）表，字段覆盖 `TaskConfig` 与序列化所需信息（含 `trigger_args` 的 JSON）。
- 启动时：先确保表存在 → 若无任何任务行则全量从 YAML 导入 → 若非空则对 YAML 中**库中不存在的 task_id** 执行插入。
- 调度器注册仅基于数据库读取结果；API/页面 CRUD 只动数据库，并成功触发热更新（与既有 `add_task`/`remove_task`/暂停恢复设计一致）。
- MySQL 与 SQLite 建表与迁移路径一致。

**Non-Goals:**

- 不把 APScheduler 的 `jobs` 持久化到 SQLAlchemyJobStore 与本表混为一谈（当前 `main.py` 使用 MemoryJobStore）；本表仅存**业务配置**。
- 不强制实现「从数据库导出回 YAML」；可作为后续增强。

## Decisions

1. **表名**  
   - **选择**：`scheduled_task`（单数，与 `signal_rule` 等风格可对比后统一）。  
   - **主键**：`task_id` `VARCHAR` 唯一，与 YAML 中 `task_id` 一致。

2. **trigger_args 存储**  
   - **选择**：`TEXT`（SQLite）/ `JSON` 或 `TEXT`（MySQL，若版本顾虑可用 `TEXT` + 应用层 `json.loads`）。  
   - **理由**：与现有代码中 dict 往返一致。

3. **空库与增量**  
   - **选择**：  
     - `COUNT(*)==0` → 解析 YAML 全部 `tasks`，逐条 INSERT。  
     - `COUNT(*)>0` → 对 YAML 每个 `task_id`，`SELECT` 不存在则 `INSERT`，存在则 **跳过**（数据库为准）。  
   - **备选**：存在则 YAML 覆盖 DB — 用户未要求，故不采用。

4. **加载顺序**  
   - **选择**：在 `main.py` 中 `Database.init_database()` 之后、`TaskManager.load_configs()` 之前或之内调用「ensure_seed_from_yaml」；`load_configs` 改为从 DB 构建 `TaskConfig` 列表。  
   - **理由**：保证表已存在。

5. **与前一变更衔接**  
   - 若 `scheduled-tasks-management-page` 已实现 YAML API，替换为 DB DAO 调用；`save_configs` 改为 `UPDATE/INSERT` SQL。

## Risks / Trade-offs

- **[Risk]** 用户手动改 YAML 期望生效 → **Mitigation**：文档说明运行期以 DB 为准；可选未来增加「重新从 YAML 导入」管理动作。  
- **[Risk]** JSON 字段方言差异 → **Mitigation**：统一应用层序列化，双引擎同一套 Python 逻辑。  
- **[Risk]** 多实例部署多进程写同一 DB → **Mitigation**：与现有多进程假设一致；任务编辑频率低，接受乐观策略或后续加版本列。

## Migration Plan

- 新代码部署后首次启动：自动建表、空则种子导入。  
- 回滚：保留 YAML 文件即可用旧版本进程；回滚前若已写 DB，需运维自行导出或接受丢失。

## Open Questions

- 是否在 UI 显示「最后从 YAML 同步时间」——非必须，可省略。
