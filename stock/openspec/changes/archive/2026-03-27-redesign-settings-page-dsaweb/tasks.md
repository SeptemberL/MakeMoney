## 1. 数据模型与持久化

- [x] 1.1 新增 `system_settings` 表结构与唯一约束（`group_name + setting_key`），并在 **MySQL + SQLite** 双实现同步落地
- [x] 1.2 在数据库访问层新增设置读写方法（按分组查询、批量 upsert）
- [x] 1.3 启动或首次访问时提供从 `config.ini` 到 `system_settings` 的默认值初始化逻辑（仅缺失时）

## 2. 后端 API 与校验

- [x] 2.1 新增 `GET /api/settings/schema`，返回分组与字段定义（基础/通信/Tushare）
- [x] 2.2 新增 `GET /api/settings`，返回合并后的当前配置（DB 优先，缺省回退 ini）
- [x] 2.3 新增 `PUT /api/settings`，按分组保存并做字段校验
- [x] 2.4 实现动态校验规则：
  - `DB_TYPE=mysql` 要求 MySQL 字段完整；`sqlite` 跳过 MySQL 必填
  - `channel=feishu` 要求 `webhook_url`，可选 `sign/timeout_seconds`
  - `channel=wx` 要求 `message_group`

## 3. dsaweb 设置页重构

- [x] 3.1 在 dsaweb 竖向 Tab 中保留“设置”为末项，并路由到新的设置页面
- [x] 3.2 新设置页按 `schema` 动态渲染分组表单（基础设置/通信设置/Tushare）
- [x] 3.3 根据用户选择动态显示字段（mysql/sqlite，wx/feishu）
- [x] 3.4 提交保存后展示成功/失败提示，并标注“是否需重启生效”

## 4. 配置读取接入

- [x] 4.1 统一配置读取入口，支持 DB 优先 + ini 回退
- [x] 4.2 通知通道（WX/FEISHU）读取新设置值并回归验证
- [x] 4.3 Tushare 读取 token 新路径并验证相关接口可用

## 5. 回归与文档

- [x] 5.1 回归：mysql/sqlite 两种模式下设置页显示与保存行为正确
- [x] 5.2 回归：通信通道切换后消息发送行为正确（WX 与 FEISHU）
- [x] 5.3 更新文档：`Docs/项目基础框架.md` 与设置说明，补充新表、API 与配置优先级
