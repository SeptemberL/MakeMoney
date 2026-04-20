## ADDED Requirements

### Requirement: 账号数据库持久化存储日历项
系统 MUST 将投资日历项持久化存储在账号数据库中，并保证同一账号的数据隔离与可迁移。

#### Scenario: 写入后可读取
- **WHEN** 用户创建一条日历项
- **THEN** 系统将其写入账号数据库，并可在后续查询中读取到

### Requirement: MySQL 与 SQLite 表结构语义一致
系统 MUST 同步维护 MySQL 与 SQLite 的建表与迁移逻辑，使表、字段、索引与约束语义一致。

#### Scenario: 双引擎均可完成初始化建表
- **WHEN** 系统在 MySQL 引擎初始化数据库结构
- **THEN** 日历相关表与索引被成功创建

#### Scenario: 双引擎结构保持一致
- **WHEN** 系统在 SQLite 引擎初始化数据库结构
- **THEN** 日历相关表与索引在语义上与 MySQL 版本一致（字段名/默认值/约束/索引意图一致）

### Requirement: 日历项表字段满足业务需求
系统 MUST 存储如下字段（名称可按项目约定微调，但语义不得丢失）：
- `account_id`: 账号标识
- `date`: 日历日期（按日，YYYY-MM-DD）
- `content`: 日历内容
- `reminder_group`: 提醒消息分组
- `reminder_message`: 提醒消息内容
- `created_at` / `updated_at`: 创建与更新时间

#### Scenario: 字段完整返回
- **WHEN** 系统查询返回某条日历项
- **THEN** 返回结果包含上述字段语义对应的数据（至少包含 date/content/reminder_group/reminder_message 与时间戳）

### Requirement: 支持按账号 + 日期范围高效查询
系统 SHALL 为常用查询提供索引，使得按 `account_id` + `date` 的范围查询在数据量增长后仍可接受。

#### Scenario: 月范围查询走索引意图
- **WHEN** 系统查询某账号在一个月范围内的日历项
- **THEN** 查询能够利用 `account_id` 与 `date` 的索引意图来限制扫描范围

### Requirement: 数据完整性与约束
系统 SHOULD 约束字段长度与空值行为以避免脏数据，并保证更新时刷新 `updated_at`。

#### Scenario: 更新刷新更新时间
- **WHEN** 系统更新一条日历项的内容
- **THEN** 该条记录的 `updated_at` 被刷新为新值

