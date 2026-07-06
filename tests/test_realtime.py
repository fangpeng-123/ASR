import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.config import load_config
from api.main import create_app
from api.realtime_recognizer import RealtimeRecognizer, _Callback
from fastapi.testclient import TestClient


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


class _FakeRecognizer:
    """可控的假识别器：按预设序列吐结果，发完后阻塞（模拟真实 queue 等待）。"""
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
        await asyncio.Event().wait()  # 阻塞，模拟真实识别器等待队列


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
    client = _client_with_fake_recognizer(monkeypatch, [])
    with client.websocket_connect("/api/v1/asr/ws") as ws:
        ws.send_json({"action": "start", "model": "paraformer-realtime-v2",
                      "format": "pcm", "sample_rate": 16000})
        ws.receive_json()
        ws.send_json({"action": "cancel"})
        msg = ws.receive_json()
    assert msg["code"] == "cancelled"
