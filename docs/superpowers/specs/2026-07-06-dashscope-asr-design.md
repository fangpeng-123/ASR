# DashScope ASR 服务设计

- 日期：2026-07-06
- 状态：待评审
- 位置：`C:\work\PythonProgram\Agent\ASR`
- 来源：基于 `openspec/changes/dashscope-asr-interface/` 的 proposal / design / specs / tasks 整合而成，作为实现的单一权威 spec。openspec 中的旧路径 `F:\code\...` 一律以实际路径 `C:\work\PythonProgram\Agent\ASR` 为准。

## 1. 概述

新建一个对称于 `TTS` 项目的 DashScope ASR（自动语音识别）服务：输入音频，输出文本。提供三种验证入口：

- HTTP `POST /api/v1/asr`：本地音频文件上传，返回完整转写结果。
- WebSocket `/api/v1/asr/ws`：客户端推音频流，服务端实时返回增量文本。
- CLI：覆盖文件识别与实时流式识别（文件 / 麦克风）。

底层统一使用 `dashscope.audio.asr.Recognition`，覆盖同步文件识别与实时流式识别；不使用 `Transcription`（仅接受公网 URL，不适合本地上传）。

### 1.1 范围

- 文件上传识别（含句子级时间戳与句尾标记）。
- WebSocket 实时流式识别（partial / sentence / done 增量）。
- CLI 文件模式、流式文件模式、流式麦克风模式（懒加载）。
- mock SDK 的 pytest 单元/集成测试 + 真实端到端手动验证。

### 1.2 非目标

- 默认关闭说话人分离（diarization）；作为可选参数 `enable_diarization`（默认 `false`）在 HTTP 与 WS 两接口暴露，由客户端按需开启；开启后 `sentences` / `sentence` 帧携带 `speaker` 字段。
- 转写结果的长期存储或异步任务查询。
- 复刻 TTS 的 SSE 流式输出；ASR 流式走 WebSocket 双向通信。

## 2. 目录结构与组件职责

```
ASR/
├── api/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 应用工厂 + 路由注册 + 异常处理
│   ├── config.py               # AppConfig / load_config / 读 DASHSCOPE_API_KEY
│   ├── models.py               # Pydantic 请求/响应模型
│   ├── service.py              # 非流式 recognize_file()
│   ├── realtime_recognizer.py  # RealtimeRecognizer + _Callback 桥接
│   ├── middleware.py           # 统一异常 → JSON 错误
│   └── routes/
│       ├── __init__.py
│       ├── health.py           # GET /health
│       └── asr.py              # POST /api/v1/asr + WS /api/v1/asr/ws
├── cli/
│   └── asr.py                  # CLI（file / stream / microphone 懒加载）
├── tests/
│   ├── conftest.py             # fixtures：mock SDK、TestClient
│   ├── test_service.py
│   ├── test_asr_route.py
│   ├── test_realtime.py
│   └── test_cli.py
├── docs/superpowers/specs/2026-07-06-dashscope-asr-design.md
├── config.yaml
├── requirements.txt
└── pytest.ini
```

**组件职责（单一职责、可独立测试）：**

- `config.py` — 加载 `config.yaml`；从系统环境变量 `DASHSCOPE_API_KEY` 读取密钥；暴露 `AppConfig`（服务器 host/port、默认 model、支持的 format/sample_rate 白名单、支持的 `model↔sample_rate` 组合表、帧切片 `frame_ms`）。无 SDK 依赖。
- `models.py` — 纯 Pydantic 模型（见第 4 节）。无 SDK 依赖。
- `service.py` — `recognize_file(path, model, format, sample_rate) -> ASRUploadResponse`；封装 `Recognition.call(file=path, ...)`，把 `RecognitionResult` 解析为 `text`/`sentences`/`duration_ms`。解析逻辑独立，便于 mock 测试。
- `realtime_recognizer.py` — `RealtimeRecognizer`：`start()` / `send_audio_chunk(bytes)` / `stop()` / `cancel()` 生命周期；`_Callback` 把 SDK 回调线程的结果经 `loop.call_soon_threadsafe(queue.put_nowait, ...)` 推入 `asyncio.Queue`；暴露 `async results()` 供路由协程消费。内部负责 20ms 样本对齐切片（见第 3.3 节）。
- `routes/health.py` — `GET /health` → `{"status":"ok"}`。
- `routes/asr.py` — HTTP 上传路由 + WS 状态机路由（见第 3 节）。
- `cli/asr.py` — argparse 参数；文件模式调 `POST /api/v1/asr`；流式模式调 WS；`--microphone` 懒加载 `sounddevice`，未安装则按 spec 给出明确提示。

