# Gemini 接入（服务端）

## 1. 目标

本项目通过 `Managers/gemini_client.py` 统一封装 Gemini 调用能力，供后续「分析/解读」类功能复用。

## 2. 配置

### API Key（推荐）

仅在**服务端**设置环境变量（不要提交到仓库、不要下发到前端）：

- `GEMINI_API_KEY`（优先）
- `GOOGLE_API_KEY`

### config.ini（仅建议本地开发）

可以在 `config.ini` 增加：

```ini
[GEMINI]
api_key =
model = gemini-1.5-flash
timeout_seconds = 60
```

建议直接参考仓库中的 `config.ini.example`，并自行创建本机 `config.ini`。

## 3. 冒烟验证（可选）

`Managers/gemini_client.py` 提供一个**默认不执行**的本地冒烟入口：只有当设置了 `GEMINI_SMOKE_PROMPT` 时才会发起真实请求。

示例：

```bash
export GEMINI_API_KEY="***"
export GEMINI_SMOKE_PROMPT="用三句话解释什么是均线金叉"
python -m Managers.gemini_client
```

> 注意：冒烟需要运行环境可以访问 Google API 端点。

