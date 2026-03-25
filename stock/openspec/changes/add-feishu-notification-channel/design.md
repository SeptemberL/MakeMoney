## Context

- 信号发送当前集中在 `routes._send_signal_to_group`：依赖 `stockGlobal.wx` 与 `WXGroupManager.find_wx_group(group_id)` 解析群聊名，再 `wx.SendMsg(message, chat_name)`。
- 全局配置由根目录 `config.py` 的 `Config` 单例读取 `config.ini`（UTF-8）；`Managers/ConfigManager.py` 为另一套路径（`Managers/config.ini`），实现阶段需确认信号路径实际使用的配置类，**避免双份 INI 行为不一致**（优先与 `routes` 已用的 `Config` 对齐）。
- 飞书机器人 Webhook 文档约定：`POST`，`Content-Type: application/json`，文本消息载荷形如 `{"msg_type":"text","content":{"text":"消息内容"}}`。

## Goals / Non-Goals

**Goals:**

- `config.ini` 可切换 `wechat` / `feishu`；飞书模式下用配置的 Webhook 发送与信号内容一致的纯文本。
- 失败时打日志且不阻断行情/信号主流程；微信模式行为与现网一致。
- Webhook URL、响应体错误信息在日志中脱敏（不全量打印密钥路径）。

**Non-goals:**

- 多群组多 Webhook 映射、@用户、卡片消息。
- 修改 `group_ids` 数据模型或管理 UI。

## Decisions

1. **配置节与键名（建议）**  
   - `[NOTIFY]`：`channel = wechat`（默认）或 `feishu`。  
   - `[FEISHU]`：`webhook_url = https://open.feishu.cn/open-apis/bot/v2/hook/...`（必填当 `channel=feishu`）。  
   - 可选：`timeout_seconds`（默认 10）。  
   - **理由**：与现有 `[WX]` 并列清晰；默认值保证未改配置的环境仍走微信。

2. **飞书与 `group_id` 的语义**  
   - **V1**：飞书通道下**忽略** `group_id`（单 Webhook 对应单一群/话题）；若规则带多个 `group_id`，对同一 Webhook **只发送一条**文本（避免重复刷屏），并在 DEBUG 日志中说明一次。  
   - **理由**：机器人 URL 通常一群一个；多群需要多个 URL 或后续扩展映射表。

3. **实现位置**  
   - 在 `routes` 或新建模块实现 `_send_signal_to_group` 内部分派：`channel==feishu` → 调用 `send_feishu_text(webhook_url, text)`；否则走现有微信逻辑。  
   - `send_feishu_text` 使用 `requests.post(..., json=payload, timeout=...)`，检查 HTTP 状态码与飞书返回 JSON 中 `StatusCode` / `code`（以官方当前响应为准：成功一般为 `0`）。

4. **错误与降级**  
   - `channel=feishu` 但 `webhook_url` 为空：记录 error，不发送（与微信无实例时「模拟日志」策略对齐，或统一为 warning + 跳过，在任务中择一并写清）。  
   - 不自动 fallback 到微信，避免误发到错误通道。

5. **测试**  
   - 单元测试可对 `send_feishu_text` mock `requests.post`；或提供仅开发环境调用的路由/脚本（若项目已有类似「测试发图」模式，可对齐风格，非必须）。

## Risks / Trade-offs

- **[Risk] Webhook 泄露** → 仅存 `config.ini` 本地；文档提醒勿提交；日志脱敏。  
- **[Trade-off] 飞书 V1 忽略 group_id** → 多群用户需多个实例或多个机器人；在 proposal/tasks 中标注后续可增强。

## Migration Plan

- 部署前在 `config.ini` 增加 `[NOTIFY]`，默认 `channel=wechat`，无需数据迁移。  
- 启用飞书时改为 `feishu` 并填写 `[FEISHU] webhook_url`，重启应用。

## Open Questions

- `Managers/ConfigManager` 与根目录 `Config` 是否应合并读取同一份 `config.ini`（若当前存在两份文件，是否以根目录为准）——在实现任务中核对并收敛。
