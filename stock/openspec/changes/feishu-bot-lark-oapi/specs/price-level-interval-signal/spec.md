## ADDED Requirements

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
