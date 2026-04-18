## ADDED Requirements

### Requirement: 设置中心应支持 dsaweb 统一入口

系统 SHALL 提供一个基于 dsaweb 风格的设置中心页面，包含竖向分组导航与表单编辑区域；设置入口在 dsaweb 导航中可访问，且“设置”项位于最后一项。

#### Scenario: 从 dsaweb 打开设置中心

- **WHEN** 用户在 dsaweb 点击“设置”
- **THEN** 系统 MUST 打开设置中心页面并加载当前配置

### Requirement: 设置持久化应使用数据库并支持双引擎

系统 MUST 使用数据库表持久化设置，并在 MySQL 与 SQLite 中保持结构与语义一致（字段、唯一约束、索引语义等价）。

#### Scenario: 新建设置表

- **WHEN** 系统初始化数据库结构
- **THEN** MySQL 与 SQLite MUST 同步创建设置表及必要唯一约束

#### Scenario: 保存后可重新读取

- **WHEN** 用户保存设置
- **THEN** 后续读取 MUST 返回刚保存的值

### Requirement: 基础设置需按数据库类型动态显示字段

设置中心在“基础设置”中 SHALL 根据 `DB_TYPE` 动态展示字段：当 `DB_TYPE=mysql` 时展示并允许编辑 MySQL 参数；当 `DB_TYPE=sqlite` 时不展示 MySQL 参数，仅展示 SQLite 相关字段。

#### Scenario: mysql 模式显示 MySQL 字段

- **WHEN** `DB_TYPE` 为 `mysql`
- **THEN** 页面 MUST 显示 `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD/DB_CHARSET`

#### Scenario: sqlite 模式隐藏 MySQL 字段

- **WHEN** `DB_TYPE` 为 `sqlite`
- **THEN** 页面 MUST 隐藏 MySQL 字段并显示 `DB_PATH`

### Requirement: 通信工具设置应支持 WX 与 FEISHU

设置中心 SHALL 支持通信通道在 `WX` 与 `FEISHU` 间切换，并根据通道显示对应字段。

#### Scenario: 选择 FEISHU

- **WHEN** 通道设置为 `feishu`
- **THEN** 页面 MUST 显示 `webhook_url`、`sign`、`timeout_seconds`，且保存时 `webhook_url` 必填

#### Scenario: 选择 WX

- **WHEN** 通道设置为 `wx`
- **THEN** 页面 MUST 显示 `message_group`，并按后端规则校验

### Requirement: Tushare 设置应可管理 token

系统 SHALL 支持在设置中心读取与保存 Tushare Token 等关键字段，并供运行时读取。

#### Scenario: 更新 Tushare Token

- **WHEN** 用户保存新的 `TUSHARE.TOKEN`
- **THEN** 设置读取接口 MUST 返回新值，并可被后续 Tushare 调用路径读取

### Requirement: 配置读取优先级

系统 MUST 定义并执行统一配置优先级：数据库设置优先，缺失项回退 `config.ini` 默认值。

#### Scenario: 数据库存有覆盖值

- **WHEN** 某设置项在数据库中存在
- **THEN** 运行时读取 MUST 使用数据库值而非 ini 默认

#### Scenario: 数据库缺失时回退

- **WHEN** 某设置项在数据库中不存在
- **THEN** 运行时读取 MUST 回退到 `config.ini` 对应项
