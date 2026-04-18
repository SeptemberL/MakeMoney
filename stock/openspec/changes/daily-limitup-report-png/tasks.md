## 1. 输入与输出约定

- [x] 1.1 明确读取输入 JSON 路径规则（默认 `outputs/daily_limitup_report/<date>/report.json`）并实现解析与字段兜底
- [x] 1.2 定义 PNG 输出目录与文件命名规则（例如 `outputs/daily_limitup_report_png/<date>/page_1.png`）并支持覆盖重跑

## 2. PNG 渲染实现（Pillow）

- [x] 2.1 增加 PNG 渲染模块：加载字体（含中文回退）、定义画布尺寸、标题/表头/行渲染函数
- [x] 2.2 实现分页渲染：按每页行数拆分 rows，输出 `page_N.png`
- [x] 2.3 实现缺失字段占位与状态提示（`partial` 行显示 `--`/灰色或附加 reason）

## 3. 任务入口与联动

- [x] 3.1 提供命令/任务入口（例如 `run_daily_limitup_report_png(trade_date=None)`），支持指定日期与默认最近日期
- [x] 3.2 （可选）接入调度：在 17:05 涨停复盘后追加 PNG 生成任务，或新增独立定时任务

## 4. 验证

- [x] 4.1 用现有 `report.json` 样例生成 PNG，人工核对字段与排版
- [x] 4.2 增加最小自动化验证：文件存在、页数正确、非空图片尺寸符合预期

