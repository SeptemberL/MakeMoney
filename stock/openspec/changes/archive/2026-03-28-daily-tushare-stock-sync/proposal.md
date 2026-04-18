## Why

当前已通过 HTTP 接口 `POST /api/fetch_today_tushare` 手动用 Tushare 拉取当日日线并写入各股票表，但依赖人工触发，容易遗漏收盘后更新。**需要在应用进程内增加每日定时任务（下午 5 点）自动执行同一套拉取与落库逻辑**，并明确使用 **未复权** 行情，与业务对原始价格序列的期望一致。

## What Changes

- 增加 **APScheduler 定时任务**：按 cron 在 **每天 17:00**（与现有 `configs/tasks_config.yaml` 调度方式一致）触发一次「Tushare 拉取当日（或最近可用交易日）日线 → 更新已跟踪股票对应表」的流程。
- **复用/抽取** 现有 `fetch_today_tushare_api` 中的核心逻辑为可调用函数（供定时任务与现有 API 共用），避免两套实现分叉。
- **数据源约定**：使用 Tushare `pro.daily` 等 **未复权** 日线接口（与当前接口实现一致；不在此变更中引入前复权/后复权参数）。
- 在 `configs/tasks_config.yaml` 中新增任务项（可 `enabled` 开关），与 `main.py` 中已有 `TaskManager` 启动路径衔接。

## Capabilities

### New Capabilities

- `daily-tushare-stock-sync`：每日定时用 Tushare 未复权日线更新所有已跟踪股票表、与手动 API 行为一致及失败/日志要求。

### Modified Capabilities

- （无：现有 `openspec/specs/` 下无与本定时同步直接对应的独立能力规格；行为为新增调度与代码抽取，不要求修改既有 watchlist/价格区间等规格。）

## Impact

- **代码**：`routes.py`（抽取/调用）、新建 `tasks/` 下模块或扩展现有 `tasks.*` 包中入口函数；`configs/tasks_config.yaml`；可选 `Docs/项目基础框架.md` 中调度示例一句（非必须，由实现阶段决定）。
- **配置**：沿用 `config.ini` 中 `[TUSHARE] TOKEN`；无新表结构。
- **依赖**：已有 `tushare`、`APScheduler`；无新增包要求。
- **运维**：进程需常驻（与现有 Flask + TaskManager 一致）；时区以调度器/服务器本地时间为准（设计文档中明确）。

## Non-goals

- 不改变 akshare 等其他数据源路径的复权策略；不在本变更中批量改写历史表为「混合复权来源」。
- 不要求新增独立 cron 系统服务（仅进程内调度）。
