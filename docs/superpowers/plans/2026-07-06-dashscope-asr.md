# DashScope ASR 服务实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `C:\work\PythonProgram\Agent\ASR` 实现一个对称于 TTS 的 DashScope ASR 服务：HTTP 文件上传识别 + WebSocket 实时流式识别 + CLI，全部带 pytest 测试。

**Architecture:** FastAPI 应用工厂 + 服务层 + 路由层 + CLI 分层。文件识别走 `Recognition.call(file=...)`；实时识别走 `Recognition.start()/send_audio_frame()/stop()`，SDK 回调经 `asyncio.Queue` + `call_soon_threadsafe` 桥接到事件循环。每切片 TDD：先按 spec 写 mock 测试，再实现到绿。

**Tech Stack:** Python 3.10+、FastAPI、uvicorn、Pydantic v2、pyyaml、httpx、httpx-ws、dashscope==1.26.0、pytest、pytest-asyncio。

---

## 已验证的 SDK API（dashscope 1.26.0，无需再次探测）

```python
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

# 构造：model/format/sample_rate 是构造参数，不是 call 参数
Recognition(model: str, callback: RecognitionCallback, format: str,
            sample_rate: int, workspace: str = None, **kwargs)

# 同步文件识别
Recognition.call(file: str, phrase_id: str = None, **kwargs) -> RecognitionResult
#   **kwargs 含: disfluency_removal_enabled, diarization_enabled(bool), speaker_count(int),
#                timestamp_alignment_enabled, special_word_filter, audio_event_detection_enabled
#   注意: call() 不触发 callback（构造时传一个空 callback 即可）

# 实时流式
Recognition.start(phrase_id: str = None, **kwargs) -> None      # 同上 kwargs
Recognition.send_audio_frame(buffer: bytes) -> None             # 把字节放入内部队列
Recognition.stop() -> None                                       # 结束并 join worker，触发 on_close
#   注意: 没有 cancel()。cancel 用 stop()+丢弃结果实现。

# RecognitionResult
result.status_code  # 200 表示成功
result.code / result.message  # 错误信息
result.get_sentence()  # call() 返回 list[dict]；on_event 返回单个 dict
RecognitionResult.is_sentence_end(sentence_dict) -> bool  # 静态方法，有 end_time 即为句尾
# sentence dict 字段: text, begin_time, end_time, speaker_id(仅 diarization 开启)

# RecognitionCallback（重写需要的即可）
on_open() / on_event(result) / on_complete() / on_error(result) / on_close()
#   on_event: 中间/句尾结果（用 is_sentence_end 区分 partial/sentence）
#   on_complete: 流正常结束 → 发 done
#   on_error(result): 出错 → 发 error
#   on_close: 连接关闭（stop() 会触发）
```

**API Key**：dashscope 在 import 时自动读 `DASHSCOPE_API_KEY` 环境变量；本计划额外在 service/realtime 里显式 `dashscope.api_key = get_api_key()` 以便校验缺失时快速失败。

---

## 文件结构

```
ASR/
├── api/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 应用工厂 + 异常处理 + 路由注册
│   ├── config.py               # AppConfig / load_config / get_api_key
│   ├── models.py               # Pydantic 模型
│   ├── service.py              # recognize_file()
│   ├── realtime_recognizer.py  # RealtimeRecognizer + _Callback
│   └── routes/
│       ├── __init__.py
│       ├── health.py           # GET /health
│       └── asr.py              # POST /api/v1/asr + WS /api/v1/asr/ws
├── cli/
│   ├── __init__.py
│   └── asr.py                  # CLI
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_service.py
│   ├── test_health.py
│   ├── test_asr_route.py
│   ├── test_realtime.py
│   └── test_cli.py
├── config.yaml
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
└── README.md
```

每个文件单一职责：`config` 只管配置与密钥；`models` 只管数据形状；`service` 只管同步识别+解析；`realtime_recognizer` 只管流式生命周期+回调桥接；`routes/asr` 只管 HTTP/WS 协议；`cli` 只管参数与调用。

---

## Task 1: 项目骨架与依赖

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `config.yaml`, `pytest.ini`
- Create: `api/__init__.py`, `api/routes/__init__.py`, `cli/__init__.py`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: 创建依赖文件**

`requirements.txt`:
```
fastapi
uvicorn[standard]
pydantic>=2
pyyaml
python-dotenv
httpx
httpx-ws
dashscope>=1.26.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest
pytest-asyncio
```

- [ ] **Step 2: 创建 config.yaml**

`config.yaml`:
```yaml
server:
  host: 0.0.0.0
  port: 8000
dashscope:
  default_model: paraformer-realtime-v2
asr:
  formats: [pcm, wav, mp3]
  sample_rates: [8000, 16000, 24000, 44100, 48000]
  supported_combinations:
    - [paraformer-realtime-v2, 16000]
    - [paraformer-realtime-8k-v2, 8000]
  frame_ms: 20
```

- [ ] **Step 3: 创建 pytest.ini**

`pytest.ini`:
```ini
[pytest]
testpaths = tests
addopts = -q -p no:cacheprovider
asyncio_mode = auto
```

- [ ] **Step 4: 创建空 `__init__.py` 与 conftest 占位**

`api/__init__.py`、`api/routes/__init__.py`、`cli/__init__.py`、`tests/__init__.py`：空文件。

`tests/conftest.py`:
```python
import os
import pytest


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """测试默认提供假 key，避免误用真实密钥。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
```

- [ ] **Step 5: 安装依赖并验证可导入**

Run: `pip install -r requirements-dev.txt`
Expected: 安装成功，无报错。

- [ ] **Step 6: Commit**

```bash
git add requirements.txt requirements-dev.txt config.yaml pytest.ini api/__init__.py api/routes/__init__.py cli/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore(asr): project skeleton, deps, config, pytest"
```

---

## Task 2: config.py

**Files:**
- Create: `api/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

`tests/test_config.py`:
```python
import pytest
from api.config import AppConfig, load_config, get_api_key


def test_load_config_reads_yaml():
    cfg = load_config()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8000
    assert cfg.default_model == "paraformer-realtime-v2"
    assert "pcm" in cfg.formats
    assert 16000 in cfg.sample_rates
    assert cfg.frame_ms == 20


