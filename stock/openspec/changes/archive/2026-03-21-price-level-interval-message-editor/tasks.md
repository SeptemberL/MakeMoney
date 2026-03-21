## 1. 前端展示与交互

- [x] 1.1 调整 `signal_notify.html`：`price_level_interval` 选中时显示主消息模板 textarea（勿与 fib 一并隐藏），保存/编辑回显 `message_template`
- [x] 1.2 调整 `watchlist.html` 信号弹窗：同上，保证 POST/PUT 的 `message_template` 与表单一致

## 2. 校验与文档

- [x] 2.1 核对 `routes.py` 创建/更新接口在价位间隔下是否始终接收并持久化 `message_template`；若有缺口则修补
- [x] 2.2 更新 `Docs/信号通知系统.md`：说明价位间隔在 UI 中可编辑模板及常用变量
