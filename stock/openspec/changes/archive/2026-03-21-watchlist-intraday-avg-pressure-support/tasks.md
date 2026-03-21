## 1. 行情解析与常量

- [x] 1.1 在 `stocks/stock_quote_tencent.py` 中将 `_parse_one` 的均价计算改为与 `StockCalculateTools.html` `fetchData` 一致的三段分支（`hk` / `sh68*`+`bj*` / 其余 A 股），成交量为 0 时回退昨收
- [x] 1.2 在同一模块集中定义 `K = 0.98848`，并为单条报价计算 `pressure_line`（`avg/K`）与 `support_line`（`avg*K`），仅在 `avg>0` 时有效，否则为 `None`（或等价表示），三位小数语义与 `StockQuote` 字段一并落地（扩展 dataclass 或在序列化处计算，择一并保持单一来源）

## 2. API

- [x] 2.1 扩展 `routes.py` 中 `api_quotes/tencent` 的 `out[k]` 字典，包含 `avg`、`pressure_line`、`support_line`（`null` 兼容 JSON），命名与 `specs/watchlist-intraday-metrics/spec.md` 最终锁定一致
- [x] 2.2 检索仓库内其它对 `/api/quotes/tencent` 响应结构的依赖（若有测试或第二处前端），必要时更新

## 3. 自选页 UI

- [x] 3.1 在 `templates/watchlist.html` 表头增加一列（含列字母行与标题），单元格样式与现有 `excel-multiline` / `excel-subtext` 协调
- [x] 3.2 在 `refreshQuotesOnce` 中根据返回的 `avg`、`pressure_line`、`support_line` 更新每行 DOM；无效时显示 `-`
- [x] 3.3 修正客户端动态插入/重建表行处（如添加自选、合并持仓）的 HTML 片段：`colspan` 与新增列节点与静态模板一致

## 4. 验证

- [x] 4.1 手工打开自选页：确认定时刷新下列中均价与压/撑变化合理，并与 `StockCalculateTools.html` 同代码对照一致（至少抽测 A 股、港股、`sh68`、`bj` 各一例若环境允许）
- [x] 4.2 若有针对 `fetch_quotes` 或该 API 的自动化测试，补充对新字段或新分支的断言