def test_is_supported_combination():
    cfg = load_config()
    assert cfg.is_supported("paraformer-realtime-v2", "wav", 16000) is True
    assert cfg.is_supported("paraformer-realtime-v2", "wav", 8000) is False  # 16k 模型不配 8k
    assert cfg.is_supported("paraformer-realtime-v2", "ogg", 16000) is False  # 不支持格式
    assert cfg.is_supported("nope", "wav", 16000) is False


def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_api_key()


def test_get_api_key_present(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "abc123")
    assert get_api_key() == "abc123"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'api.config'`）

- [ ] **Step 3: 实现 config.py**

`api/config.py`:
```python
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass
class AppConfig:
    host: str
    port: int
    default_model: str
    formats: List[str]
    sample_rates: List[int]
    supported_combinations: List[Tuple[str, int]]
    frame_ms: int

    def is_supported(self, model: str, format: str, sample_rate: int) -> bool:
        if format not in self.formats:
            return False
        if sample_rate not in self.sample_rates:
            return False
        return (model, sample_rate) in self.supported_combinations


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    combos = [(c[0], int(c[1])) for c in raw["asr"]["supported_combinations"]]
    return AppConfig(
        host=raw["server"]["host"],
        port=int(raw["server"]["port"]),
        default_model=raw["dashscope"]["default_model"],
        formats=list(raw["asr"]["formats"]),
        sample_rates=list(raw["asr"]["sample_rates"]),
        supported_combinations=combos,
        frame_ms=int(raw["asr"]["frame_ms"]),
    )


def get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY environment variable not set")
    return key
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api/config.py tests/test_config.py
git commit -m "feat(asr): config loader with supported-combination validation"
```

---

## Task 3: models.py

**Files:**
- Create: `api/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试**

`tests/test_models.py`:
```python
import pytest
from pydantic import ValidationError
from api.models import ASRSentence, ASRUploadResponse, WSControlMessage, WSResultMessage


def test_asr_sentence_speaker_optional():
    s = ASRSentence(text="hi", begin_time=0, end_time=100, is_final=True)
    assert s.speaker is None


def test_upload_response():
    r = ASRUploadResponse(text="hi", sentences=[
        ASRSentence(text="hi", begin_time=0, end_time=100, is_final=True)
    ], duration_ms=100)
    assert r.duration_ms == 100


def test_ws_control_start_valid():
    m = WSControlMessage(action="start", model="paraformer-realtime-v2",
                         format="pcm", sample_rate=16000)
    assert m.enable_diarization is False


def test_ws_control_invalid_action():
    with pytest.raises(ValidationError):
        WSControlMessage(action="bogus")


def test_ws_result_error_frame():
    m = WSResultMessage(type="error", code="invalid_start", message="bad")
    assert m.code == "invalid_start"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_models.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 models.py**

`api/models.py`:
```python
from typing import List, Literal, Optional

from pydantic import BaseModel


class ASRSentence(BaseModel):
    text: str
    begin_time: int
    end_time: int
    is_final: bool
    speaker: Optional[str] = None


class ASRUploadResponse(BaseModel):
    text: str
    sentences: List[ASRSentence]
    duration_ms: int


class WSControlMessage(BaseModel):
    action: Literal["start", "finish", "cancel"]
    model: Optional[str] = None
    format: Optional[str] = None
    sample_rate: Optional[int] = None
    enable_diarization: bool = False


class WSResultMessage(BaseModel):
    type: Literal["ready", "partial", "sentence", "done", "error"]
    text: Optional[str] = None
    begin_time: Optional[int] = None
    end_time: Optional[int] = None
    duration_ms: Optional[int] = None
    speaker: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_models.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add api/models.py tests/test_models.py
git commit -m "feat(asr): pydantic models for upload response and ws protocol"
```

---

## Task 4: service.py（非流式识别，切片1核心）

**Files:**
- Create: `api/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: 写失败测试**

`tests/test_service.py`:
```python
from types import SimpleNamespace
from unittest.mock import MagicMock

from api.service import recognize_file, _parse_sentences


def _fake_result(sentences, status_code=200, code=None, message=None):
    return SimpleNamespace(
        status_code=status_code, code=code, message=message,
        get_sentence=lambda: sentences,
    )


def test_parse_single_sentence_final():
    res = _fake_result([{"text": "你好", "begin_time": 0, "end_time": 1500}])
    out = _parse_sentences(res)
    assert len(out) == 1
    assert out[0].text == "你好"
    assert out[0].is_final is True
    assert out[0].end_time == 1500


def test_parse_multi_sentence():
    res = _fake_result([
        {"text": "第一句", "begin_time": 0, "end_time": 1000},
        {"text": "第二句", "begin_time": 1000, "end_time": 2000},
    ])
    out = _parse_sentences(res)
    assert len(out) == 2
    assert all(s.is_final for s in out)


def test_parse_diarization_speaker():
    res = _fake_result([{"text": "hi", "begin_time": 0, "end_time": 100, "speaker_id": 2}])
    out = _parse_sentences(res)
    assert out[0].speaker == "2"


def test_recognize_file_success(monkeypatch):
    fake_result = _fake_result([{"text": "你好", "begin_time": 0, "end_time": 1500}])
    fake_instance = MagicMock()
    fake_instance.call.return_value = fake_result
    fake_cls = MagicMock(return_value=fake_instance)
    monkeypatch.setattr("api.service.Recognition", fake_cls)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    resp = recognize_file("x.wav", "paraformer-realtime-v2", "wav", 16000)
    assert resp.text == "你好"
    assert resp.duration_ms == 1500
    assert resp.sentences[0].is_final is True
    # 确认构造时传了 model/format/sample_rate
    _, kwargs = fake_cls.call_args
    assert kwargs["model"] == "paraformer-realtime-v2"
    assert kwargs["format"] == "wav"
    assert kwargs["sample_rate"] == 16000


def test_recognize_file_diarization_passes_kwarg(monkeypatch):
    fake_result = _fake_result([{"text": "hi", "begin_time": 0, "end_time": 100}])
    fake_instance = MagicMock()
    fake_instance.call.return_value = fake_result
    monkeypatch.setattr("api.service.Recognition", MagicMock(return_value=fake_instance))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    recognize_file("x.wav", "paraformer-realtime-v2", "wav", 16000, enable_diarization=True)
    _, kwargs = fake_instance.call.call_args
    assert kwargs.get("diarization_enabled") is True


def test_recognize_file_sdk_error(monkeypatch):
    fake_result = _fake_result([], status_code=400, code="Bad Request", message="nope")
    fake_instance = MagicMock()
    fake_instance.call.return_value = fake_result
    monkeypatch.setattr("api.service.Recognition", MagicMock(return_value=fake_instance))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    import pytest
    with pytest.raises(RuntimeError):
        recognize_file("x.wav", "paraformer-realtime-v2", "wav", 16000)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_service.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 service.py**

`api/service.py`:
```python
from typing import List

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from api.config import get_api_key
from api.models import ASRSentence, ASRUploadResponse


