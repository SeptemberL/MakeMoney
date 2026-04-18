## 1. 依赖与基础结构

- [x] 1.1 将 `lark-oapi` 加入项目依赖（requirements/poetry/pipenv 以项目现状为准），并补齐最小可运行示例导入
- [x] 1.2 新增飞书通知模块骨架（如 `feishu/` 或 `notifiers/feishu_*.py`），定义统一的发送接口（text message）与错误类型
- [x] 1.3 为“通知目的地 group”新增/扩展配置结构：`feishu.groups[]`（含 `id/name/send_mode`）及两种模式所需字段（`chat_id` 或 `webhook_url`）

## 2. 设置界面：飞书设置与 group 列表

- [x] 2.1 在设置界面新增“飞书设置”入口与表单（对齐现有“微信”设置的交互）
- [x] 2.2 支持维护 `groups` 列表：新增/编辑/删除（至少包含 `id/name/send_mode`）
- [x] 2.3 `send_mode=oapi` 时展示并校验 `chat_id`（或项目选定的 OAPI 目标字段）；缺失时阻止保存并给出错误提示
- [x] 2.4 `send_mode=https` 时展示并校验 `webhook_url`；缺失时阻止保存并给出错误提示
- [x] 2.5 保存设置时确保持久化到项目配置文件，并避免在 UI/日志中泄露敏感字段
- [x] 2.6 确保设置中存在全局通知渠道开关（微信/飞书）：选择飞书时，业务侧 `group_id` 将从飞书 `groups` 解析；选择微信时保持从微信配置解析

## 3. 发送实现：OAPI 与 HTTPS 两条链路

- [x] 3.1 实现 `FeishuOapiSender`：使用 `lark-oapi` 完成鉴权与发送（超时/错误包装/最小日志）
- [x] 3.2 实现 `FeishuHttpsSender`：对 webhook URL 进行 POST 发送（超时/错误包装/最小日志）
- [x] 3.3 实现发送路由：根据 group 的 `send_mode` 选择 sender，并统一输出成功/失败结果
- [x] 3.4 发送失败时记录可定位错误信息（HTTP 状态/错误码/摘要），并确保不输出敏感凭证

## 4. 与信号通知系统集成

- [x] 4.1 保持信号/业务侧接口不变：仍只传 `group_id` / `group_ids`（不新增“飞书 group”目的地类型）
- [x] 4.2 通知发送时根据全局通知渠道开关选择 group 配置来源：微信 → 读微信配置；飞书 → 读飞书 `groups`
- [x] 4.3 当全局渠道为飞书时：将 `group_id` 映射到 `feishu.groups[].id`，并按该 group 的 `send_mode` 路由 OAPI/HTTPS sender
- [x] 4.4 校验规则的 `group_ids`：按全局渠道开关校验其在对应渠道的 group 配置中存在；不存在则拒绝保存并返回可理解错误
- [x] 4.5 补齐配置示例文件（如 `configs/tasks_config*.yaml`）：展示“同一套规则仅填写 groupID”，并分别给出全局选择微信/飞书时的 group 配置示例（飞书示例包含 `oapi` 与 `https` 两种 send_mode）

## 5. 测试与回归

- [ ] 5.1 为配置校验添加单元测试：oapi 必填字段、https 必填字段、未知 group 引用拒绝保存
- [ ] 5.2 为发送路由添加单元测试：同一消息对不同 group 走不同 sender（mock 掉网络/OAPI）
- [ ] 5.3 增加一个最小集成测试/手动验收清单：UI 配置 → 触发一条信号 → 成功发送到飞书（oapi 与 https 各验证一次）
