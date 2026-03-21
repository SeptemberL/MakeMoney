## Why

价位间隔信号（`price_level_interval`）在后端已使用与其它规则相同的 `message_template` 字段，但前端在切换为该类型时**隐藏了主消息模板编辑区**（与黄金分割类似整块切换显示逻辑），导致用户无法在界面中填写或修改发送文案，只能落默认模板。需要在配置流程中**显式提供可编辑的发送消息/模板**并与保存、回显一致。

## What Changes

- 在 `signal_notify` 悬浮编辑器与自选列表信号弹窗中，当 `signal_type === price_level_interval` 时**展示消息模板（或等价「发送消息」）输入控件**，与 `price_range` 行为对齐。
- 保存（POST/PUT）时继续提交 `message_template`（或现有 API 字段名），确保与 `signal_rule.message_template` 持久化一致；编辑已有规则时正确回显用户自定义内容。
- 可选：在价位间隔参数区域旁增加简短占位符说明（与 `Docs/信号通知系统.md` 中 `target_price`、`mode_label` 等变量一致），降低编辑成本。

## Capabilities

### New Capabilities

- （无独立新能力包；属既有价位间隔能力的 UX/需求补全。）

### Modified Capabilities

- `price-level-interval-signal`：补充「管理与编辑器暴露」相关需求——价位间隔类型下 MUST 提供可编辑、可保存、可回显的发送消息（模板）配置，且不得仅依赖隐式默认。

## Impact

- **前端**：`templates/signal_notify.html`、`templates/watchlist.html` 中信号类型切换与表单布局逻辑。
- **后端**：若无字段缺失则**可能无需改 API**；若发现 PUT/校验未传递 `message_template` 则做小修复。
- **文档**：`Docs/信号通知系统.md` 可增一行说明价位间隔在 UI 中的模板编辑入口。
