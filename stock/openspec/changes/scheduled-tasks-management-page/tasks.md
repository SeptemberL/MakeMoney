## 1. 应用与 TaskManager 集成

- [x] 1.1 在 `main.py` 创建 `TaskManager` 后将其注册到 Flask 应用（如 `app.config['TASK_MANAGER']`），并保证蓝图内可安全访问
- [x] 1.2 在 `TaskManager` 中实现 `save_configs()`（或等价方法）：将任务集合序列化为 YAML 安全写回 `configs/tasks_config.yaml`（临时文件 + 替换），并与 `load_configs` 字段兼容

## 2. 后端 API

- [x] 2.1 在 `routes.py`（或蓝图）新增 `GET /api/scheduled_tasks`：合并 `TaskConfig` 与 `scheduler.get_job` 信息，返回 JSON 列表（含 next_run、暂停状态等）
- [x] 2.2 新增暂停/恢复接口（如 `POST /api/scheduled_tasks/<id>/pause` 与 `.../resume`），调用 `pause_task` / `resume_task`
- [x] 2.3 新增 `PUT` 或 `PATCH` 单任务更新：校验输入、更新内存与 YAML、对调度器执行 `remove_task` + 条件 `add_task`；错误时返回明确 `message`

## 3. 页面与导航

- [x] 3.1 新增页面路由（如 `/scheduled_tasks`）与模板 `templates/scheduled_tasks.html`：表格列表、空状态、与现有 Bootstrap 风格一致
- [x] 3.2 在 `templates/index.html` 中于「信号通知」后插入「定时任务」导航链接
- [x] 3.3 在 `templates/dsaweb.html` 侧栏中于「信号通知」tab 后插入对应 tab
- [x] 3.4 前端使用 `fetch` 调用上述 API，实现编辑表单（模态或独立区）、暂停/恢复按钮与刷新

## 4. 收尾

- [ ] 4.1 手动验证：编辑 cron/interval、暂停/恢复、YAML 落盘与进程重启后配置一致
- [ ] 4.2 对无效 `module_path` 的保存失败场景做错误提示验证
