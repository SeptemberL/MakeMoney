## Context

- 进程入口 `main.py` 创建 `TaskManager(config_file="configs/tasks_config.yaml")`，调用 `load_configs()` 与 `start()`；`TaskManager`（`Managers/scheduler_system.py`）基于 APScheduler，支持 cron / interval / date，并提供 `list_tasks`、`get_running_jobs`、`pause_task`、`resume_task`、`remove_task`，但**未**向 Flask 暴露实例，也未实现将内存修改写回 YAML。
- 主导航在 `templates/index.html`；嵌入壳 `templates/dsaweb.html` 的侧栏在「信号通知」后有「设置」。新页需在两处与「信号通知」相邻插入入口。
- 独立机制：`schedule` 库线程、`nga_monitor` 等不在本页作为「YAML 任务」列出（与 proposal 一致），避免误导；可在页面文案中一句话说明。

## Goals / Non-Goals

**Goals:**

- 提供只读或可写（按实现选定）的 `tasks_config.yaml` 视图，与调度器任务 ID 一致。
- 支持对 APScheduler 已注册任务的 **暂停 / 恢复**（映射 `pause_task` / `resume_task`），以及列表展示下次运行时间等（APScheduler `job.next_run_time`）。
- 支持 **编辑** 任务配置并持久化：写回 YAML 后，对变更项执行「移除旧 job + 按新配置 `add_task`」，或整文件重载策略（二选一，见下）。
- 在应用启动后通过 `app` 持有 `TaskManager` 引用，供蓝图安全访问。

**Non-Goals:**

- 不实现任意 Python 代码在线编辑执行；`module_path` / `function_name` 仍限于配置中的合法模块入口。
- 不把数据库迁移（MySQL/SQLite）纳入本功能；任务配置仍为 YAML 文件。
- 不强制实现多用户鉴权；若部署在局域网，可按现有项目惯例保持与同类页面一致。

## Decisions

1. **暴露 TaskManager**  
   - **选择**：在 `main.py` 创建 `task_manager` 后执行 `app.config['TASK_MANAGER'] = task_manager`（或 `app.extensions['task_manager'] = task_manager`）。  
   - **理由**：蓝图通过 `current_app` 获取，避免循环导入；与 Flask 惯例一致。  
   - **备选**：模块级全局变量；简单但测试与多实例较差。

2. **读取列表数据源**  
   - **选择**：列表以 `TaskManager.tasks`（`TaskConfig`）为主，辅以 `scheduler.get_job(id)` 取运行时状态（暂停、next_run_time）。  
   - **理由**：与 YAML 定义一一对应；`enabled: false` 的任务若未加入调度器，需在 UI 标明「未加载」。

3. **写回 YAML**  
   - **选择**：在 `TaskManager` 增加 `save_configs()`：将当前 `self.tasks` 与文件中**未加载的**禁用项合并写回；或每次编辑后全量重写 `tasks` 数组（以保持顺序简单）。  
   - **理由**：现有类无此方法，需新增；写文件前用临时文件 + `replace` 降低损坏风险。  
   - **备选**：仅内存修改不写盘——重启丢失，不符合「编辑」期望。

4. **编辑后热更新**  
   - **选择**：对单个任务更新：`remove_task(task_id)` 后若 `enabled` 则 `add_task(TaskConfig(...))`，否则只保留在 `tasks` 字典并写 YAML（或从字典移除与 YAML 一致）。  
   - **理由**：无需重启进程。  
   - **备选**：整表 `load_configs` 需先清空 scheduler 全部 job，实现复杂且易出错。

5. **API 形状**  
   - **选择**：`GET /api/scheduled_tasks` 返回任务数组 + 运行态；`PATCH` 或 `PUT` 更新单任务；`POST .../pause`、`.../resume` 或 PATCH 内 `enabled` 映射暂停/恢复。  
   - **理由**：与现有 `routes.py` 中 JSON API 风格对齐。

6. **前端**  
   - **选择**：服务端渲染页 + 少量 fetch JSON（类似 `signal_notify`），Bootstrap 表格与模态框编辑表单。  
   - **理由**：与仓库现有技术栈一致。

## Risks / Trade-offs

- **[Risk]** 并发编辑 YAML 与手动编辑文件冲突 → **Mitigation**：写前读入合并或文档提示「单写者」；可选文件 mtime 校验。
- **[Risk]** `pause` 与 YAML 中 `enabled` 语义重叠 → **Mitigation**：UI 区分「配置启用」与「当前调度暂停」；保存编辑时以表单 `enabled` 为准同步到 YAML。
- **[Risk]** 动态加载模块失败导致 `add_task` 失败 → **Mitigation**：API 返回明确错误信息，页面展示上次成功配置。

## Migration Plan

- 部署新版本后无需数据迁移；首次访问前确保进程已用新版本 `main.py` 注册 `Task_MANAGER`。  
- 回滚：移除新路由与导航链接即可；YAML 仍兼容旧进程读取。

## Open Questions

- 是否在 UI 中暴露「立即执行一次」（`scheduler.modify_job` / `job.modify` 或手动 `TaskExecutor.execute_function`）——可在 `/opsx:apply` 阶段作为可选任务项。
