## ADDED Requirements

### Requirement: 美人肩信号基础输入输出
系统 MUST 提供一个名为 `signal-meirenjian` 的筛选信号能力，用于在给定标的的指定时间窗口内识别“美人肩”形态，并输出结构化结果。

#### Scenario: 输入数据不足
- **WHEN** 输入的 K 线数量小于 `minBars`
- **THEN** 系统 MUST 返回 `hit=false` 且给出 `reason` 指示为数据不足

#### Scenario: 正常输入
- **WHEN** 输入满足 `minBars` 且包含 OHLCV（至少 O/H/L/C）
- **THEN** 系统 MUST 输出一个结果对象，包含 `hit` 与 `meta`（见下述 Requirements）

### Requirement: 参数与默认值
系统 MUST 支持通过参数配置美人肩识别口径，并为未提供的参数使用默认值。参数集合 MUST 至少包含：

- `lookbackBars`：识别窗口长度（默认 120）
- `minBars`：最小输入 K 线数量（默认 60）
- `pivotLeft` / `pivotRight`：局部极值（pivot）判定左右跨度（默认 3 / 3）
- `maxNecklineSlopeAbs`：颈线允许的绝对斜率（默认 0.02，单位为“每根 K 的相对变化”）
- `minHeadAboveShoulderPct`：头部相对肩部的最小突出比例（默认 0.03）
- `maxShoulderHeightDiffPct`：左右肩高度最大差异比例（默认 0.03）
- `minPatternBars`：形态最小跨度（默认 15）
- `maxPatternBars`：形态最大跨度（默认 90）
- `minScore`：命中阈值（默认 0.6，范围 0~1）

#### Scenario: 未提供参数
- **WHEN** 调用信号未提供任何参数
- **THEN** 系统 MUST 采用上述默认值完成计算

#### Scenario: 参数越界
- **WHEN** 参数（例如 `lookbackBars`、`minScore`）超出允许范围
- **THEN** 系统 MUST 以可诊断方式失败或回退到安全值（具体策略 MUST 在实现侧统一，并在返回中给出 `reason`）

### Requirement: 关键点与形态结构定义（抽象）
系统 MUST 将“美人肩”形态抽象为按时间顺序排列的关键点集合，并至少包含下列语义点：

- `LS`：左肩高点（pivot high）
- `T`：头部高点（pivot high），其价格 MUST 高于 `LS` 与 `RS`（满足 `minHeadAboveShoulderPct`）
- `RS`：右肩高点（pivot high）
- `NL1`、`NL2`：颈线两点（pivot low 或等价支撑点），用于定义颈线

系统 MUST 保证关键点时间顺序满足：`LS < NL1 < T < NL2 < RS`（以 bar index 计）。

#### Scenario: 关键点顺序不满足
- **WHEN** 候选关键点无法满足上述时间顺序约束
- **THEN** 系统 MUST 返回 `hit=false`

#### Scenario: 肩部对称性约束
- **WHEN** 候选 `LS` 与 `RS` 的价格差异超过 `maxShoulderHeightDiffPct`
- **THEN** 系统 MUST 返回 `hit=false` 或降低评分使其无法达到 `minScore`

### Requirement: 颈线定义与斜率约束
系统 MUST 以 `NL1` 与 `NL2` 两点定义颈线，并计算颈线斜率（相对变化/每根 K）。系统 MUST 约束颈线斜率绝对值不超过 `maxNecklineSlopeAbs`，否则不得命中。

#### Scenario: 颈线斜率过大
- **WHEN** 计算得到的颈线斜率绝对值大于 `maxNecklineSlopeAbs`
- **THEN** 系统 MUST 返回 `hit=false` 或降低评分使其无法达到 `minScore`

### Requirement: 形态跨度约束
系统 MUST 约束形态跨度（`LS` 到 `RS` 的 bar 数）在 `[minPatternBars, maxPatternBars]` 范围内，否则不得命中。

#### Scenario: 形态跨度过短或过长
- **WHEN** `RS - LS` 小于 `minPatternBars` 或大于 `maxPatternBars`
- **THEN** 系统 MUST 返回 `hit=false`

### Requirement: 评分与命中判定
系统 MUST 计算一个 \(0 \le score \le 1\) 的评分，并以 `score >= minScore` 作为命中条件。评分的组成因子 MUST 至少考虑：

- 头部突出度（越大越好）
- 左右肩一致性（越一致越好）
- 颈线稳定性（斜率越小越好）
- 形态跨度落在合理区间（偏离越大扣分）

#### Scenario: 评分不足
- **WHEN** 候选形态评分小于 `minScore`
- **THEN** 系统 MUST 返回 `hit=false` 且输出 `score`

#### Scenario: 命中
- **WHEN** 候选形态评分大于等于 `minScore`
- **THEN** 系统 MUST 返回 `hit=true` 且输出 `score` 与关键点信息

### Requirement: 输出字段规范
系统 MUST 在输出中提供以下字段（名称与语义必须一致）：

- `hit`：布尔值
- `score`：0~1 浮点
- `reason`：可选字符串（未命中/异常时的原因）
- `points`：关键点集合（至少包含 `LS`、`T`、`RS`、`NL1`、`NL2` 的 bar index 与 price）
- `neckline`：颈线信息（至少包含斜率与两点）
- `window`：本次识别使用的窗口（起止 bar index 或日期）

#### Scenario: 命中输出
- **WHEN** `hit=true`
- **THEN** 系统 MUST 输出 `points`、`neckline`、`window`

#### Scenario: 未命中输出
- **WHEN** `hit=false`
- **THEN** 系统 MUST 仍然输出 `score`（若已计算）与 `reason`（若可诊断）

