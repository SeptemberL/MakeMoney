## ADDED Requirements

### Requirement: 腾讯批量行情接口暴露均价与压力/支撑

`POST /api/quotes/tencent` 在 `success: true` 且返回 `quotes` 时，对每一条成功解析的报价对象 SHALL 包含除现有字段外的下列数值字段（或与之下列语义等价的命名，实现阶段在 `tasks.md` 中锁定唯一命名并在全仓调用处一致）：

- `avg`：当日实时均价，计算规则 MUST 与 `TestScripts/StockCalculateTools.html` 中 `fetchData` 对 `newAvg` 的分支一致（港股：`turnover/volume`；代码以 `sh68` 开头或 `bj` 开头：`(turnover×10000)/volume`；其它 A 股：`(turnover×10000)/(volume×100)`；当 `volume≤0` 时 MUST 使用昨收价作为回退，与工具页中 `parseFloat(d[4])` 回退语义一致）。
- `pressure_line`：压力位，当 `avg>0` 时为 `avg / K`，否则为无效；`K` MUST 等于 `0.98848`。
- `support_line`：支撑位，当 `avg>0` 时为 `avg × K`，否则为无效。

`pressure_line` 与 `support_line` 在有效时应为保留三位小数的数值（与工具页 `toFixed(3)` 一致）；无效时 MUST 以 `null` 表示（禁止用 `0` 冒充有效价位）。

#### Scenario: 有成交量的 A 股返回三项

- **WHEN** 某只股票解析得到正的 `volume` 与 `turnover`，且代码不属于港股或 `sh68*`/`bj*` 特殊分支
- **THEN** 响应中该股票的 `avg` MUST 按 `(turnover×10000)/(volume×100)` 计算，`pressure_line` 与 `support_line` MUST 由该 `avg` 与 `K` 导出且为三位小数精度

#### Scenario: 无成交量时回退昨收且不输出有效压力/支撑

- **WHEN** `volume≤0` 导致均价回退为昨收，且业务上视为无效均价（与工具页在 `avg>0` 才计算 `topLine`/`bottomLine` 的行为一致）
- **THEN** `avg` MAY 为回退后的数值，但若实现认定 `avg` 无效则 `pressure_line` 与 `support_line` MUST 为 `null`

### Requirement: 自选列表表格展示单列均价与压力/支撑

自选列表页面（`templates/watchlist.html`）SHALL 在表格中增加一列，用于展示每只自选股票的当日实时均价；同一单元格内 SHALL 以次要样式展示压力位与支撑位标签及数值（例如「压」「撑」或与表意等价的中文标签），刷新频率与现价列一致（沿用现有定时 `refreshQuotesOnce` 行为）。

#### Scenario: 刷新后更新均价与压力/支撑

- **WHEN** 客户端成功收到带 `avg`、`pressure_line`、`support_line` 的行情响应
- **THEN** 对应行的该列 MUST 显示格式化后的均价；当 `pressure_line`/`support_line` 非 `null` 时 MUST 显示对应价位，否则 MUST 显示与现价列 `-` 一致的缺省占位

#### Scenario: 表头与空表 colspan

- **WHEN** 页面渲染表头与「暂无自选」占位行
- **THEN** 表头 MUST 为新列提供列标题（含义为分时/当日均价及压力支撑）；列字母行 MUST 增加一列；空数据行的 `colspan` MUST 与总列数一致

### Requirement: 动态增删行 DOM 与自选行结构一致

凡在客户端向 `#watchlist-table` 追加或重建自选行的脚本路径，SHALL 为新列生成与静态模板等价的单元格结构（含用于 JS 更新的选择器类名），以便 `refreshQuotesOnce` 能更新新增行。

#### Scenario: 添加自选后出现新列内容

- **WHEN** 用户通过页面逻辑新增一行自选
- **THEN** 该行 MUST 包含均价/压力/支撑列的占位节点，且在首次行情刷新成功后显示有效数据或 `-`
