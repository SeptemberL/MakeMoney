## ADDED Requirements

### Requirement: 通过 config.ini 选择通知通道

系统 SHALL 支持在配置中指定信号类通知使用的通道为 **微信** 或 **飞书**。未配置或非法值时 MUST 回退为与现有部署一致的行为（默认 **微信**）。

#### Scenario: 默认走微信

- **WHEN** 未设置通知通道或设置为 `wechat`
- **THEN** 发送逻辑 MUST 使用现有微信客户端与 `WXGroupManager` 解析的聊天名发送（在 wx 实例不可用时保持与当前一致的降级行为，如仅打日志）

#### Scenario: 选择飞书

- **WHEN** 通知通道设置为 `feishu`
- **THEN** 系统 MUST 使用飞书机器人 Webhook 通过 HTTP POST 发送文本消息，而不得调用微信 `SendMsg`

### Requirement: 飞书 Webhook 与请求格式

当通道为飞书时，系统 MUST 从配置读取机器人 **Webhook 完整 URL**，并向该 URL 发起 **HTTPS POST**，请求头包含 `Content-Type: application/json`，请求体为 JSON，且文本消息 MUST 符合飞书自定义机器人约定，例如：`{"msg_type":"text","content":{"text":"<渲染后的消息正文>"}}`。

#### Scenario: 配置缺失

- **WHEN** 通道为 `feishu` 但 Webhook URL 未配置或为空
- **THEN** 系统 MUST NOT 发起无效请求，并 MUST 记录可诊断的日志（日志中不得输出完整密钥 URL）

#### Scenario: 发送成功判定

- **WHEN** HTTP 响应与飞书返回体表明发送成功
- **THEN** 系统 MUST 视为该次通知已送达并完成与现有信号流程一致的后续步骤（如状态更新不因此失败）

#### Scenario: 发送失败

- **WHEN** 网络错误、非成功 HTTP 状态或飞书返回业务错误
- **THEN** 系统 MUST 记录错误日志且 MUST NOT 因通知失败而中断信号引擎主流程

### Requirement: 与 group_id 的 V1 语义

在飞书通道下，系统 MAY 使用单一 Webhook 对应单一群聊；**V1** 实现中对同一条消息在多个 `group_id` 上的行为 MUST 在设计中明确（建议：同一文本仅发送一次到该 Webhook，避免重复）。

#### Scenario: 多 group_id 不重复刷屏

- **WHEN** 一条信号规则关联多个 `group_id` 且通道为飞书
- **THEN** 系统 MUST NOT 向同一 Webhook 连续发送多条完全相同的正文（除非后续规格扩展「每群一 Webhook」映射）

### Requirement: 无数据库表结构变更

本能力 MUST NOT 要求新增或修改 MySQL/SQLite 表结构；配置仅来自 `config.ini`（或与现有 `Config` 单例等价的配置源）。
