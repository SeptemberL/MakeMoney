# 到价提醒信号（price_level_interval / price-level-interval-signal）

本文档由变更 `signal-interval-at-price-level`、`price-level-interval-message-editor` 等归档时合并入主规格库。

## Requirements

### Requirement: 到价提醒信号的配置与校验

系统 SHALL 支持一种用户可见名称为「到价提醒」、技术标识为 `price_level_interval` 的信号类型，其配置 MUST 包含：`stock_code`、`group_ids`、`target_price`（有限数值）、`mode`（枚举：`at_or_above` 表示当前价大于等于目标价时条件为真，`at_or_below` 表示当前价小于等于目标价时条件为真）、`send_interval_seconds`（正整数，且不小于系统规定的最小间隔，如 60）。

#### Scenario: 拒绝非法间隔

- **WHEN** 用户保存规则且 `send_interval_seconds` 小于系统最小间隔或不是正整数
- **THEN** 系统 MUST 拒绝保存并返回可理解的校验错误

#### Scenario: 拒绝非法目标价

- **WHEN** `target_price` 缺失或非有限数值
- **THEN** 系统 MUST 拒绝保存

### Requirement: 条件为真时按间隔发送消息

当规则启用且当前报价更新时，若 `mode` 定义的条件相对 `target_price` 为真，系统 SHALL 向该规则关联的每个 `group_id` 发送一条由模板渲染的消息；且任意两次成功发送之间的时间间隔 MUST 大于等于 `send_interval_seconds`（以服务器处理该规则的时钟为准）。

#### Scenario: 首次进入条件立即允许首条（受最小间隔约束）

- **WHEN** 条件由假变为真，且自上次成功发送以来已超过 `send_interval_seconds`（或从未发送过）
- **THEN** 系统 MUST 在本次或后续满足间隔的更新中发送一条消息并更新 `last_sent_at`

#### Scenario: 条件持续为真时隔一段时间再发

- **WHEN** 条件持续为真，且距离上次成功发送已满 `send_interval_seconds`
- **THEN** 系统 MUST 再发送一条消息并更新 `last_sent_at`

#### Scenario: 未满间隔不发送

- **WHEN** 条件为真但距离上次成功发送未满 `send_interval_seconds`
- **THEN** 系统 MUST NOT 发送消息

### Requirement: 条件为假时停止发送

当 `mode` 定义的条件为假时，系统 MUST NOT 发送消息；条件再次变为真时，发送行为 MUST 仍遵守「两次成功发送之间间隔 ≥ `send_interval_seconds`」的规则（不得以条件闪断绕过间隔）。

#### Scenario: 条件由真变假

- **WHEN** 当前价使条件为假
- **THEN** 系统 MUST NOT 发送消息

### Requirement: 持久化与双引擎一致性

规则参数与运行态（至少包含 `last_sent_at`，以及实现穿越模式时所需的上一价格）MUST 持久化；数据库为 MySQL 与 SQLite 时，表结构与迁移 MUST 同步更新且语义等价。

#### Scenario: 重启后保留节流状态

- **WHEN** 进程重启后加载已有规则状态
- **THEN** 系统 MUST 继续使用已存储的 `last_sent_at` 计算是否到达下一发送时刻

### Requirement: 管理与编辑器暴露

悬浮/管理端 schema MUST 包含新信号类型选项及 `target_price`、`mode`、`send_interval_seconds` 字段说明；API 序列化与反序列化 MUST 与持久化模型一致。对于 `price_level_interval`，编辑器界面 MUST 提供与 `price_range` 同等级别的**发送消息模板**编辑能力：用户 SHALL 能够查看、修改并保存 `message_template`（或 API 中等价字段），且编辑已有规则时 MUST 回显已保存的模板内容；不得以「仅默认模板、界面不可见」作为唯一配置方式。

#### Scenario: 列出规则包含新类型

- **WHEN** 客户端请求信号规则列表
- **THEN** 响应中 MUST 能区分该新类型并返回上述参数

#### Scenario: 到价提醒可编辑发送模板

- **WHEN** 用户在界面中选择信号类型为到价提醒（`price_level_interval`）并打开新建或编辑表单
- **THEN** 系统 MUST 展示可编辑的消息模板输入控件，且保存后再次打开同一规则时 MUST 显示用户保存的模板文本

#### Scenario: 保存提交携带模板

- **WHEN** 用户修改到价提醒规则的消息模板并执行保存（创建或更新）
- **THEN** 请求体 MUST 包含模板内容并持久化到该规则的 `message_template`（或与现有 API 字段一致），且后续触发通知时使用该模板渲染消息

---

以下由变更 `feishu-bot-lark-oapi` 合并补充。

### Requirement: 到价提醒规则仅配置 group_ids，发送渠道由全局设置决定

系统 MUST 允许到价提醒信号规则仅通过 `group_ids` 指定通知目的地；当规则触发需要发送消息时，系统 MUST 根据全局通知渠道设置决定从对应渠道的 group 配置解析并发送（例如全局为“飞书”则解析飞书 `groups`，全局为“微信”则解析微信配置）。

#### Scenario: 规则配置包含 group_ids
- **WHEN** 用户创建或编辑到价提醒规则，并将一个或多个 `group_id` 作为通知目的地保存
- **THEN** 系统 MUST 成功保存该配置（在校验通过的前提下）

#### Scenario: 触发发送时按全局渠道投递
- **WHEN** 到价提醒规则满足触发条件且到达允许发送的间隔，并配置了 `group_ids` 作为目的地
- **THEN** 系统 MUST 按全局通知渠道设置，将消息投递到每个 `group_id` 对应的群

### Requirement: group_id 校验由全局通知渠道决定

系统 MUST 在保存到价提醒规则时，按全局通知渠道进行校验：
- 当全局渠道为“飞书”时：`group_ids` MUST 存在于飞书 `groups[].id`
- 当全局渠道为“微信”时：`group_ids` MUST 存在于微信的 group 配置中

#### Scenario: 引用未知 group_id
- **WHEN** 用户保存到价提醒规则且其 `group_ids` 包含一个在当前全局渠道配置中不存在的 `group_id`
- **THEN** 系统 MUST 拒绝保存并返回可理解的校验错误