class _NoopCallback(RecognitionCallback):
    """Recognition 构造要求 callback；同步 call() 不会触发它，给个空实现即可。"""
    pass


def _parse_sentences(result: RecognitionResult) -> List[ASRSentence]:
    raw = result.get_sentence()
    if not raw:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: List[ASRSentence] = []
    for s in items:
        out.append(ASRSentence(
            text=s.get("text", ""),
            begin_time=int(s.get("begin_time") or 0),
            end_time=int(s.get("end_time") or 0),
            is_final=RecognitionResult.is_sentence_end(s),
            speaker=(str(s["speaker_id"]) if "speaker_id" in s else None),
        ))
    return out


def recognize_file(path: str, model: str, format: str, sample_rate: int,
                   enable_diarization: bool = False) -> ASRUploadResponse:
    dashscope.api_key = get_api_key()
    recognition = Recognition(
        model=model,
        callback=_NoopCallback(),
        format=format,
        sample_rate=sample_rate,
    )
    kwargs = {"diarization_enabled": True} if enable_diarization else {}
    result = recognition.call(file=path, **kwargs)
    if result.status_code != 200:
        raise RuntimeError(f"ASR failed: code={result.code} message={result.message}")
    sentences = _parse_sentences(result)
    text = "".join(s.text for s in sentences)
    duration_ms = max((s.end_time for s in sentences), default=0)
    return ASRUploadResponse(text=text, sentences=sentences, duration_ms=duration_ms)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_service.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add api/service.py tests/test_service.py
git commit -m "feat(asr): non-streaming recognize_file with sentence parsing"
```

---

## Task 5: health 路由 + 应用工厂（为 HTTP 路由测试打基础）

**Files:**
- Create: `api/routes/health.py`, `api/main.py`
- Test: `tests/test_health.py`

- [ ] **Step 1: 写失败测试**

`tests/test_health.py`:
```python
from fastapi.testclient import TestClient
from api.main import create_app


def test_health():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_health.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 health.py 与 main.py**

`api/routes/health.py`:
```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
```

`api/main.py`:
```python
from fastapi import FastAPI

from api.config import load_config
from api.routes import health


def create_app() -> FastAPI:
    app = FastAPI(title="DashScope ASR")
    app.state.config = load_config()
    app.include_router(health.router)
    # asr 路由在 Task 6 注册
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    cfg = app.state.config
    uvicorn.run(app, host=cfg.host, port=cfg.port)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_health.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add api/routes/health.py api/main.py tests/test_health.py
git commit -m "feat(asr): health route and app factory"
```

---

## Task 6: HTTP 文件上传路由（切片1完成）

**Files:**
- Create: `api/routes/asr.py`
- Modify: `api/main.py`（注册 asr 路由）
- Test: `tests/test_asr_route.py`

- [ ] **Step 1: 写失败测试**

`tests/test_asr_route.py`:
```python
from io import BytesIO
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.main import create_app
from api.models import ASRSentence, ASRUploadResponse


def _client_with_mock_service(monkeypatch, resp=None, error=None):
    def fake_recognize(path, model, format, sample_rate, enable_diarization=False):
        if error:
            raise error
        return resp or ASRUploadResponse(
            text="你好", sentences=[ASRSentence(text="你好", begin_time=0, end_time=1500, is_final=True)],
            duration_ms=1500)
    monkeypatch.setattr("api.routes.asr.recognize_file", fake_recognize)
    return TestClient(create_app())


def _wav_bytes():
    # 12 字节伪 wav，内容不影响（service 被 mock）
    return BytesIO(b"RIFF\x00\x00\x00\x00WAVEfmt ")


def test_upload_success(monkeypatch):
    client = _client_with_mock_service(monkeypatch)
    resp = client.post(
        "/api/v1/asr",
        files={"file": ("hello.wav", _wav_bytes(), "audio/wav")},
        data={"model": "paraformer-realtime-v2", "format": "wav", "sample_rate": "16000"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "你好"
    assert body["duration_ms"] == 1500


def test_upload_missing_file(monkeypatch):
    client = _client_with_mock_service(monkeypatch)
    resp = client.post(
        "/api/v1/asr",
        data={"model": "paraformer-realtime-v2", "format": "wav", "sample_rate": "16000"},
    )
    assert resp.status_code == 422


def test_upload_unsupported_format(monkeypatch):
    client = _client_with_mock_service(monkeypatch)
    resp = client.post(
        "/api/v1/asr",
        files={"file": ("x.ogg", _wav_bytes(), "audio/ogg")},
        data={"model": "paraformer-realtime-v2", "format": "ogg", "sample_rate": "16000"},
    )
    assert resp.status_code == 400


def test_upload_unsupported_combination(monkeypatch):
    client = _client_with_mock_service(monkeypatch)
    resp = client.post(
        "/api/v1/asr",
        files={"file": ("x.wav", _wav_bytes(), "audio/wav")},
        data={"model": "paraformer-realtime-v2", "format": "wav", "sample_rate": "8000"},
    )
    assert resp.status_code == 400


def test_upload_service_error_returns_500(monkeypatch):
    client = _client_with_mock_service(monkeypatch, error=RuntimeError("boom"))
    resp = client.post(
        "/api/v1/asr",
        files={"file": ("x.wav", _wav_bytes(), "audio/wav")},
        data={"model": "paraformer-realtime-v2", "format": "wav", "sample_rate": "16000"},
    )
    assert resp.status_code == 500
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_asr_route.py -v`
Expected: FAIL（路由不存在 / 404）

- [ ] **Step 3: 实现 asr.py 路由（HTTP 部分）**

