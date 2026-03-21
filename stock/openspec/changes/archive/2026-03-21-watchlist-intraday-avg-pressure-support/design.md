## Context

- 自选页 `templates/watchlist.html` 通过 `POST /api/quotes/tencent` 批量拉取行情，定时刷新现价与涨跌幅。
- 路由当前仅向下游返回 `code`、`name`、`now`、`prev_close`，而 `stocks/stock_quote_tencent.StockQuote` 已解析成交量、成交额并在 `_parse_one` 中计算了 `avg`，但未暴露给客户端。
- 用户指定的参考实现 `TestScripts/StockCalculateTools.html`：均价在 `fetchData` 内按代码前缀分支计算（约 1088–1092 行）；`calculateRow` 内以 `K=0.98848` 计算压力位 `avg/K`、支撑位 `avg*K`（约 968–972 行）。说明：文档中若引用「第 951 行」，该行实际为读取 `row.avg`；**真正的均价公式以行情拉取处分支为准**。

## Goals / Non-Goals

**Goals:**

- 自选表增加一列，展示**实时均价**及**压力/支撑**（同一列多行展示即可满足「新增 1 列」）。
- 均价与压力/支撑的数值口径与 `StockCalculateTools.html` 一致。
- 系数 `K` 在后端集中定义一处，API 同时返回均价与派生价位，前端只负责展示与格式化。

**Non-Goals:**

- 不在自选列表中绘制分时图或历史均线曲线。
- 不改变 `user_watchlist` 存储结构或同步协议。
- 不要求未登录场景下由服务端持久化均价（仍随每次行情刷新）。

## Decisions

1. **均价计算放在 `stock_quote_tencent._parse_one`（或同级辅助函数）**  
   - **理由**：与腾讯 `~` 字段解析同一位置维护，持仓/自选/其它调用 `fetch_quotes` 的路径自动一致。  
   - **变更**：将现有「非港股统一 `(turnover*10000)/(volume*100)`」改为与工具页一致的三段分支：`hk` / `sh68*` 与 `bj*` / 其余 A 股。

2. **压力/支撑在后端随每条 `StockQuote` 写入 API 响应**  
   - **理由**：避免在 `watchlist.html` 与 Python 各写一遍 `K` 与舍入规则。  
   - **字段建议**：在 `quotes[code]` 上增加 `avg`（number）、`pressure_line`（number）、`support_line`（number），均为三位小数语义；无有效均价时返回 `null` 或与工具页一致的占位展示约定（见规格）。

3. **UI：单列多行**  
   - **理由**：用户明确要求一列；与「股票名称」列的 `excel-multiline` + `excel-subtext` 模式一致，表格仍为一列。  
   - **结构示例**：第一行均价（主字号），第二行小字「压 xxx · 撑 xxx」或两行分别标注。

4. **兼容性**  
   - **理由**：其它消费者若只读 `now`/`prev_close`，新增字段为向后兼容。若存在严格 JSON Schema 校验，需在任务中列出并更新。

## Risks / Trade-offs

- **[Risk] 科创板/北交所均价分支调整后，依赖旧公式的隐含行为会变化** → **Mitigation**：与工具页对齐为产品要求；可在变更说明中注明；必要时对比单只股票手工验算。

- **[Risk] 成交量为 0 或字段异常时均价无效** → **Mitigation**：与工具页一致回退昨收；压力/支撑在无有效 `avg` 时显示 `-` 或 `0.00`（与规格一致）。

- **[Trade-off] API 载荷略增** → 每条仅多三个数值字段，可接受。

## Migration Plan

- 常规部署：先发布后端（新字段可选），再发布前端列展示；或同版本一并发布。无需数据迁移。

## Open Questions

- 是否需要在**持仓页**等同样调用 `/api/quotes/tencent` 的界面展示均价（本变更以自选列表为范围，默认不做，除非任务外扩）。
