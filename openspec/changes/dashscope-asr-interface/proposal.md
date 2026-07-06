## Why

`F:\code\TTS` 已经提供了一个基于 DashScope 的文本转语音代理服务，但语音交互链路还缺少反向能力：将本地语音转成文本。为了形成完整的语音输入/输出闭环，需要建设一个与 TTS 对称的 ASR（自动语音识别）服务，支持本地音频文件上传识别和实时流式识别，并提供 CLI 与 HTTP/WebSocket 两种验证方式。

## What Changes

- 在 `F:\code\Agent\ASR` 新建独立项目，结构镜像 `F:\code\TTS`：
  - `api/`：FastAPI 应用、配置、Pydantic 模型、服务层、路由、实时识别器封装
  - `cli/`：命令行客户端，支持文件识别与实时流式识别两种模式
  - `tests/`：单元测试与集成测试
  - `config.yaml` / `requirements.txt` / `pytest.ini`
- 新增 HTTP 接口 `POST /api/v1/asr`：接收本地音频文件上传，返回完整识别文本与句子列表
- 新增 WebSocket 接口 `/api/v1/asr/ws`：客户端发送音频流，服务端实时返回 `partial` / `sentence` / `done` 等文本增量
- 新增 CLI：`python -m cli.asr --file <audio>` 与 `python -m cli.asr --stream --file <audio>`
- 统一使用 DashScope `dashscope.audio.asr.Recognition` 作为底层 SDK，同时覆盖同步文件识别与实时流式识别

## Capabilities

### New Capabilities

- `asr-file-upload`：本地音频文件上传后返回完整转写结果
- `asr-realtime-ws`：WebSocket 实时音频流识别，返回增量文本与句子结束事件
- `asr-cli`：命令行工具，支持文件识别与实时流式两种验证方式

### Modified Capabilities

- 无

## Impact

- 新增独立项目 `F:\code\Agent\ASR`，不影响现有 `task_agent` / `TTS` 项目
- 新增 Python 依赖：`fastapi`、`uvicorn`、`pydantic`、`pyyaml`、`python-dotenv`、`httpx`、`httpx-ws`、`dashscope`
- 需要配置 DashScope API Key（环境变量或 `.env`）
