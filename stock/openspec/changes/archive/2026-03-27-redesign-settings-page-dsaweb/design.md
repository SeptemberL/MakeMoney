## Context

- 当前配置读取主路径为 `config.py:Config`（读取 `config.ini`），部分模块已支持 FEISHU/WX 切换。
- 现有 `dsaweb` 已具备工作台壳层（竖向 Tab + iframe）风格，适合承载设置中心。
- 用户要求新增数据库表保存设置，且涉及表结构改动时必须同时支持 MySQL 与 SQLite。

## Goals / Non-Goals

**Goals:**

- 设计统一设置数据模型与 API，覆盖基础设置、通信工具、Tushare。
- 设置页基于 dsaweb 风格重构，支持按配置动态显示字段。
- 保存后配置可被现有通知与数据模块读取，并具备基础校验。
- MySQL/SQLite 双引擎结构与语义一致。

**Non-goals:**

- 细粒度 RBAC 权限体系。
- 热更新所有运行中组件（允许“保存后提示部分配置需重启”）。

## Decisions

1. **数据库模型**
   - 新增 `system_settings` 表（键值 + 分组）作为通用配置存储。
   - 建议字段：`id`, `group_name`, `setting_key`, `setting_value`, `value_type`, `updated_at`。
   - 唯一约束：`(group_name, setting_key)`。
   - 理由：兼容后续扩展，避免每类配置单独建表。

2. **配置优先级**
   - 运行时读取优先级：`DB(system_settings) > config.ini 默认值`。
   - 保存设置只写数据库；可选提供“导出到 ini”功能（后续）。

3. **动态表单规则**
   - 基础设置：`DB_TYPE=mysql` 时显示 MySQL 字段（host/port/name/user/password/charset），`sqlite` 时显示 `DB_PATH`。
   - 通信设置：`channel=feishu` 显示 `webhook_url/sign/timeout_seconds`；`channel=wx` 显示 `message_group`。

4. **安全与脱敏**
   - 密钥类字段（如 Tushare token、Feishu sign）返回时可部分脱敏；保存时明文入库（与现状一致）或后续加密。
   - 日志中禁止输出完整敏感值。

5. **API 设计（建议）**
   - `GET /api/settings/schema`：返回分组与字段元数据（前端动态渲染）。
   - `GET /api/settings`：返回当前值（已合并默认值）。
   - `PUT /api/settings`：按分组保存，带后端校验。

## Risks / Trade-offs

- **[Risk] 数据库配置存储在数据库本身（鸡生蛋问题）**：首次连接仍依赖 `config.ini`，数据库配置作为“业务层连接参数”或“下一次重启生效”。
- **[Risk] 敏感信息明文保存**：短期沿用现状，后续可引入加密或系统密钥保护。
- **[Trade-off] 通用 KV 表 vs 专用表**：KV 灵活但约束弱；通过 schema 校验与类型字段缓解。

## Migration Plan

1. 增加 `system_settings` 表（MySQL + SQLite 同步）。
2. 启动后若表为空，可按 `config.ini` 初始化关键默认项。
3. 上线设置页与 API，逐步从文件直改迁移到页面维护。

## Open Questions

- `message_group` 具体是群组 ID（int）还是 chat_list 名称（string）？建议统一为 group_id（int）。
- 是否允许在线修改数据库连接立即生效，或统一“保存后重启生效”？建议后者更稳妥。
