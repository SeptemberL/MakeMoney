## Why

当前股票系统以行情抓取、自选股、信号与定时任务为主，缺少统一的生成式 AI 能力；你希望接入 Google Gemini API，以便后续把持仓、复盘、舆情、策略解释等分析需求逐步交给模型辅助完成。现在建立可复用的客户端与配置边界，能降低后续各功能零散直连 API 的成本与安全风险。

## What Changes

- 增加对 **Google Gemini（Generative Language / Google AI）HTTP API** 的官方或推荐 SDK 集成路径，封装为可注入的业务模块（而非在路由里散落 `requests` 调用）。
- 增加 **密钥与模型名等配置** 的加载方式（环境变量或现有 `config`/YAML 约定之一），并明确**不得**把密钥写入仓库或前端。
- 定义 **超时、重试、错误分类与日志** 的最小行为，便于后续异步任务或 Web 端调用时一致处理。
- （可选占位）为后续「分析类」功能预留 **服务端调用入口**（例如内部 service 或受控 API），本变更以**基础设施就绪**为主，不要求一次性上线具体业务分析页面。

## Capabilities

### New Capabilities

- `gemini-integration`: 覆盖 Gemini API 客户端封装、配置与密钥管理约定、调用与错误处理语义，以及后续功能复用该集成时应满足的安全与可观测性要求。

### Modified Capabilities

- （无）本变更为新增能力，不修改既有 `openspec/specs/` 中已发布能力的对外需求语义。

## Impact

- **依赖**：`requirements.txt` 预计新增 Google 官方 Python SDK（如 `google-genai`）或等价 HTTP 客户端依赖；需与现有 Flask 3.x、Python 版本兼容。
- **代码**：新增独立模块（例如 `Managers/` 或 `services/` 下的 Gemini 封装）、`config`/`Config` 或环境变量读取；`routes.py` 仅在确需对外暴露调试/管理接口时最小改动。
- **运维**：部署环境需能访问 Google API 端点；需在密钥管理（环境变量、密钥文件权限）上对齐现有项目习惯。
- **安全**：API Key 仅服务端持有；日志中禁止完整打印密钥与用户敏感 payload。