`api/routes/asr.py`:
```python
import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, Request

from api.models import ASRUploadResponse
from api.service import recognize_file

router = APIRouter(prefix="/api/v1")


@router.post("/asr", response_model=ASRUploadResponse)
async def upload_asr(
    request: Request,
    file = File(...),
    model: str = Form(...),
    format: str = Form(...),
    sample_rate: int = Form(...),
    enable_diarization: bool = Form(False),
):
    cfg = request.app.state.config
    if not cfg.is_supported(model, format, sample_rate):
        raise HTTPException(status_code=400,
                            detail=f"unsupported model/format/sample_rate: {model}/{format}/{sample_rate}")

    suffix = os.path.splitext(file.filename or "audio")[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        content = await file.read()
        tmp.write(content)
        tmp.flush()
        tmp.close()
        try:
            return recognize_file(tmp.name, model, format, sample_rate, enable_diarization)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
```

修改 `api/main.py`，在 `create_app` 里注册 asr 路由（在 `include_router(health.router)` 之后加）:
```python
from api.routes import asr as asr_route
...
    app.include_router(asr_route.router)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_asr_route.py -v`
Expected: 5 passed

- [ ] **Step 5: 运行全部测试**

Run: `pytest -v`
Expected: 全绿（config/models/service/health/asr_route）

- [ ] **Step 6: Commit**

```bash
git add api/routes/asr.py api/main.py tests/test_asr_route.py
git commit -m "feat(asr): HTTP file upload route with validation and temp-file cleanup"
```

---

## Task 7: 真实端到端冒烟（文件上传，手动验证）

**Files:** 无新增代码，手动脚本验证。

- [ ] **Step 1: 准备一段测试音频**

用任意方式准备一个 16kHz wav（如用现有 TTS 生成，或录制一句"你好，这是一个测试"）。放到 `ASR/smoke/hello.wav`（`smoke/` 已在 `.gitignore` 之外，但音频不入库——可手动加 `*.wav` 到 `.gitignore`）。

先在 `.gitignore` 末尾追加：
```
# smoke test audio
smoke/
*.wav
*.mp3
*.pcm
```

- [ ] **Step 2: 启动服务**

Run: `python -m api.main`
Expected: uvicorn 启动，监听 `0.0.0.0:8000`。

- [ ] **Step 3: 用 curl 上传**

Run: `curl -s -X POST http://localhost:8000/api/v1/asr -F "file=@smoke/hello.wav" -F "model=paraformer-realtime-v2" -F "format=wav" -F "sample_rate=16000"`
Expected: 返回 JSON，`text` 为识别出的文字，`sentences` 含时间戳。

- [ ] **Step 4: 若失败则排查**

常见：`DASHSCOPE_API_KEY` 未生效（确认系统环境变量在启动进程可见）、模型名错误（调整 `config.yaml` 的 `supported_combinations`）、音频采样率与模型不匹配。修复后重跑。

- [ ] **Step 5: 提交 .gitignore 更新**

```bash
git add .gitignore
git commit -m "chore(asr): ignore smoke test audio"
```

---

## Task 8: realtime_recognizer.py（切片2核心）

**Files:**
- Create: `api/realtime_recognizer.py`
- Test: `tests/test_realtime.py`（recognizer 部分）

- [ ] **Step 1: 写失败测试（recognizer 行为）**

`tests/test_realtime.py`:
```python
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.config import load_config
from api.realtime_recognizer import RealtimeRecognizer, _Callback


def _cfg():
    return load_config()


def test_send_audio_chunk_slices_20ms(monkeypatch):
    """100ms @16k = 3200 bytes; frame=640 bytes → 5 次 send_audio_frame"""
    fake_instance = MagicMock()
    fake_cls = MagicMock(return_value=fake_instance)
    monkeypatch.setattr("api.realtime_recognizer.Recognition", fake_cls)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    loop = asyncio.new_event_loop()
    try:
        rec = RealtimeRecognizer(_cfg(), "paraformer-realtime-v2", "pcm", 16000, loop=loop)
        rec.send_audio_chunk(b"\x00" * 3200)
        assert fake_instance.send_audio_frame.call_count == 5
        for call in fake_instance.send_audio_frame.call_args_list:
            assert len(call.args[0]) == 640
    finally:
        loop.close()


def test_send_audio_chunk_sample_aligned(monkeypatch):
    """奇数字节输入：跨调用保留 1 字节，下次拼回，不送半样本。"""
    fake_instance = MagicMock()
    monkeypatch.setattr("api.realtime_recognizer.Recognition",
                        MagicMock(return_value=fake_instance))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    loop = asyncio.new_event_loop()
    try:
        rec = RealtimeRecognizer(_cfg(), "paraformer-realtime-v2", "pcm", 16000, loop=loop)
        rec.send_audio_chunk(b"\x00" * 3201)  # 奇数
        # 3201 = 5*640 + 1，残留 1 字节，应只送 5 帧
        assert fake_instance.send_audio_frame.call_count == 5
        rec.send_audio_chunk(b"\x00" * 639)  # 残留1 + 639 = 640，补成完整一帧
        assert fake_instance.send_audio_frame.call_count == 6
    finally:
        loop.close()


def test_callback_on_event_partial_and_sentence():
    loop = asyncio.new_event_loop()
    q = asyncio.Queue()
    cb = _Callback(loop, q)

    # 中间结果（无 end_time）→ partial
    partial = SimpleNamespace(get_sentence=lambda: {"text": "你", "begin_time": 0})
    cb.on_event(partial)
    # 句尾（有 end_time）→ sentence
    final = SimpleNamespace(get_sentence=lambda: {"text": "你好", "begin_time": 0, "end_time": 1500})
    cb.on_event(final)

    loop.call_soon(cb._put, {"type": "sentinel"})  # flush
    loop.run_until_complete(asyncio.sleep(0.01))

    items = []
    while not q.empty():
        items.append(loop.run_until_complete(q.get()))
    types = [i["type"] for i in items if i["type"] != "sentinel"]
    assert "partial" in types and "sentence" in types
    sent = [i for i in items if i["type"] == "sentence"][0]
    assert sent["text"] == "你好"
    assert sent["end_time"] == 1500


def test_callback_on_error_and_complete():
    loop = asyncio.new_event_loop()
    q = asyncio.Queue()
    cb = _Callback(loop, q)
    cb.on_error(SimpleNamespace(message="boom"))
    cb.on_complete()
    loop.run_until_complete(asyncio.sleep(0.01))
    items = []
    while not q.empty():
        items.append(loop.run_until_complete(q.get()))
    assert any(i["type"] == "error" and i["code"] == "internal" for i in items)
    assert any(i["type"] == "done" for i in items)


def test_start_stop_delegate(monkeypatch):
    fake_instance = MagicMock()
    monkeypatch.setattr("api.realtime_recognizer.Recognition",
                        MagicMock(return_value=fake_instance))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    loop = asyncio.new_event_loop()
    try:
        rec = RealtimeRecognizer(_cfg(), "paraformer-realtime-v2", "pcm", 16000, loop=loop)
        rec.start()
        fake_instance.start.assert_called_once()
        rec.stop()
        fake_instance.stop.assert_called_once()
    finally:
        loop.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_realtime.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 realtime_recognizer.py**

`api/realtime_recognizer.py`:
```python
import asyncio
from typing import AsyncIterator, Optional

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from api.config import AppConfig, get_api_key


