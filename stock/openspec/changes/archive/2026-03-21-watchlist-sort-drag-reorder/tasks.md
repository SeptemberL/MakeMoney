## 1. 状态与数据流

- [x] 1.1 在 `watchlist.html` 脚本中增加排序状态模型（当前排序列 id、方向：`none`|`asc`|`desc`），以及进入排序前可选的 `canonicalOrder`（`stock_code` 列表）用于恢复无排序
- [x] 1.2 梳理并统一「权威 items 数组」来源：拖拽后与 `persistWatchlistItems` / `loadWatchlistItems` / 服务器加载路径一致，避免合并持仓后顺序分叉

## 2. 表头三态排序

- [x] 2.1 为「股票名称、当日价格、涨跌幅、分时均价」表头增加可点击区域与三态指示（▲/▼/无）
- [x] 2.2 实现单列排序：激活一列时取消其他列排序态；按列类型解析比较键（数值列解析数字，名称 `localeCompare`，缺失值规则与规格一致）
- [x] 2.3 应用排序时重排 `tbody` 中 `tr.watchlist-row` 或基于 items 重绘，并更新左侧行号显示

## 3. 行号拖拽（仅无排序）

- [x] 3.1 为行号 `td` 设置 `draggable`、样式（`cursor`、提示文案），在排序激活时禁用拖拽
- [x] 3.2 实现 `dragstart`/`dragover`/`drop`/`dragend`（或等价）以在 `tbody` 内移动行，drop 后同步内存 items 顺序并调用 `persistWatchlistItems`
- [x] 3.3 确保 `renderWatchlistItems` 生成的行包含相同结构与拖拽绑定逻辑

## 4. 与刷新及回归

- [x] 4.1 验证 `refreshQuotesOnce` 在排序态与无排序态下均只更新报价单元格、不改变既定顺序语义
- [x] 4.2 手工回归：已登录/未登录、添加自选、与持仓合并、拖拽保存后刷新页面顺序是否保持
- [x] 4.3 （可选）更新 `Docs/自选列表.md` 简述排序与拖拽规则
