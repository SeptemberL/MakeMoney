# 定时任务管理（scheduled-tasks-management）

本文档由变更 `scheduled-tasks-management-page` 合并入主规格库。

## ADDED Requirements

### Requirement: 导航入口位置

系统 MUST 在 Web 主导航中于「信号通知」菜单项**之后**提供「定时任务」链接；若存在 DSA 嵌入侧栏（`dsaweb.html`），MUST 在「信号通知」对应 tab **之后**增加等价入口，指向同一页面路径。

#### Scenario: 主导航顺序

- **WHEN** 用户打开包含侧栏导航的主布局页面
- **THEN** 「定时任务」MUST 出现在「信号通知」与后续菜单项之间的约定位置（紧接信号通知之后）

### Requirement: 任务列表展示

定时任务页面 MUST 列出当前进程从 `configs/tasks_config.yaml` 加载并由 `TaskManager` 管理的全部任务条目。每条 MUST 至少展示：任务 ID、名称、模块与函数名、触发器类型（cron / interval / date）、用于触发的参数摘要、`enabled` 配置状态，以及调度器中的运行态（例如已暂停、下次执行时间，若 APScheduler 可提供）。

#### Scenario: 空配置

- **WHEN** 配置文件中无任何任务或全部未启用且未注册到调度器
- **THEN** 页面 MUST 显示明确空状态或提示，且不得抛出未处理错误

### Requirement: 开启与关闭

用户 MUST 能够对已注册到 APScheduler 的任务执行开启（恢复调度）与关闭（暂停调度）操作，且操作结果 MUST 通过后端调用 `TaskManager` 的暂停/恢复能力与调度器状态一致。若任务因 `enabled: false` 从未被加载，页面 MUST 区分说明，且不得将「暂停」与「未加载」混为一谈。

#### Scenario: 暂停已运行任务

- **WHEN** 用户对当前正在调度的任务发起「关闭」或「暂停」
- **THEN** 该任务 MUST 不再按触发器执行，直至用户执行「开启」或「恢复」

### Requirement: 编辑与持久化

用户 MUST 能够编辑至少以下字段并保存：`task_name`、`trigger_type`、`trigger_args`、`enabled`、`module_path`、`function_name`、`description`，以及现有 `TaskConfig` 支持的 `max_instances`、`misfire_grace_time`、`coalesce`（以表单或 JSON 子字段呈现）。保存 MUST 将变更写入项目使用的 `tasks_config.yaml`（或项目约定的同一配置文件路径），并 MUST 使运行中调度器与该配置一致（通过移除并重新添加任务或等效热更新），无需用户手动重启进程。

#### Scenario: 保存后触发器生效

- **WHEN** 用户将某任务从 cron 改为 interval 并成功保存
- **THEN** 该任务 MUST 按新的 interval 规则被调度，且 YAML 文件中 MUST 反映新触发器定义

### Requirement: HTTP API

系统 MUST 提供 JSON API 供上述页面获取任务列表、执行暂停/恢复与提交编辑；响应 MUST 在失败时包含可读的 `success`/`message` 或等价结构，与项目现有 API 风格保持一致。

#### Scenario: 无效模块路径

- **WHEN** 用户提交无法导入的 `module_path` 或不存在函数名
- **THEN** API MUST 返回错误且不破坏其余已存在任务的调度状态（或明确文档化的回滚行为）