class _Callback(RecognitionCallback):
    """SDK 回调在 worker 线程触发；只把结果丢进 asyncio.Queue。"""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self._loop = loop
        self._queue = queue
        self._last_end_time = 0

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if sentence is None:
            return
        items = sentence if isinstance(sentence, list) else [sentence]
        for s in items:
            is_end = RecognitionResult.is_sentence_end(s)
            end_time = s.get("end_time")
            if end_time:
                self._last_end_time = max(self._last_end_time, int(end_time))
            self._put({
                "type": "sentence" if is_end else "partial",
                "text": s.get("text", ""),
                "begin_time": s.get("begin_time"),
                "end_time": end_time,
                "speaker": (str(s["speaker_id"]) if "speaker_id" in s else None),
            })

    def on_error(self, result: RecognitionResult) -> None:
        self._put({"type": "error", "code": "internal",
                   "message": getattr(result, "message", None) or "recognition error"})

    def on_complete(self) -> None:
        self._put({"type": "done", "duration_ms": self._last_end_time})

    def on_close(self) -> None:
        self._put({"type": "closed"})

    def _put(self, item: dict) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, item)


class RealtimeRecognizer:
    def __init__(self, config: AppConfig, model: str, format: str,
                 sample_rate: int, enable_diarization: bool = False,
                 loop: Optional[asyncio.AbstractEventLoop] = None):
        self._sample_rate = sample_rate
        self._frame_ms = config.frame_ms
        self._loop = loop or asyncio.get_event_loop()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._callback = _Callback(self._loop, self._queue)
        dashscope.api_key = get_api_key()
        self._recognition = Recognition(
            model=model, callback=self._callback,
            format=format, sample_rate=sample_rate,
        )
        self._kwargs = {"diarization_enabled": True} if enable_diarization else {}
        self._leftover = b""
        self._running = False

    def start(self) -> None:
        self._recognition.start(**self._kwargs)
        self._running = True

    def _frame_bytes(self) -> int:
        # 16-bit mono: 每帧字节数 = sample_rate * 2 * (frame_ms/1000)，并对齐到偶数
        size = int(self._sample_rate * 2 * (self._frame_ms / 1000))
        size -= size % 2
        return max(2, size)

    def send_audio_chunk(self, data: bytes) -> None:
        frame = self._frame_bytes()
        data = self._leftover + data
        # 只保留整样本（偶数长度），奇数尾巴留到下次
        if len(data) % 2:
            self._leftover = data[-1:]
            data = data[:-1]
        else:
            self._leftover = b""
        for i in range(0, len(data), frame):
            chunk = data[i:i + frame]
            if chunk:
                self._recognition.send_audio_frame(chunk)

    def stop(self) -> None:
        self._running = False
        self._recognition.stop()

    def cancel(self) -> None:
        # SDK 无 cancel：用 stop() 优雅停止，丢弃后续结果。
        self._running = False
        try:
            self._recognition.stop()
        except Exception:
            pass

    async def results(self) -> AsyncIterator[dict]:
        while True:
            item = await self._queue.get()
            yield item
            if item.get("type") in ("done", "error", "closed"):
                break
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_realtime.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add api/realtime_recognizer.py tests/test_realtime.py
git commit -m "feat(asr): realtime recognizer with sample-aligned slicing and callback bridge"
```

---

## Task 9: WebSocket 实时路由（切片2完成）

**Files:**
- Modify: `api/routes/asr.py`（加 WS 路由）
- Test: `tests/test_realtime.py`（追加 WS 路由测试）

- [ ] **Step 1: 追加 WS 路由测试**

在 `tests/test_realtime.py` 末尾追加：
```python
import json
from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient
from api.main import create_app


class _FakeRecognizer:
    """可控的假识别器：按预设序列吐结果。"""
    def __init__(self, events):
        self._events = events
        self.started = False
        self.stopped = False
        self.cancelled = False
        self.chunks = []

    def start(self):
        self.started = True

    def send_audio_chunk(self, data):
        self.chunks.append(data)

    def stop(self):
        self.stopped = True

    def cancel(self):
        self.cancelled = True

    async def results(self):
        for e in self._events:
            yield e


def _client_with_fake_recognizer(monkeypatch, events):
    monkeypatch.setattr("api.routes.asr.RealtimeRecognizer",
                        lambda *a, **k: _FakeRecognizer(events))
    return TestClient(create_app())


def test_ws_start_ready(monkeypatch):
    client = _client_with_fake_recognizer(monkeypatch, [])
    with client.websocket_connect("/api/v1/asr/ws") as ws:
        ws.send_json({"action": "start", "model": "paraformer-realtime-v2",
                      "format": "pcm", "sample_rate": 16000})
        msg = ws.receive_json()
    assert msg["type"] == "ready"


def test_ws_invalid_start_missing_format(monkeypatch):
    client = _client_with_fake_recognizer(monkeypatch, [])
    with client.websocket_connect("/api/v1/asr/ws") as ws:
        ws.send_json({"action": "start", "model": "paraformer-realtime-v2",
                      "format": "pcm"})  # 缺 sample_rate
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == "invalid_start"


def test_ws_not_started_on_binary(monkeypatch):
    client = _client_with_fake_recognizer(monkeypatch, [])
    with client.websocket_connect("/api/v1/asr/ws") as ws:
        ws.send_bytes(b"\x00" * 640)
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == "not_started"


