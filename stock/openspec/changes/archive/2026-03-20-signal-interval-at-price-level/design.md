## Context

信号子系统已有 `PriceRangeSignal`（区间内触发 + 同日一次）、`FibonacciRetraceSignal`，以及 `SignalConfig` 上的 `send_type` / `send_interval_seconds` 字段与悬浮 schema 占位。`SingleManager.update_price` 在每次价格推送时调用各信号的 `update`；持久化通过 `signal_rule` 与 `signal_rule_state`（具体列名以实现为准）与数据库双引擎维护。

## Goals / Non-Goals

**Goals:**

- 提供**单目标价位**类信号：用户设定 `target_price` 与**触发模式**（至少支持：`at_or_above` 价格 ≥ 目标、`at_or_below` 价格 ≤ 目标；可选扩展 `cross_up` / `cross_down` 基于上一 tick 与当前价比较）。
- 当触发模式对应的**条件为真**时，系统 SHALL 按 `send_interval_seconds`（正整数）节流发送消息；两次成功发送之间间隔不得小于该秒数（使用 `last_sent_at` 与当前时间比较）。
- 当条件为假时，停止发送；运行态记录「是否曾进入激活」以便产品语义清晰（见决策）。
- 与现有通道一致：通过 `group_ids` 与既有 `sender` 发送；模板沿用 `SignalMessageTemplate` 占位符扩展（如 `target_price`、`mode`）。

**Non-Goals:**

- 不负责保证行情 tick 频率（依赖上游报价更新）；不实现推送服务商级别的「送达保证」。
- 不在本变更中重构所有历史信号为统一状态机（仅新增类型并最小侵入注册）。

## Decisions

1. **新枚举值 `SingleType.PRICE_LEVEL_INTERVAL`（或等价命名）**  
   - *理由*：与区间类 `PRICE_RANGE` 语义不同，避免复用 `params.lower/upper` 造成歧义。  
   - *备选*：复用 `PRICE_RANGE` 令 lower=upper；*否决*：与「区间一日一次」逻辑冲突且难维护。

2. **`send_type` 固定为 `INTERVAL` 或允许 `ON_TRIGGER` 首条 + `INTERVAL` 后续**  
   - *建议*：本信号类型创建时强制 `send_type=INTERVAL`，且 `send_interval_seconds` 必填并校验范围（如 60–86400，具体上下限在实现/配置中写死可调）。  
   - *理由*：与用户需求「每隔一段时间」一致，减少无效规则。

3. **条件由假变真时的行为**  
   - *决策*：条件首次为真即可在**不早于** `interval` 的首个 tick 发送第一条（若距上次发送已超过 interval，或从未发送）；之后每满足间隔发一条，**只要条件持续为真**。  
   - *条件由真变假*：清除「可发送」计时语义上的挂起，可选将 `last_sent_at` 保留或重置；*建议*：条件为假时**不重置** `last_sent_at`，条件再次为真时仍须满足完整间隔（避免边界抖动连发）。

4. **持久化字段**  
   - `params` JSON：`target_price`（number）、`mode`（enum 字符串）、可选 `min_interval_seconds` 若与全局默认不同（优先单一来源）。  
   - `runtime_state`：`last_sent_at`（ISO 或 epoch 秒，与现有字段风格一致）、可选 `last_price` 用于穿越判断。

5. **与 `PriceRangeSignal` 的「同日一次」互不影响**  
   - 新类**不使用** `last_notified_date` 同日限次逻辑，仅以时间间隔节流。

## Risks / Trade-offs

- **[Risk] 报价稀疏导致「间隔」实际变长** → 说明文档标注：间隔为「至少间隔」，依赖 `update_price` 调用频率。  
- **[Risk] 间隔过小导致刷屏** → 校验最小间隔；可选在管理端警告。  
- **[Risk] 抖动在目标价附近反复横跳** → 采用决策 3 的间隔门闩；若仍嘈杂，后续可加「迟滞带」*（列为 Open Question）*。

## Migration Plan

1. 部署新版本代码（含新 `SingleType` 与 DB 迁移若需扩展 `signal_type` 枚举存储）。  
2. 已有规则数据不变；用户新建「价位间隔」类规则时使用新类型值。  
3. 回滚：下线该类型处理分支；库中若已有该类型规则，回滚后应禁用或忽略（任务阶段定义 API 行为）。

## Open Questions

- 是否在首条消息前需要「必须穿越」而非「静态 ≥/≤」（默认 MVP 可做静态，穿越为增强）。 
   >=为向上穿越， <=为向下穿越
- 是否需要「每日最多 N 条」全局上限（与纯间隔并列）。  
   需要每日最多N条上限，但是是单条信号的配置而非全部
- 目标价精度是否与股票小数位策略统一（复用现有价格格式化）。
   策略统一即可
