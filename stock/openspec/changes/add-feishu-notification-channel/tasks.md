## 1. 配置与文档

- [x] 1.1 在根目录 `config.ini` 示例（及 `configs/config.ini` 若项目要求双份同步）增加 `[NOTIFY] channel` 与 `[FEISHU] webhook_url`、可选 `timeout_seconds` 说明注释
- [x] 1.2 核对 `Config` 与 `Managers/ConfigManager` 是否指向同一配置文件；若不一致，在实现中统一或明确文档约定，避免信号读到旧配置
- [x] 1.3 （可选）更新 `Docs/信号通知系统.md` 或 `Docs/项目基础框架.md` 中配置表，说明微信/飞书切换与飞书 Webhook 格式

## 2. 飞书 HTTP 发送

- [x] 2.1 新增飞书发送函数（建议模块：`Managers/feishu_bot.py` 或 `notifications/feishu.py`）：`POST` JSON，`msg_type=text`，`content.text` 为传入字符串；使用 `requests`，超时可配置
- [x] 2.2 解析响应：HTTP 2xx 且飞书业务码表示成功时返回成功；否则打日志（脱敏 URL）并返回失败
- [x] 2.3 对过长文本或飞书限制做截断或记录 warning（若官方有长度限制，按文档处理）

## 3. 信号发送适配

- [x] 3.1 在 `Config`（或统一配置入口）增加读取 `notify.channel`、`feishu.webhook_url`、`feishu.timeout_seconds`
- [x] 3.2 重构 `routes._send_signal_to_group`：根据 `channel` 分派；`feishu` 分支调用 2.1，**V1** 对多 `group_id` 去重为单次发送（与设计一致）
- [x] 3.3 `wechat` 分支保持现有逻辑：`stockGlobal.wx`、`WXGroupManager`、`SendMsg`

## 4. 验证

- [x] 4.1 本地 `channel=wechat` 回归：无微信实例时仍为日志模拟行为，与改前一致
- [x] 4.2 `channel=feishu` + 有效 Webhook：触发测试信号或最小脚本，确认群内收到文本
- [x] 4.3 `channel=feishu` 且缺少 `webhook_url`：确认不崩溃且有明确日志