def test_ws_partial_sentence_done(monkeypatch):
    events = [
        {"type": "partial", "text": "你"},
        {"type": "sentence", "text": "你好", "begin_time": 0, "end_time": 1500},
        {"type": "done", "duration_ms": 1500},
    ]
    client = _client_with_fake_recognizer(monkeypatch, events)
    with client.websocket_connect("/api/v1/asr/ws") as ws:
        ws.send_json({"action": "start", "model": "paraformer-realtime-v2",
                      "format": "pcm", "sample_rate": 16000})
        ws.receive_json()  # ready
        ws.send_bytes(b"\x00" * 640)
        ws.send_json({"action": "finish"})
        msgs = [ws.receive_json() for _ in range(3)]
    assert [m["type"] for m in msgs] == ["partial", "sentence", "done"]


def test_ws_cancel(monkeypatch):
    events = [{"type": "error", "code": "cancelled", "message": "session cancelled"}]
    client = _client_with_fake_recognizer(monkeypatch, events)
    with client.websocket_connect("/api/v1/asr/ws") as ws:
        ws.send_json({"action": "start", "model": "paraformer-realtime-v2",
                      "format": "pcm", "sample_rate": 16000})
        ws.receive_json()
        ws.send_json({"action": "cancel"})
        msg = ws.receive_json()
    assert msg["code"] == "cancelled"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_realtime.py -v -k ws`
Expected: FAIL（WS 路由不存在）

- [ ] **Step 3: 实现 WS 路由**

在 `api/routes/asr.py` 顶部追加导入，并新增 WS 处理函数：
```python
import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
from starlette.status import WS_1008_POLICY_VIOLATION

from api.config import AppConfig
from api.models import WSControlMessage, WSResultMessage
from api.realtime_recognizer import RealtimeRecognizer
```
（`recognize_file`、`ASRUploadResponse` 等已有导入保留。）

在文件末尾追加：
```python
async def _send_error(ws: WebSocket, code: str, message: str) -> None:
    await ws.send_json(WSResultMessage(type="error", code=code, message=message).model_dump())


@router.websocket("/asr/ws")
async def asr_ws(websocket: WebSocket):
    await websocket.accept()
    cfg: AppConfig = websocket.app.state.config

    # 1) 等 start 帧；先收到二进制 → not_started
    first = await websocket.receive()
    if first.get("bytes") is not None:
        await _send_error(websocket, "not_started", "send start control frame first")
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return
    try:
        ctrl = WSControlMessage(**json.loads(first["text"]))
    except Exception:
        await _send_error(websocket, "invalid_start", "invalid start frame")
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return

    if ctrl.action != "start" or not ctrl.model or not ctrl.format or not ctrl.sample_rate:
        await _send_error(websocket, "invalid_start", "start requires model/format/sample_rate")
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return
    if not cfg.is_supported(ctrl.model, ctrl.format, ctrl.sample_rate):
        await _send_error(websocket, "invalid_start", "unsupported model/format/sample_rate")
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return

    loop = asyncio.get_running_loop()
    recognizer = RealtimeRecognizer(
        cfg, ctrl.model, ctrl.format, ctrl.sample_rate,
        ctrl.enable_diarization, loop=loop)
    try:
        recognizer.start()
    except Exception as e:
        await _send_error(websocket, "internal", str(e))
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return
    await websocket.send_json(WSResultMessage(type="ready").model_dump())

    async def forward_results():
        async for item in recognizer.results():
            await websocket.send_json(WSResultMessage(**item).model_dump())
            if item.get("type") in ("done", "error"):
                return

    async def receive_loop():
        while True:
            msg = await websocket.receive()
            if msg.get("bytes") is not None:
                recognizer.send_audio_chunk(msg["bytes"])
            elif msg.get("text") is not None:
                c = WSControlMessage(**json.loads(msg["text"]))
                if c.action == "finish":
                    recognizer.stop()
                    return
                if c.action == "cancel":
                    recognizer.cancel()
                    await _send_error(websocket, "cancelled", "session cancelled")
                    return

    fwd = asyncio.create_task(forward_results())
    rcv = asyncio.create_task(receive_loop())
    try:
        await asyncio.wait({fwd, rcv}, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        recognizer.cancel()
    finally:
        for t in (fwd, rcv):
            if not t.done():
                t.cancel()
        await websocket.close()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_realtime.py -v`
Expected: 全部 passed（含 5 个 recognizer + 5 个 ws）

- [ ] **Step 5: 运行全部测试**

Run: `pytest -v`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add api/routes/asr.py tests/test_realtime.py
git commit -m "feat(asr): websocket realtime route with state machine and error codes"
```

---

## Task 10: 真实端到端冒烟（流式，手动验证）

**Files:** 无新增代码。

- [ ] **Step 1: 准备裸 PCM**

准备一段 16kHz 16bit mono 的裸 PCM（如从 wav 提取数据段，或用 sox/ffmpeg 转换）。放 `smoke/hello.pcm`。

- [ ] **Step 2: 启动服务**

Run: `python -m api.main`

- [ ] **Step 3: 用 CLI 流式模式验证（CLI 实现后；此处可先手写一次性脚本）**

若 CLI 未实现，先用一次性 Python 脚本：
```python
import asyncio, json
from httpx_ws import aconnect_ws

async def main():
    async with aconnect_ws("ws://localhost:8000/api/v1/asr/ws") as ws:
        await ws.send_json({"action":"start","model":"paraformer-realtime-v2","format":"pcm","sample_rate":16000})
        print(await ws.receive_json())  # ready
        data = open("smoke/hello.pcm","rb").read()
        for i in range(0, len(data), 640):
            await ws.send_bytes(data[i:i+640]); await asyncio.sleep(0.02)
        await ws.send_json({"action":"finish"})
        while True:
            msg = await ws.receive_json()
            print(msg)
            if msg["type"] in ("done","error"): break
asyncio.run(main())
```
Expected: 看到 partial 增量、sentence 句尾、done 结束。

- [ ] **Step 4: 若失败排查**

切片是否样本对齐、PCM 是否真是 16k/16bit/mono、模型与采样率组合是否在 `supported_combinations`。

---

## Task 11: CLI 文件模式（切片3）

**Files:**
- Create: `cli/asr.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

`tests/test_cli.py`:
```python
import json
from unittest.mock import MagicMock

import pytest

from cli.asr import main


def test_missing_source_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0
    out = capsys.readouterr().err
    assert "file" in out.lower() or "usage" in out.lower() or "stream" in out.lower()


def test_file_mode_posts_and_prints_text(monkeypatch, tmp_path, capsys):
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = {"text": "你好", "sentences": [], "duration_ms": 1500}
    fake_client = MagicMock()
    fake_client.post.return_value = fake_resp
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("cli.asr.httpx.Client", lambda **k: fake_client)

    audio = tmp_path / "hello.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    main(["--file", str(audio), "--model", "paraformer-realtime-v2",
          "--format", "wav", "--sample-rate", "16000"])
    out = capsys.readouterr().out
    assert "你好" in out


