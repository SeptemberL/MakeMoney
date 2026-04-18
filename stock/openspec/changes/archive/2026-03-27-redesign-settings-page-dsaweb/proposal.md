## Why

当前系统配置主要分散在 `config.ini` 与少量 YAML 文件中，运维或业务用户修改配置需要直接编辑文件并重启，门槛高且容易误改。随着通知通道（WX/FEISHU）与持仓、信号、行情等模块增多，缺少统一设置入口会造成维护成本和配置一致性风险。

用户希望基于 `dsaweb` 的新框架重做设置页，并将关键设置持久化到数据库，覆盖：
- 基础服务配置（尤其数据库连接）
- 通信工具配置（WX / FEISHU）
- Tushare Token 等第三方接入配置

## What Changes

- 新增基于 `dsaweb` 的设置中心页面（竖向分组导航 + 表单区域），统一承载系统设置。
- 新增设置持久化数据库表（及必要索引），并提供 MySQL / SQLite 双引擎等价实现。
- 设置项按分组管理：
  - **基础设置**：读取当前 `DB_TYPE`，若为 `mysql` 显示并允许编辑 MySQL 连接项；若为 `sqlite` 隐藏 MySQL 输入，仅展示 SQLite 路径等相关项。
  - **通信工具设置**：在 `WX` 与 `FEISHU` 间切换；
    - FEISHU：`webhook_url`、`sign`、`timeout_seconds`
    - WX：`message_group`（或等价 group_id）
  - **Tushare 设置**：`TOKEN` 等必要字段。
- 增加后端设置 API（读取/保存/校验），并将保存结果同步到运行时配置读取路径（以数据库优先或明确覆盖策略）。

## Capabilities

### New Capabilities

- `settings-console`：提供 dsaweb 风格设置中心，支持分组编辑、动态表单显示、数据库持久化与双引擎一致性。

### Modified Capabilities

- `signal-notify-channel`（行为关联）：通知通道配置来源增加“设置中心 + 数据库持久化”路径。

## Impact

- **前端**：`templates/dsaweb.html` 扩展设置入口；新增/重构设置页面模板与脚本。
- **后端**：`routes.py`（或 settings 模块）新增设置读取/保存 API 与校验逻辑。
- **数据库**：新增设置表与访问层方法，MySQL/SQLite 同步实现。
- **配置策略**：需要定义 `config.ini` 与数据库配置的优先级与回写策略。

## Non-goals

- 本次不覆盖全部历史配置项（仅覆盖基础设置、通信工具、Tushare 核心字段）。
- 本次不实现复杂权限系统（可先沿用现有登录态控制）。
