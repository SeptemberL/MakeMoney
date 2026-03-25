## Context

- 自选数据：未登录存 `localStorage`（`watchlist_items_v1`），已登录经 `GET/PUT /api/watchlist`；`replace_user_watchlist` 按数组下标写入 `sort_order`，与「用户顺序」一致。
- 页面以 `renderWatchlistItems` 重建行，并由 `refreshQuotesOnce` 按 `data-stock-code` 回填行情；排序/拖拽必须保留 `tr.watchlist-row` 结构与类名，避免破坏刷新逻辑。

## Goals / Non-Goals

**Goals:**

- 表头三态排序 + 无排序时行号列拖拽重排，并重排后触发既有持久化。
- 排序列与缺省规则在规格中列清；实现用稳定比较（同值按 `stock_code` 或原始索引）避免抖动。

**Non-Goals:**

- 不要求服务端分页、多键排序或保存「上次排序列」到账号（除非实现阶段零成本附带 sessionStorage，可写入 Open Questions）。
- 不改动信号编辑器、持仓合并「只加不删」的业务规则（新股票仍按现有逻辑追加）。

## Decisions

1. **排序状态放在前端内存（+ 可选 sessionStorage）**  
   - 刷新页面默认**无排序**（或可选恢复上次排序，见 Open Questions）。  
   - **理由**：与现有无全局表状态架构一致；避免改 API。

2. **无排序时的「基准顺序」**  
   - 以内存中当前 `items` 数组顺序为准；拖拽后立刻 `persistWatchlistItems`。  
   - 进入**升/降序**时保留一份 `canonicalOrder`（`stock_code` 列表），回到无排序时按该快照重排 DOM 与内存数组（若快照与持久化已一致则等价于恢复添加顺序）。

3. **拖拽实现**  
   - 优先 **HTML5 Drag and Drop**（`draggable` 放在行号 `td`，`tbody` 监听 `dragover`/`drop`）以保持零依赖。  
   - 备选：轻量库；仅当无障碍或触摸端体验不达标时再评估。

4. **可排序列与解析**  
   - 价格、涨跌幅：解析当前单元格展示文本或 `data-*` 缓存数值（刷新后仍可比）。  
   - 分时均价：取主行 `.wl-day-avg` 数值；「-」视为空值，排序时置底或置顶需在规格中统一。  
   - 名称：用首列主行文本（股票名称）字典序，大小写/中文按 `localeCompare`。

5. **行号列 UI**  
   - 无排序时行号格显示 `⋮` 或 `⠿` 类提示 + `cursor: grab`，`title` 说明可拖动；排序激活时 `cursor: default` 并 `draggable=false`。

## Risks / Trade-offs

- **[Risk] 排序下列顺序与持久化顺序不一致，用户拖拽误以为已保存** → **Mitigation**：仅无排序可拖；重排后必须 `persistWatchlistItems` 并维持与合并逻辑共用同一 `items` 源。

- **[Risk] `refreshQuotesOnce` 与重排竞态** → **Mitigation**：刷新只更新单元格内容，不重建行；若重建行则须在刷新完成后重新绑定拖拽。

- **[Trade-off] 表格行拖拽在触摸设备上体验弱** → 文档注明以桌面为主；后续可加触摸专用控件。

## Migration Plan

- 仅前端与可选文档；无迁移脚本。部署后用户立即获得新交互。

## Open Questions

- 是否在 sessionStorage 中恢复上次排序列与方向（跨同标签页刷新）？默认提案为否，以降低复杂度。