## 3. 数据流

### 3.1 HTTP 文件上传（`POST /api/v1/asr`）

```
客户端 multipart(file + model/format/sample_rate + 可选 enable_diarization)
  → 路由校验 (model, format, sample_rate) 是否在支持组合表内
  → UploadFile 落盘 tempfile
  → service.recognize_file(tempfile, model, format, sample_rate, enable_diarization)
  → Recognition.call(file=tempfile, model=..., format=..., sample_rate=...)  # enable_diarization 透传给 SDK，参数名 step 0 确认
  → 解析 RecognitionResult → ASRUploadResponse（diarization 开启时 sentences 带 speaker）
  → finally 删除 tempfile
  → 200 JSON
```

- 缺 `file` 字段 → 422。
- `(model, format, sample_rate)` 不在支持组合表 → 400（明确 message）。
- SDK 异常 → 500（对客户端只回通用信息，日志记详情）。

### 3.2 WebSocket 实时流式（`/api/v1/asr/ws`）

状态机：

1. **连接建立** → 等待客户端 `start` 控制帧。
2. **`start`**（JSON：`action=start` + `model` + `format` + `sample_rate`）→ 路由校验组合表 → `RealtimeRecognizer.start(...)` → 回 `{"type":"ready"}`。
   - 缺 `format`/`sample_rate` 或组合不支持 → 回 `{"type":"error","code":"invalid_start","message":"..."}` 并关闭连接。
3. **二进制音频帧** → 路由 `send_audio_chunk(bytes)` → 识别器切 20ms → `send_audio_frame` → SDK 回调 → Queue → 路由协程消费 → 发 `partial` / `sentence`。
   - 未 `start` 先发音频 → 回 `{"type":"error","code":"not_started","message":"..."}` 并关闭。
4. **`finish`**（JSON：`action=finish`）→ `RealtimeRecognizer.stop()` 冲刷残余 → 等最终句子 → 发 `{"type":"done","duration_ms":...}` → 关闭。
5. **`cancel`**（JSON：`action=cancel`）→ `RealtimeRecognizer.cancel()` → 发 `{"type":"error","code":"cancelled","message":"..."}` → 关闭。
6. SDK 回调抛异常 → 作为 error 入队 → 路由发 `{"type":"error","code":"internal","message":"..."}` → 关闭。

控制帧为 JSON 文本帧；音频为二进制帧。结果帧统一为 `WSResultMessage`（见第 4 节）。

### 3.3 音频切片安全守则（`realtime_recognizer` 契约）

流式 ASR 把音频视为连续 PCM 字节流，20ms 只是传输分包单位，不是识别单位；服务端重组字节流后识别，分包边界不影响准确率。但切片**错**了会损坏音频，必须守住以下 4 条：

