## Why

后台已用 APScheduler 与 `configs/tasks_config.yaml` 管理 cron/interval 等定时任务，但只能通过改文件与重启进程来查看或调整，缺少集中可视化管理。在「信号通知」旁增加调度任务页，可让运维与日常使用者在本机 Web 界面统一查看启停与编辑配置。

## What Changes

- 在主导航与 DSA 嵌入布局中，于「信号通知」**之后**增加「定时任务」入口，对应新页面路由与模板。
- 新页面展示当前项目中由 `tasks_config.yaml` 加载的**全部** APScheduler 任务（含 cron、interval、date 触发类型），并显示与调度器一致的状态（如是否已调度、暂停等）。
- 提供**开启/关闭（暂停/恢复）**、**编辑**（写回 YAML 并热更新调度器或明确需重启的边界）、以及列表刷新等能力；具体交互与持久化策略见 `design.md`。
- 新增 REST API（或复用现有风格）供页面读写任务列表与状态；**不**在本变更中把 NGA 轮询、`schedule` 库循环等独立于 APScheduler 的机制强行并入同一列表（可在页面以简短说明区分），除非实现阶段证明可安全统一展示。

## Capabilities

### New Capabilities

- `scheduled-tasks-management`: Web 端定时任务列表、启停与配置编辑，与 `TaskManager` / `tasks_config.yaml` 对齐。

### Modified Capabilities

- （无）现有 `openspec/specs/` 下规格与本次功能无交叉需求变更。

## Impact

- **前端**：`templates/index.html`、`templates/dsaweb.html` 导航；新模板与静态交互（可与现有 Bootstrap/信号通知页风格一致）。
- **后端**：`routes.py`（或蓝图内）新增页面路由与 API；`main.py` 需将 `TaskManager` 实例暴露给 Flask 应用上下文（如 `app.extensions` 或模块级注册），以便路由调用 `list_tasks`、`pause_task`、`resume_task`、写回 YAML 与 `add_job`/`remove_job` 等。
- **配置与数据**：`configs/tasks_config.yaml` 读写权限与并发安全；可选扩展 `TaskManager`（保存配置、按 ID 更新任务、重载单任务）。
- **依赖**：沿用现有 APScheduler、PyYAML、Flask；无新增硬性第三方依赖（除非实现选择引入表单校验库等）。
