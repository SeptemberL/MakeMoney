## Why

现有信号多为「触发一次」或「日内一次」类逻辑；用户需要在**股价到达指定价位（或满足方向性穿越条件）后**，在条件持续成立期间**按固定时间间隔重复提醒**，以免错过盯盘或需要持续确认仓位风险。`SendType.INTERVAL` 与 `send_interval_seconds` 已在配置层预留，但缺少与之匹配的价位类信号语义与实现。

## What Changes

- 新增一种**价位/穿越类**信号类型：可配置目标价、比较方向（触及/上破/下破等，以实现阶段以设计为准）、以及**重复通知间隔**（秒）。
- 当**激活条件**首次满足后进入「已武装」状态；在**持续满足**期间，每隔 `send_interval_seconds` 生成并发送一条消息（受最小间隔约束，避免刷屏）。
- 当价格离开条件或用户定义的「解除」语义满足时，停止间隔发送；再次满足时可按设计决定是否重新武装（建议可配置：每日重置 / 每次离开区间后重置）。
- 持久化与运行态：在 `signal_rule` / `signal_rule_state`（或等价存储）中保存新类型参数与 `last_sent_at`、武装状态等，**MySQL 与 SQLite 同步**。
- 更新悬浮编辑器 schema、路由/API、文档（如 `Docs/信号通知系统.md`），与现有 `PriceRangeSignal` / `FibonacciRetraceSignal` 并列注册。

## Capabilities

### New Capabilities

- `price-level-interval-signal`：定义「目标价位 + 方向/触及语义 + 间隔重复通知」的配置校验、触发与解除、运行态持久化及与发送通道的集成要求。

### Modified Capabilities

- （无）`openspec/specs/` 下尚无既有能力规格；本次仅新增能力规格。

## Impact

- **代码**：`signals/signal_notify_system.py`（新 `SingleType`、新 Signal 类、`create_signal_instance`、`get_floating_editor_schema`）、`routes.py` 中信号 CRUD/序列化、数据库层 `database.py` 与迁移（MySQL + SQLite）。
- **API/配置**：前端/悬浮面板字段新增；若存在 OpenAPI 或表单校验需对齐。
- **运维**：间隔过短可能导致消息风暴，需在设计与任务中约定默认下限与可选上限。
