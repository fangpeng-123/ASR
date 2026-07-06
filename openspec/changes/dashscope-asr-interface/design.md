## Context

`F:\code\TTS` 已经提供了一套基于 DashScope 的文本转语音代理服务，采用 FastAPI + 服务层 + 路由层 + CLI 的分层结构。本变更在 `F:\code\Agent\ASR` 新建一个对称的自动语音识别（ASR）服务，复用相同的工程结构和设计模式，但输入/输出方向与 TTS 相反：接收音频，返回文本。

DashScope ASR SDK 提供两类入口：

- `dashscope.audio.asr.Recognition`：支持同步文件识别（`call(file=...)`）和实时流式识别（`start()` / `send_audio_frame(bytes)` / `stop()`），并通过 `RecognitionCallback` 回调返回结果。
- `dashscope.audio.asr.Transcription`：仅支持公网可访问的音频 URL 列表，不适合“本地上传”场景。

因此，本地上传识别与实时流式识别均统一走 `Recognition`。

## Goals / Non-Goals

**Goals：**

- 提供 HTTP 接口 `POST /api/v1/asr`，支持本地音频文件上传并返回完整转写结果。
- 提供 WebSocket 接口 `/api/v1/asr/ws`，支持客户端推送音频流并实时返回识别文本增量。
- 提供 CLI 客户端，覆盖文件识别与实时流式识别两种验证方式。
- 项目结构、配置加载方式、错误处理风格与 `F:\code\TTS` 保持一致。

**Non-Goals：**

- 默认开启说话人分离（diarization），仅作为可选参数暴露。
- 提供音频转写结果的长期存储或任务查询（走同步/实时模式即可）。
- 复刻 TTS 的 SSE 流式输出；ASR 的流式场景通过 WebSocket 双向通信实现。

## Decisions

### 1. 文件上传识别使用 `Recognition.call(file=...)`，而非 `Transcription`

- **原因**：`Transcription` 只接受公网 URL 列表，若要支持本地上传还需额外文件托管服务。`Recognition.call(file="本地路径")` 可直接传入本地文件路径，更贴合需求。
- **权衡**：`Recognition.call` 是同步阻塞调用，大文件识别时会占用请求线程；但文件上传场景通常可接受秒级延迟，且实现简单。

### 2. 实时识别使用 WebSocket，服务端对音频帧进行二次切片

- **原因**：DashScope `Recognition` 实时模式通过 `send_audio_frame(bytes)` 推送音频，SDK 内部以 WebSocket 与云端通信。为了让客户端不必关心精确的 20ms/40ms 切片，服务端收到任意大小的二进制音频帧后，按固定字节长度（`sample_rate × 2 × 0.02`，即 20ms 16bit mono）切分再调用 `send_audio_frame`。
- **权衡**：增加服务端一次内存拷贝，但显著降低客户端集成难度。

### 3. 项目结构镜像 TTS

- **原因**：降低维护成本，方便后续统一演进（例如统一的配置中心、日志、健康检查）。
- **结构**：
  ```
  ASR/
  ├── api/
  │   ├── main.py              # FastAPI 应用工厂
  │   ├── config.py            # AppConfig / load_config / get_api_key
  │   ├── models.py            # Pydantic 请求/响应模型
  │   ├── service.py           # 非流式识别服务封装
  │   ├── realtime_recognizer.py  # 实时识别器 + SDK 回调桥接
  │   ├── routes/
  │   │   ├── health.py
  │   │   └── asr.py           # POST /asr + WS /asr/ws
  │   └── middleware.py
  ├── cli/
  │   └── asr.py               # 命令行客户端
  └── tests/
  ```

### 4. 上传文件先落盘到临时目录，识别完成后清理

- **原因**：`Recognition.call(file=...)` 需要本地文件路径，`UploadFile` 对象必须落盘。
- **实现**：使用 `tempfile.NamedTemporaryFile` 或 `tempfile.mkstemp`，在请求结束时删除。

### 5. 实时识别回调通过 `asyncio.Queue` 桥接到主事件循环

- **原因**：DashScope SDK 回调在内部线程触发，而 FastAPI/WebSocket 运行在 asyncio 事件循环中。使用 `loop.call_soon_threadsafe(queue.put_nowait, ...)` 将回调结果安全地桥接到协程。
- **参考模式**：与 `F:\code\TTS\api\realtime_synthesizer.py` 中的 `_Callback` 桥接模式一致。

## Risks / Trade-offs

- **[Risk] SDK 回调线程与 asyncio 事件循环耦合** → **Mitigation**：所有回调只负责把数据/异常放入 `asyncio.Queue`，实际处理逻辑全部放在协程中。
- **[Risk] 实时识别对音频格式/采样率敏感** → **Mitigation**：API 与 CLI 强制要求客户端指定 `format` 与 `sample_rate`，并在 `start` 帧校验支持的组合。
- **[Risk] 临时文件未及时清理导致磁盘增长** → **Mitigation**：使用 `try/finally` 或上下文管理器确保识别完成后删除。
- **[Risk] 大文件同步识别阻塞工作线程** → **Mitigation**：后续如需支持长音频，可迁移到 `Transcription` + 文件托管方案；当前 MVP 先保持简单。