1. **样本对齐**：16bit mono 一个样本 = 2 字节，切片必须落在**偶数字节**边界。20ms 帧字节长度 = `sample_rate × 2 × (frame_ms/1000)`（16k/20ms → 640 字节，天然偶数）；残留尾部不足一帧时也按偶数字节处理。
2. **大小按声明的 sample_rate 计算**：帧字节长度从 `start` 帧的 `sample_rate` 与 `config.frame_ms` 推导，不写死常量。
3. **WAV 头处理**：流式通道默认要求**裸 PCM**，`start` 帧用 `format=pcm`。若源是 WAV 文件，CLI 侧剥去 RIFF 头后只发裸 PCM 数据段；服务端不得把 WAV 头字节当音频送入 `send_audio_frame`。流式是否支持 `format=wav`/`mp3` 由 step 0 确认，未确认前流式仅支持 `pcm`。文件上传走 `Recognition.call(file=路径)`，pcm/wav/mp3 均由 SDK 按文件路径处理，不受此约束。
4. **顺序与完整性**：不丢字节、不重复、不乱序。

**可选简化（待 step 0 确认）**：若 SDK `send_audio_frame` 接受任意大小帧，则直接透传客户端块、不做 20ms 重切；若有帧大小上限，则仅超过上限时按样本对齐切分。两条路对准确率等价。默认实现 20ms 重切（与 openspec 场景一致）。

## 4. 数据模型（`models.py`）

```python
class ASRSentence(BaseModel):
    text: str
    begin_time: int          # 毫秒
    end_time: int            # 毫秒
    is_final: bool
    speaker: Optional[str] = None   # 仅 enable_diarization=true 时填充

class ASRUploadResponse(BaseModel):
    text: str
    sentences: list[ASRSentence]
    duration_ms: int

class WSControlMessage(BaseModel):
    action: Literal["start", "finish", "cancel"]
    model: Optional[str] = None
    format: Optional[str] = None
    sample_rate: Optional[int] = None
    enable_diarization: Optional[bool] = False

class WSResultMessage(BaseModel):
    type: Literal["ready", "partial", "sentence", "done", "error"]
    text: Optional[str] = None
    begin_time: Optional[int] = None
    end_time: Optional[int] = None
    duration_ms: Optional[int] = None
    speaker: Optional[str] = None    # 仅 type=sentence 且 enable_diarization=true
    code: Optional[str] = None       # 仅 type=error
    message: Optional[str] = None
```

WS error `code` 取值：`invalid_start` / `not_started` / `cancelled` / `internal`。

## 5. 配置（`config.yaml`）

```yaml
server:
  host: 0.0.0.0
  port: 8000
dashscope:
  # api_key 来自系统环境变量 DASHSCOPE_API_KEY，不写入文件
  default_model: paraformer-realtime-v2   # 见 §8 step 0 确认
asr:
  formats: [pcm, wav, mp3]
  sample_rates: [8000, 16000, 24000, 44100, 48000]
  supported_combinations:                 # (model, sample_rate)；见 §8 step 0 确认
    - [paraformer-realtime-v2, 16000]
    - [paraformer-realtime-8k-v2, 8000]
  frame_ms: 20
```

> 注：openspec spec 的示例用了 `paraformer-realtime-8k-v2` + `sample_rate 16000`，这与"8k 模型对应 8k 采样率"的命名直觉不符。确切的 model ID 与 `model↔sample_rate` 兼容矩阵在实现 step 0 依据 DashScope 文档/SDK 确认后写入 `supported_combinations`；服务端按此表校验，不在表内的组合返回 400。step 0 是写测试的前置条件。

## 6. 错误处理

- **HTTP**：422（缺 `file`）、400（不支持的 model / format / sample_rate / 组合，message 明确）、500（SDK 异常，对外通用信息 + 日志详情）。
- **WS**：所有错误统一为 `WSResultMessage(type="error", code, message)` 后关闭连接（见 3.2 错误码）。
- **临时文件**：`try/finally` 必删，避免磁盘增长。
- **SDK 回调异常**：`_Callback` 内捕获，作为 error 入队，由路由协程以 `error:internal` 帧抛出。
- **CLI**：参数缺失/冲突 → 打印用法、非零退出；连不上 `http://localhost:8000` → 提示 `请先启动 ASR 服务: python -m api.main`。

