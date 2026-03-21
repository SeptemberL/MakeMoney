## Why

自选列表目前只展示现价与涨跌幅，缺少与同花顺分时图「均线」一致的**当日实时均价**参考；同时用户希望用与 `StockCalculateTools.html` 相同的 **0.98848 系数**派生**压力位 / 支撑位**，便于在列表中快速对照，而无需打开独立工具页。

## What Changes

- 在 Web 自选页表格中**新增一列**（可与「股票名称」列同样采用多行单元格样式）：主行展示**当日实时均价**；次行展示由均价按固定系数算出的**压力位**与**支撑位**（对齐工具页 `topLine` / `bottomLine` 语义）。
- **均价计算**与 `TestScripts/StockCalculateTools.html` 中行情回调逻辑一致：港股为成交额/成交量；科创板（`sh68*`）与北交所（`bj*`）为 `(turnover×10000)/volume`；其余 A 股为 `(turnover×10000)/(volume×100)`；成交量为 0 时回退为昨收（与工具页一致）。
- **压力位 / 支撑位**：常量 `K = 0.98848`；压力位 `avg / K`，支撑位 `avg × K`，数值保留三位小数（与工具页 `toFixed(3)` 一致）。
- 扩展 `POST /api/quotes/tencent` 的每条报价 JSON，使前端刷新逻辑能拿到 `avg` 及派生价位（或等价字段），避免在浏览器中重复实现腾讯字段口径与分支。

## Capabilities

### New Capabilities

- `watchlist-intraday-metrics`：定义自选列表展示「实时均价 + 压力/支撑」所需的数据口径、API 字段与 UI 行为。

### Modified Capabilities

- （无）现有 `openspec/specs/` 下无「自选列表」独立能力文档；本次仅新增能力规格。

## Impact

- **后端**：`stocks/stock_quote_tencent.py`（均价分支与工具页对齐）、`routes.py` 中 `api_quotes/tencent` 响应字段扩展；若有单测或脚本依赖响应形状，需一并更新。
- **前端**：`templates/watchlist.html`（表头、列字母、空状态 colspan、`refreshQuotesOnce` 与动态增行 DOM）；其它调用同一接口的页面若假设仅含 `now`/`prev_close`，需确认兼容性。
- **数据库**：无表结构变更。
