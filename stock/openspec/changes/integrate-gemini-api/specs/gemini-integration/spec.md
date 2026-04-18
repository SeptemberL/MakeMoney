# gemini-integration（变更草案）

本规格描述「在本股票系统中接入 Gemini API」所需的最小可验证行为，供实现与回归对照。

## ADDED Requirements

### Requirement: 系统 MUST 通过集中封装调用 Gemini

系统 MUST 提供单一模块（或包）作为调用 Gemini 的唯一入口；业务代码 MUST NOT 在各处直接散落初始化 SDK 与裸 HTTP 调用（测试替身除外）。

#### Scenario: 业务代码通过封装发起一次生成请求

- **WHEN** 任意服务端代码需要调用 Gemini 生成文本
- **THEN** 系统 MUST 通过该集中封装发起调用并获取模型文本结果或受控错误类型

### Requirement: 系统 MUST 从安全来源读取 API 密钥且不得泄露

系统 MUST 从环境变量或经项目约定的服务端配置中读取 Gemini API 密钥；密钥 MUST NOT 写入前端资源、MUST NOT 进入版本库、MUST NOT 在日志中以明文完整输出。

#### Scenario: 未配置密钥时拒绝调用

- **WHEN** 运行环境中未提供有效 API 密钥
- **THEN** 系统 MUST 在调用前失败并返回明确错误（不得向 Google 端点发送空密钥请求）

#### Scenario: 日志脱敏

- **WHEN** 记录与 Gemini 调用相关的诊断日志
- **THEN** 日志 MUST NOT 包含完整 API 密钥或等价可还原密钥的字段

### Requirement: 系统 MUST 支持可配置的模型标识与请求超时

系统 MUST 允许配置默认模型标识（例如模型名称字符串）与请求超时时间；配置缺失时 MUST 使用文档化的默认值。

#### Scenario: 使用配置的模型与超时

- **WHEN** 管理员在配置中指定模型名与超时秒数
- **THEN** 系统 MUST 使用该模型标识与超时阈值向 Gemini 发起请求

### Requirement: 系统 MUST 对超时与可重试错误进行一致处理

系统 MUST 为调用设置超时；对判定为瞬时网络故障或服务端 5xx 类错误，MUST 采用有限次数的重试策略；对鉴权失败与客户端 4xx 错误，MUST NOT 无意义重试。

#### Scenario: 请求超时

- **WHEN** 调用在配置的超时时间内未完成
- **THEN** 系统 MUST 中止该次请求并向上层返回超时错误

#### Scenario: 可重试错误

- **WHEN** 调用遇到被归类为可重试的错误
- **THEN** 系统 MUST 在不超过既定重试次数的前提下进行退避重试

### Requirement: 系统 MUST 声明并实现 Python 依赖

系统 MUST 在 `requirements.txt`（或项目等价的依赖清单）中声明 Gemini 集成所需的官方或受支持的客户端库，并与现有 Flask 应用兼容安装。

#### Scenario: 依赖安装

- **WHEN** 在新环境中按项目依赖清单安装
- **THEN** 环境 MUST 能成功导入 Gemini 封装所依赖的库并完成一次最小调用路径的导入检查（不要求有网单测默认命中真实 API）