## 7. 测试策略（每切片 TDD，mock SDK）

每个切片先按对应 capability spec 写测试（mock `Recognition` / `RealtimeRecognizer`），再实现到绿：

- `test_service.py`（切片1）— mock `Recognition.call`：单句/多句解析、`is_final` 标记、`duration_ms`、异常传播。
- `test_asr_route.py`（切片1）— `TestClient`：有效上传 200、缺 `file` 422、不支持 format 400、不支持 model/组合 400、tempfile 清理。
- `test_realtime.py`（切片2）— mock `RealtimeRecognizer`：`start`→`ready`、`partial`/`sentence` 下发、`finish`→`done`、`cancel`→`error:cancelled`、未 `start` 发音频→`error:not_started`、`start` 缺参→`error:invalid_start`、100ms 块切成 5×20ms（样本对齐）。
- `test_cli.py`（切片3）— 参数校验、缺输入源非零退出、连接失败提示；HTTP/WS 用 mock 桩。
- **真实端到端（不进 pytest CI）**：用系统环境变量 `DASHSCOPE_API_KEY` 跑一次真实文件识别 + 一次真实流式，作为 tasks 8.3 的手动验证脚本，单独记录。

## 8. 实现顺序（A + 每切片 TDD）

0. **SDK 假设确认**（非项目文件，5 分钟）：检查已装 `dashscope.audio.asr.Recognition` 的 `call` / `start` / `send_audio_frame` / `stop` 与 `RecognitionCallback` 签名是否与 openspec 一致；确认 `send_audio_frame` 是否接受任意大小帧（决定 3.3 是否简化）；确认 model ID 与 `model↔sample_rate` 兼容矩阵并写入 `config.yaml`；确认 diarization 的 SDK 参数名与返回结构（`speaker` 字段来源）。不一致则先调整 `models`/`service`/`realtime_recognizer` 接口再写测试。
1. 骨架 + `config.py` + `models.py` + `requirements.txt` / `config.yaml` / `pytest.ini`（无 SDK）。
2. **切片1 HTTP**：`test_service` → `service` → `test_asr_route` → `routes/asr.py`（HTTP 部分）→ 真实 Key 冒烟。
3. **切片2 WS**：`test_realtime` → `realtime_recognizer` → `routes/asr.py`（WS 部分）→ 真实流式冒烟。
4. **切片3 CLI**：file / stream / 麦克风懒加载（`sounddevice`，未装给提示）。
5. `README.md`（启动命令、API 示例、CLI 示例）+ 全量 `pytest -q -p no:cacheprovider`。

`requirements.txt`：`fastapi`、`uvicorn`、`pydantic`、`pyyaml`、`python-dotenv`、`httpx`、`httpx-ws`、`dashscope`；可选（麦克风）：`sounddevice`、`numpy`（懒加载，文档说明安装方式）。

## 9. 风险与权衡

- **[Risk] SDK 回调线程与 asyncio 事件循环耦合** → 所有回调只入 `asyncio.Queue`，处理逻辑全在协程；与 `TTS/api/realtime_synthesizer.py` 的 `_Callback` 桥接模式一致。
- **[Risk] SDK API 与 openspec 假设不符** → step 0 前置确认；不符则调整接口再写测试，避免 TDD 建立在错误假设上。
- **[Risk] 实时识别对音频格式/采样率敏感** → API 与 CLI 强制声明 `format`/`sample_rate`，`start` 帧按组合表校验；切片守样本对齐。
- **[Risk] 临时文件未清理** → `try/finally` 保证删除。
- **[Risk] 大文件同步识别阻塞工作线程** → MVP 保持 `Recognition.call` 同步；后续如需长音频再迁移到 `Transcription` + 文件托管。
- **[Risk] 麦克风录音库跨平台二进制（PortAudio）** → 懒加载，未安装给明确提示，不阻塞核心功能。
