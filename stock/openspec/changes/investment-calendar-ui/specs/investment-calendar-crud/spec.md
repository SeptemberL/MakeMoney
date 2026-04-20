## ADDED Requirements

### Requirement: 按账号隔离访问日历项
系统 MUST 将投资日历项与当前账号绑定。任何读取或写入 MUST 只作用于当前账号的数据，且不得通过参数越权访问其他账号的数据。

#### Scenario: 读取仅返回当前账号数据
- **WHEN** 用户以账号 A 请求查询某月日历项
- **THEN** 系统仅返回账号 A 的日历项，不包含账号 B 的任何数据

#### Scenario: 越权更新被拒绝
- **WHEN** 用户以账号 A 尝试更新属于账号 B 的日历项
- **THEN** 系统拒绝该请求并返回“未授权/不存在”的一致错误语义

### Requirement: 查询指定日期范围的日历项
系统 SHALL 支持按日期范围查询日历项，返回结果 MUST 包含每条日历项的唯一标识与字段（date/content/reminder_group/reminder_message/created_at/updated_at）。

#### Scenario: 查询某月范围
- **WHEN** 用户请求查询 2026-04-01 到 2026-04-30 的范围
- **THEN** 系统返回该范围内的所有日历项，且每条都包含 `date`

### Requirement: 创建日历项
系统 SHALL 允许创建日历项。创建请求 MUST 指定 `date`（YYYY-MM-DD）与 `content`，提醒字段为可选。

#### Scenario: 创建成功
- **WHEN** 用户提交合法的 `date` 与非空 `content`
- **THEN** 系统创建记录并返回新建日历项（含唯一 id 与时间戳）

#### Scenario: 日期格式非法
- **WHEN** 用户提交 `date=2026/04/20`
- **THEN** 系统拒绝请求并返回“日期格式非法”的错误信息

### Requirement: 更新日历项
系统 SHALL 支持更新指定 id 的日历项字段。更新时 MUST 只允许修改该记录的业务字段（content/reminder_group/reminder_message），且保持 `date` 不被隐式变更（除非明确提供“变更日期”的能力）。

#### Scenario: 更新内容成功
- **WHEN** 用户对既有日历项 id 提交新的 `content`
- **THEN** 系统更新该记录并返回更新后的日历项（含新的 `updated_at`）

### Requirement: 删除日历项
系统 SHALL 支持删除指定 id 的日历项。删除成功后再次读取该 id MUST 表现为不存在。

#### Scenario: 删除成功
- **WHEN** 用户请求删除一个存在的日历项 id
- **THEN** 系统删除该记录并返回成功结果

#### Scenario: 删除后不可再读取
- **WHEN** 用户删除成功后再次请求读取该 id
- **THEN** 系统返回“不存在”的一致错误语义

### Requirement: 结果排序稳定
系统 SHALL 对查询结果提供稳定排序（至少按 `date` 升序，其次按 `id` 或 `created_at`）。

#### Scenario: 同日多条排序稳定
- **WHEN** 同一日期存在多条日历项并被查询返回
- **THEN** 系统返回的顺序稳定且可预测

