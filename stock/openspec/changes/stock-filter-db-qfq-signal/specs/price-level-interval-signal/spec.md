## MODIFIED Requirements

### Requirement: 条件为真时按间隔发送消息

当规则启用且当前报价更新时，若 `mode` 定义的条件相对 `target_price` 为真，系统 SHALL 向该规则关联的每个 `group_id` 发送一条由模板渲染的消息；且任意两次成功发送之间的时间间隔 MUST 大于等于 `send_interval_seconds`（以服务器处理该规则的时钟为准）。用于计算“当前报价”的数据源 MUST 为数据库行情数据，并在进行比较/计算前将未复权行情按数据库中的前复权因子转换为前复权口径；当复权因子缺失导致无法完成转换时，系统 MUST 按既定缺失策略处理并在输出中显式标注口径（不得静默当作已复权数据继续计算）。

#### Scenario: 首次进入条件立即允许首条（受最小间隔约束）

- **WHEN** 条件由假变为真，且自上次成功发送以来已超过 `send_interval_seconds`（或从未发送过），且当前报价由“DB 行情 + 前复权转换”得到
- **THEN** 系统 MUST 在本次或后续满足间隔的更新中发送一条消息并更新 `last_sent_at`

#### Scenario: 条件持续为真时隔一段时间再发

- **WHEN** 条件持续为真，且距离上次成功发送已满 `send_interval_seconds`，且当前报价由“DB 行情 + 前复权转换”得到
- **THEN** 系统 MUST 再发送一条消息并更新 `last_sent_at`

#### Scenario: 未满间隔不发送

- **WHEN** 条件为真但距离上次成功发送未满 `send_interval_seconds`
- **THEN** 系统 MUST NOT 发送消息

#### Scenario: 缺失复权因子时不得静默按前复权计算
- **WHEN** 当前交易日缺失前复权因子，导致无法将 DB 未复权行情转换为前复权口径
- **THEN** 系统 MUST 按缺失策略跳过或回退，并在输出/日志中显式标注 `adjustment=raw_fallback` 或 `insufficient_data`

