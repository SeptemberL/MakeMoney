## Context

- 项目已通过 **`configs/tasks_config.yaml` + `Managers/scheduler_system.TaskManager`**（APScheduler）加载并启动定时任务（见 `main.py`）。
- **Tushare 当日更新**逻辑已存在于 `routes.fetch_today_tushare_api`：使用 `pro.daily(trade_date=...)` 全市场日线，再按 `_get_tracked_stocks()` 过滤，对每只股票 `INSERT ... ON DUPLICATE KEY` / SQLite `ON CONFLICT` 写入各股独立表。Tushare **日线接口默认为不复权（未复权）**，与「未复权数据」要求一致。
- 手动 API 与定时任务应 **共用同一实现**，避免一处改参数、另一处仍用旧逻辑。

## Goals / Non-Goals

**Goals:**

- 每天 **17:00** 自动执行一次与手动拉取等价的同步（含「当日无数据则向前回溯若干交易日」的现有容错）。
- 任务可通过 YAML **启用/禁用**，与现有任务配置风格一致。
- 失败时记录日志；单只股票失败不阻断整批（与当前 API 行为一致）。

**Non-Goals:**

- 不引入新数据库表或迁移（无表结构变更）。
- 不强制指定 APScheduler 的 `timezone` 新配置项；若需固定 **中国时区**，可在实现阶段为调度器或该 job 设置 `Asia/Shanghai`（见 Open Questions）。

## Decisions

1. **触发时间**  
   - 使用 **cron：`hour: 17`, `minute: 0`**，与用户需求「每天下午 5 点」一致。  
   - **理由**：收盘后数据通常已入库；5 点执行晚于 A 股常规收盘时间，降低「当日数据未就绪」概率（仍保留现有回溯逻辑）。

2. **抽取方式**  
   - 将「拉取 Tushare + 遍历已跟踪股票写库」提取为模块级函数，例如 `tasks/daily_tushare_sync.py` 中 `run_daily_tushare_sync()`（名称以实现为准）。  
   - `fetch_today_tushare_api` 改为调用该函数，并将 HTTP 结果封装为 `jsonify`。  
   - **理由**：单一事实来源；定时任务仅 `module_path` + `function_name` 指向该函数。

3. **未复权**  
   - 继续使用 **`pro.daily`**，不调用带复权参数的接口；若未来 Tushare 侧增加参数，代码中 **显式不传复权相关参数或显式文档化为 raw**。  
   - **理由**：与当前实现及用户需求一致。

4. **配置**  
   - Token 仍从 **`config.ini` `[TUSHARE] TOKEN`** 读取（与现有 API 一致）。未配置时任务应打日志并跳过或快速返回（与 API 返回 400 语义对齐：记录 warning/error，不抛未捕获异常导致调度器线程崩溃）。

5. **并发**  
   - 任务设置 **`max_instances: 1`**（与现有 `task_001` 风格一致），避免重叠执行。

## Risks / Trade-offs

- **[Risk] 服务器时区非东八区** → 17:00 可能不是用户预期的「北京时间下午 5 点」→ **缓解**：在 `tasks_config` 的 `description` 中注明依赖主机时区；可选在实现中为 scheduler/job 绑定 `Asia/Shanghai`。  
- **[Risk] Tushare 额度/限流** → 单次 `pro.daily` 为全市场一行请求，已跟踪股票为本地更新，与现网一致；异常时依赖现有重试与日志。  
- **[Trade-off] 仅进程内调度** → 应用未运行时不会执行；与现有架构一致，不在本变更引入系统 crontab。

## Migration Plan

1. 部署新代码与更新后的 `tasks_config.yaml`。  
2. 重启应用使 `TaskManager` 加载新任务。  
3. 回滚：将对应任务 `enabled: false` 或移除任务项并重启。

## Open Questions

- 是否必须为 APScheduler 显式配置 **`Asia/Shanghai`**（若生产环境服务器为 UTC，则当前「17:00」会为 UTC 时间）。建议在实现时根据部署环境二选一并在 README/任务描述中写清。
