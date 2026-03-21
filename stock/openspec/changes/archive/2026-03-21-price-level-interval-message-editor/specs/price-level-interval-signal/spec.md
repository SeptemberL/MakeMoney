## MODIFIED Requirements

### Requirement: 管理与编辑器暴露

悬浮/管理端 schema MUST 包含新信号类型选项及 `target_price`、`mode`、`send_interval_seconds` 字段说明；API 序列化与反序列化 MUST 与持久化模型一致。对于 `price_level_interval`，编辑器界面 MUST 提供与 `price_range` 同等级别的**发送消息模板**编辑能力：用户 SHALL 能够查看、修改并保存 `message_template`（或 API 中等价字段），且编辑已有规则时 MUST 回显已保存的模板内容；不得以「仅默认模板、界面不可见」作为唯一配置方式。

#### Scenario: 列出规则包含新类型

- **WHEN** 客户端请求信号规则列表
- **THEN** 响应中 MUST 能区分该新类型并返回上述参数

#### Scenario: 价位间隔可编辑发送模板

- **WHEN** 用户在界面中选择信号类型为价位间隔并打开新建或编辑表单
- **THEN** 系统 MUST 展示可编辑的消息模板输入控件，且保存后再次打开同一规则时 MUST 显示用户保存的模板文本

#### Scenario: 保存提交携带模板

- **WHEN** 用户修改价位间隔规则的消息模板并执行保存（创建或更新）
- **THEN** 请求体 MUST 包含模板内容并持久化到该规则的 `message_template`（或与现有 API 字段一致），且后续触发通知时使用该模板渲染消息