def test_file_mode_writes_output_json(monkeypatch, tmp_path):
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = {"text": "hi", "sentences": [], "duration_ms": 100}
    fake_client = MagicMock()
    fake_client.post.return_value = fake_resp
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("cli.asr.httpx.Client", lambda **k: fake_client)

    audio = tmp_path / "hello.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    out_path = tmp_path / "result.json"
    main(["--file", str(audio), "--output", str(out_path)])
    assert json.loads(out_path.read_text(encoding="utf-8"))["text"] == "hi"


def test_service_down_hint(monkeypatch, tmp_path, capsys):
    import httpx
    def raise_conn(**k):
        raise httpx.ConnectError("conn refused")
    monkeypatch.setattr("cli.asr.httpx.Client", raise_conn)
    audio = tmp_path / "hello.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    with pytest.raises(SystemExit):
        main(["--file", str(audio)])
    err = capsys.readouterr().err
    assert "启动 ASR 服务" in err or "python -m api.main" in err
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 CLI（文件模式 + 参数骨架）**

`cli/asr.py`:
```python
import argparse
import json
import sys
from pathlib import Path

import httpx

DEFAULT_URL = "http://localhost:8000"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m cli.asr", description="DashScope ASR CLI")
    p.add_argument("--file", help="本地音频文件路径")
    p.add_argument("--stream", action="store_true", help="实时流式识别")
    p.add_argument("--microphone", action="store_true", help="从麦克风采集（仅 --stream）")
    p.add_argument("--model", default="paraformer-realtime-v2")
    p.add_argument("--format", default="pcm")
    p.add_argument("--sample-rate", type=int, default=16000)
    p.add_argument("--enable-diarization", action="store_true")
    p.add_argument("--output", help="将结果写入 JSON 文件（文件模式）")
    p.add_argument("--base-url", default=DEFAULT_URL)
    return p


def _die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def cmd_file(args: argparse.Namespace) -> None:
    try:
        with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
            with open(args.file, "rb") as f:
                files = {"file": (Path(args.file).name, f)}
                data = {"model": args.model, "format": args.format,
                        "sample_rate": str(args.sample_rate)}
                if args.enable_diarization:
                    data["enable_diarization"] = "true"
                resp = client.post("/api/v1/asr", files=files, data=data)
    except httpx.ConnectError:
        _die("无法连接 ASR 服务，请先启动: python -m api.main")
    if resp.status_code != 200:
        _die(f"ASR 请求失败 {resp.status_code}: {resp.text}")
    result = resp.json()
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(result.get("text", ""))


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if not args.file and not args.stream:
        print("用法: python -m cli.asr --file <audio> | --stream [--file <audio> | --microphone]", file=sys.stderr)
        sys.exit(2)
    if args.stream:
        # Task 12 实现
        _die("流式模式尚未实现")
    else:
        if not args.file:
            _die("文件模式需要 --file")
        cmd_file(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_cli.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add cli/asr.py tests/test_cli.py
git commit -m "feat(asr): CLI file mode with output and connection-error hint"
```

---

## Task 12: CLI 流式模式（文件 + 麦克风懒加载）

**Files:**
- Modify: `cli/asr.py`（实现 `cmd_stream`）
- Modify: `tests/test_cli.py`（追加流式测试）

- [ ] **Step 1: 追加流式测试**

在 `tests/test_cli.py` 末尾追加：
```python
@pytest.mark.asyncio
async def test_stream_file_mode_uses_ws(monkeypatch, tmp_path):
    class _FakeWS:
        def __init__(self): self.received = []; self._rcv = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def send_json(self, obj): self.received.append(("json", obj))
        async def send_bytes(self, b): self.received.append(("bytes", len(b)))
        async def receive_json(self):
            self._rcv += 1
            return {"type": "ready"} if self._rcv == 1 else {"type": "done", "duration_ms": 0}

    fake_ws = _FakeWS()
    def fake_connect(url):                       # aconnect_ws 是同步函数，返回 ACM
        assert url.endswith("/api/v1/asr/ws")
        return fake_ws
    monkeypatch.setattr("cli.asr.aconnect_ws", fake_connect)

    pcm = tmp_path / "a.pcm"
    pcm.write_bytes(b"\x00" * 3200)
    from cli.asr import cmd_stream
    args = type("A", (), {"file": str(pcm), "microphone": False, "model": "paraformer-realtime-v2",
                          "format": "pcm", "sample_rate": 16000, "enable_diarization": False,
                          "base_url": "http://localhost:8000"})()
    await cmd_stream(args)
    actions = [o.get("action") for t, o in fake_ws.received if t == "json"]
    assert "start" in actions and "finish" in actions


def test_microphone_missing_dep_hint(monkeypatch, capsys):
    import builtins, asyncio
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "sounddevice":
            raise ImportError("no sounddevice")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    from cli.asr import _read_stream_audio
    args = type("A", (), {"file": None, "microphone": True, "sample_rate": 16000, "format": "pcm"})()
    with pytest.raises(SystemExit):
        asyncio.run(_read_stream_audio(args))
    err = capsys.readouterr().err
    assert "sounddevice" in err
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_cli.py -v -k stream`
Expected: FAIL（`cmd_stream` 不存在 / "尚未实现"）

- [ ] **Step 3: 实现 cmd_stream**

在 `cli/asr.py` 顶部追加导入：
```python
import asyncio
from httpx_ws import aconnect_ws
```

