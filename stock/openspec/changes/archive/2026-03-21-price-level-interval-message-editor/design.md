## Context

`price_level_interval` 与 `price_range` 共用 `signal_rule.message_template`。当前实现里 `renderSignalTypeFields` / `renderWlSignalTypeFields` 将「主模板」区域在 `isFib || isPl` 时一并隐藏，价位间隔用户看不到 `messageTemplate` / `wlTemplate`。

## Goals / Non-Goals

**Goals:**

- 价位间隔选中时，主消息模板 textarea **可见、可编辑**，保存与加载与其它类型一致。
- 新建时默认填入 `DEFAULT_TEMPLATES.price_level_interval`（若当前逻辑已存在则保留）；编辑时以服务端 `message_template` 为准。
- 自选页与 signal_notify 页行为一致。

**Non-Goals:**

- 不引入富文本编辑器或新存储字段（仍用单列 `message_template`）。
- 不改变价位间隔触发/节流后端语义。

## Decisions

1. **单独区块 vs 复用 priceRangeTemplateSection**  
   - *决策*：价位间隔与价格区间共用同一「主模板」textarea（与数据模型一致），仅调整 `display` 规则：在 `isPl` 时与 `price_range` 一样显示主模板区，而非与 fib 一并隐藏。  
   - *备选*：复制一份专用 textarea；*否决*：易造成两处不同步。

2. **黄金分割仍独占三区模板**  
   - 仅 fib 显示 `fibTemplateSection`；价位间隔只显示主模板 + 价位参数区。

## Risks / Trade-offs

- **[Risk] 布局上模板出现在参数块下方或上方** → 保持与 price_range 相同相对顺序，降低用户认知成本。

## Migration Plan

- 纯前端（及可能的极小 API 修补）；无需数据库迁移。

## Open Questions

- 无。
