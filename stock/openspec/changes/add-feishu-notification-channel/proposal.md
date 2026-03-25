## Why

信号与部分业务路径目前依赖本机 **微信客户端 + wxauto** 向群组发消息；在无桌面微信、服务器部署或希望用群机器人统一收告警时无法可靠送达。**飞书自定义机器人**支持通过 HTTPS POST 推送文本，配置简单、不依赖 GUI。需要在不破坏现有微信链路的前提下，增加可选通道，并由运维在 `config.ini` 中切换。

## What Changes

- 在 `config.ini` 中增加**通知通道**配置：可选择 **微信**（现有行为）或 **飞书**。
- 飞书模式下配置 **机器人 Webhook 完整 URL**（`https://open.feishu.cn/open-apis/bot/v2/hook/...`）。
- 实现飞书发送：**HTTP POST**、`Content-Type: application/json`，请求体为飞书要求的 JSON，例如文本类型：`{"msg_type":"text","content":{"text":"..."}}`。
- 将现有「信号 → 发消息」入口（如 `routes._send_signal_to_group`）改为经统一适配层按配置选择微信或飞书；微信路径保持与现有一致（`WXGroupManager` + `wx.SendMsg`）。

## Capabilities

### New Capabilities

- `signal-notify-channel`：基于 `config.ini` 的微信/飞书通道选择、飞书 Webhook 文本发送及与信号发送适配器的集成要求。

### Modified Capabilities

- （无独立既有规格文件时视为新增；实现后与 `Docs/信号通知系统.md` 可选同步说明。）

## Impact

- **配置**：`config.ini`（示例与文档需补充 `[NOTIFY]` / `[FEISHU]` 或等价节）；注意勿将真实 Webhook 提交到版本库，可用 `.example` 说明。
- **代码**：`routes.py`（或抽离到 `Managers`/独立模块）、`Config` / `ConfigManager` 读取新项；可选封装 `FeishuBotClient` 便于测试。
- **依赖**：项目已有 `requests`，飞书 POST 优先使用 `requests`（与设计一致）。
- **数据库**：无表结构变更。

## Non-goals

- 本次不要求支持飞书富文本卡片、多 Webhook 按 `group_id` 路由（可作为后续变更）；不要求改前端信号表单。
- 不要求替代 NGA 等模块内若存在的独立微信推送逻辑（除非与信号共用同一适配器且零成本合并，见设计）。
