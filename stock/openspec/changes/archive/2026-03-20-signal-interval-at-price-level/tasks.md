## 1. 数据模型与校验

- [x] 1.1 审阅现有 `signal_rule` / `signal_rule_state` 与 `signal_type` 存储方式，确认新增枚举值是否需要迁移或扩列（MySQL + SQLite 同步）
- [x] 1.2 实现保存 API 校验：`target_price`、`mode`、`send_interval_seconds`（正整数 + 最小间隔常量）
- [x] 1.3 定义并持久化运行态字段（如 `last_sent_at`、可选 `last_price`），加载/回写与现有状态机一致

## 2. 信号核心逻辑

- [x] 2.1 在 `SingleType` 中新增价位间隔类型，并实现对应 `SingleBase` 子类：`trigger`/`update` 中实现条件判定与间隔节流
- [x] 2.2 扩展 `SignalMessageTemplate` 默认占位符（如 `target_price`、`mode`）与文档示例
- [x] 2.3 在 `create_signal_instance` 中注册新类型；`get_floating_editor_schema` 增加字段与 enum 选项

## 3. 集成与文档

- [x] 3.1 更新 `routes.py`（及任何 DTO）序列化/反序列化以支持新类型与参数
- [x] 3.2 更新 `Docs/信号通知系统.md`（或等价文档）说明行为、限制与最小间隔
- [x] 3.3 补充手工或自动化测试：条件真/假、间隔边界、持久化恢复、非法参数拒绝
