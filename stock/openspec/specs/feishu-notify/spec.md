# 飞书通知（feishu-notify）

本文档由变更 `feishu-bot-lark-oapi` 等合并入主规格库。

## Requirements

### Requirement: 全局通知渠道选择为飞书时启用飞书 group 解析

系统 MUST 提供一个全局通知渠道选择（至少包含“微信/飞书”）；当全局通知渠道选择为“飞书”时，系统 MUST 使用“飞书设置”中的 `groups` 列表来解析业务侧传入的 `group_id`（或 `group_ids`）并发送消息。

#### Scenario: 全局选择飞书后按飞书 groups 发送
- **WHEN** 全局通知渠道为“飞书”，且业务侧请求向某个 `group_id` 发送一条文本消息
- **THEN** 系统 MUST 从飞书 `groups` 中找到该 `id` 对应的配置并完成发送（或返回明确错误）

### Requirement: 飞书 group 配置可维护

系统 MUST 在设置中提供“飞书设置”，并允许用户维护一个 `groups` 列表；每个 group MUST 至少包含：
- `id`：用于在规则中引用的稳定标识（字符串）
- `name`：用于界面展示的名称
- `send_mode`：枚举 `oapi` 或 `https`

#### Scenario: 新增一个 oapi group
- **WHEN** 用户新增 group 并选择 `send_mode = oapi`，填写必填字段后保存
- **THEN** 系统 MUST 保存该 group，并在后续可被选择为通知目的地

#### Scenario: 新增一个 https group
- **WHEN** 用户新增 group 并选择 `send_mode = https`，填写必填字段后保存
- **THEN** 系统 MUST 保存该 group，并在后续可被选择为通知目的地

### Requirement: OAPI 发送模式的字段与校验

当 group 的 `send_mode = oapi` 时，系统 MUST 要求该 group 配置包含发送目标标识（例如 `chat_id` 或等价字段）；系统 MUST 在保存时校验该字段存在且为非空字符串。

#### Scenario: 缺失 chat_id 拒绝保存
- **WHEN** 用户保存 `send_mode = oapi` 的 group 且发送目标标识缺失或为空
- **THEN** 系统 MUST 拒绝保存并返回可理解的校验错误

### Requirement: HTTPS 发送模式的字段与校验

当 group 的 `send_mode = https` 时，系统 MUST 要求该 group 配置包含目标 URL（例如 `webhook_url` 或等价字段）；系统 MUST 在保存时校验其为非空字符串。

#### Scenario: 缺失 webhook_url 拒绝保存
- **WHEN** 用户保存 `send_mode = https` 的 group 且目标 URL 缺失或为空
- **THEN** 系统 MUST 拒绝保存并返回可理解的校验错误

### Requirement: 按 group 的 send_mode 路由发送实现

系统 MUST 在发送通知消息时，根据目标 group 的 `send_mode` 选择发送实现：
- `oapi`：通过 `lark-oapi` 调用飞书 OAPI 发送
- `https`：通过 HTTP POST 请求发送

#### Scenario: 发送到 oapi group
- **WHEN** 系统需要向 `send_mode = oapi` 的 group 发送一条文本消息
- **THEN** 系统 MUST 使用 OAPI 发送实现完成发送或返回明确错误

#### Scenario: 发送到 https group
- **WHEN** 系统需要向 `send_mode = https` 的 group 发送一条文本消息
- **THEN** 系统 MUST 使用 HTTPS 发送实现完成发送或返回明确错误

### Requirement: 解析不到 group_id 时返回可理解错误

当全局通知渠道为“飞书”且业务侧传入的 `group_id` 未在飞书 `groups` 列表中找到时，系统 MUST 返回/记录可理解的错误信息（包含缺失的 `group_id`），且 MUST NOT 继续尝试发送。

#### Scenario: group_id 不存在
- **WHEN** 全局通知渠道为“飞书”且发送目标 `group_id` 不存在于飞书 `groups`
- **THEN** 系统 MUST 返回/记录可理解错误并不进行发送

### Requirement: 发送失败的可定位错误信息

当飞书发送失败时，系统 MUST 输出可定位的错误信息（例如错误码、HTTP 状态、失败原因摘要），且 MUST 避免在日志中输出敏感凭证。

#### Scenario: OAPI 调用失败
- **WHEN** OAPI 返回失败响应或请求超时
- **THEN** 系统 MUST 返回/记录可定位错误信息且不包含敏感凭证

#### Scenario: HTTPS 调用失败
- **WHEN** HTTPS POST 返回非 2xx 或请求超时
- **THEN** 系统 MUST 返回/记录可定位错误信息且不包含敏感凭证