替换 `cmd_stream` 占位（把 `main` 里的 `_die("流式模式尚未实现")` 改为 `cmd_stream(args)`），并新增函数：
```python
def _strip_wav_header(data: bytes) -> bytes:
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    idx = 12
    while idx + 8 <= len(data):
        chunk_id = data[idx:idx + 4]
        chunk_size = int.from_bytes(data[idx + 4:idx + 8], "little")
        if chunk_id == b"data":
            return data[idx + 8:idx + 8 + chunk_size]
        idx += 8 + chunk_size
    return data


async def cmd_stream(args: argparse.Namespace) -> None:
    ws_url = args.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/v1/asr/ws"
    try:
        async with aconnect_ws(ws_url) as ws:
            await ws.send_json({
                "action": "start", "model": args.model, "format": args.format,
                "sample_rate": args.sample_rate, "enable_diarization": args.enable_diarization,
            })
            ready = await ws.receive_json()
            if ready.get("type") == "error":
                _die(f"启动失败: {ready}")

            async def sender():
                data = await _read_stream_audio(args)
                chunk = max(2, int(args.sample_rate * 2 * 0.02))  # 20ms
                for i in range(0, len(data), chunk):
                    await ws.send_bytes(data[i:i + chunk])
                    await asyncio.sleep(0.02)
                await ws.send_json({"action": "finish"})

            async def receiver():
                while True:
                    msg = await ws.receive_json()
                    t = msg.get("type")
                    if t == "partial":
                        print(f"\r{msg.get('text', '')}", end="", flush=True)
                    elif t == "sentence":
                        print(f"\r{msg.get('text', '')}", flush=True)
                    elif t == "done":
                        print(flush=True)
                        return
                    elif t == "error":
                        print(f"\n错误: {msg}", file=sys.stderr)
                        return

            await asyncio.gather(sender(), receiver())
    except httpx.ConnectError:
        _die("无法连接 ASR 服务，请先启动: python -m api.main")


async def _read_stream_audio(args: argparse.Namespace) -> bytes:
    if args.microphone:
        try:
            import sounddevice as sd
        except ImportError:
            _die("麦克风需要 sounddevice，请安装: pip install sounddevice numpy")
        # 录 5 秒 16k mono
        import numpy as np
        rec = sd.rec(int(args.sample_rate * 5), samplerate=args.sample_rate,
                     channels=1, dtype="int16")
        sd.wait()
        return rec.tobytes()
    with open(args.file, "rb") as f:
        data = f.read()
    if args.format == "wav":
        data = _strip_wav_header(data)
    return data
```

并把 `main` 中的 `cmd_stream(args)` 分支改为：
```python
    if args.stream:
        asyncio.run(cmd_stream(args))
    else:
        ...
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_cli.py -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add cli/asr.py tests/test_cli.py
git commit -m "feat(asr): CLI stream mode (file + lazy microphone) over websocket"
```

---

## Task 13: README + 全量测试 + 推送

**Files:**
- Create: `README.md`

- [ ] **Step 1: 写 README.md**

`README.md`:
```markdown
# DashScope ASR

基于 DashScope 的自动语音识别服务，与 TTS 项目对称。提供 HTTP 文件上传识别、WebSocket 实时流式识别与 CLI。

## 安装

```bash
pip install -r requirements-dev.txt
export DASHSCOPE_API_KEY=你的密钥   # Windows: 设系统环境变量 DASHSCOPE_API_KEY
```

## 启动服务

```bash
python -m api.main
# 监听 http://0.0.0.0:8000
```

## HTTP 文件上传

```bash
curl -X POST http://localhost:8000/api/v1/asr \
  -F file=@hello.wav \
  -F model=paraformer-realtime-v2 \
  -F format=wav \
  -F sample_rate=16000
```

返回：`{"text": "...", "sentences": [...], "duration_ms": ...}`

## WebSocket 实时流式

1. 连接 `ws://localhost:8000/api/v1/asr/ws`
2. 发 `{"action":"start","model":"paraformer-realtime-v2","format":"pcm","sample_rate":16000}` → 收 `{"type":"ready"}`
3. 发二进制 PCM 帧 → 收 `partial` / `sentence`
4. 发 `{"action":"finish"}` → 收 `{"type":"done","duration_ms":...}`
5. 或发 `{"action":"cancel"}` 中断

错误码：`invalid_start` / `not_started` / `cancelled` / `internal`

## CLI

```bash
# 文件识别
python -m cli.asr --file hello.wav --format wav --sample-rate 16000
python -m cli.asr --file hello.wav --output result.json

# 流式（文件）
python -m cli.asr --stream --file hello.pcm --format pcm --sample-rate 16000

# 流式（麦克风，需 pip install sounddevice numpy）
python -m cli.asr --stream --microphone --format pcm --sample-rate 16000

# 说话人分离
python -m cli.asr --file meeting.wav --enable-diarization
```

## 测试

```bash
pytest -q -p no:cacheprovider
```

## 支持组合

| model | sample_rate |
|---|---|
| paraformer-realtime-v2 | 16000 |
| paraformer-realtime-8k-v2 | 8000 |

格式：pcm / wav / mp3。可在 `config.yaml` 调整。
```

- [ ] **Step 2: 运行全量测试**

Run: `pytest -q -p no:cacheprovider`
Expected: 全部通过，无失败。

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(asr): README with usage examples"
```

- [ ] **Step 4: 推送**

```bash
git push origin main
```

---

## Self-Review（已完成）

**1. Spec coverage：**
- HTTP 文件上传 + 句子时间戳 + 格式/采样率校验 → Task 6 ✓
- WS start/binary/partial/sentence/finish/cancel + 切片 → Task 8/9 ✓
- CLI file/stream/mic + 参数校验 + 服务未启动提示 → Task 11/12 ✓
- diarization 默认关闭、HTTP+WS 暴露、speaker 字段 → Task 4/6/8/9 ✓
- 切片安全守则（样本对齐、按 sample_rate 推导、WAV 剥头、顺序）→ Task 8（send_audio_chunk + leftover）、Task 12（_strip_wav_header）✓
- 测试 mock SDK + 真实端到端 → Task 7/10 ✓
- README + 全量 pytest → Task 13 ✓

**2. Placeholder scan：** 无 TBD/TODO；每个步骤含完整代码与命令。Task 7/10 的真实音频为手动准备（已说明），非占位。

**3. Type consistency：** `recognize_file(path, model, format, sample_rate, enable_diarization)` 签名在 Task 4 定义、Task 6 调用一致；`RealtimeRecognizer(config, model, format, sample_rate, enable_diarization, loop)` 在 Task 8 定义、Task 9 调用一致；`WSResultMessage` 字段在 Task 3 定义、Task 8/9 使用一致；`_Callback._put` / `results()` 一致。

**已知 trade-off（已写入代码注释/spec）：** SDK 无 `cancel()`，用 `stop()` 优雅停止 + 丢弃结果，非瞬时中断。
