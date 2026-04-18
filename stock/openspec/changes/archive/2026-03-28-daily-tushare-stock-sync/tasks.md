## 1. 抽取与复用

- [x] 1.1 从 `routes.fetch_today_tushare_api` 抽取「Tushare `pro.daily` + 回溯日期 + 遍历已跟踪股票 + MySQL/SQLite upsert」为独立函数（如 `tasks/daily_tushare_sync.py` 中 `run_daily_tushare_sync`），保留与现有一致的字段映射与未复权数据源（`pro.daily`）。
- [x] 1.2 将 `fetch_today_tushare_api` 改为调用上述函数，并将返回值/错误转换为现有 JSON 响应格式。

## 2. 定时任务配置

- [x] 2.1 在 `configs/tasks_config.yaml` 中新增任务：`cron` 触发 `hour: 17`, `minute: 0`，`module_path` / `function_name` 指向新入口；设置 `enabled: true`、`max_instances: 1`，`description` 注明「Tushare 未复权日线、依赖进程与时区」。
- [x] 2.2 本地验证：`TaskManager.load_configs` 能加载新任务且无语法错误；启动应用后日志中可见任务注册（或按需手动触发一次函数验证写库）。

## 3. 时区与文档（按需）

- [x] 3.1 若部署环境非东八区，为 APScheduler 或该 job 配置 `Asia/Shanghai`，或在任务说明中明确「服务器本地 17:00」与运维约定。
- [x] 3.2 （可选）在 `Docs/项目基础框架.md` 定时调度小节增加一行说明该每日 Tushare 任务。

## 4. 验证

- [x] 4.1 配置有效 Token 时，手动调用 HTTP API 与直接调用任务函数行为一致（更新计数/跳过逻辑一致）。
- [x] 4.2 Token 缺失时，任务函数不抛未捕获异常，日志可定位原因。
