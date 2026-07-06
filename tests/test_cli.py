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
    from cli.asr import _stream_microphone
    args = type("A", (), {"microphone": True, "sample_rate": 16000, "format": "pcm"})()
    with pytest.raises(SystemExit):
        asyncio.run(_stream_microphone(ws=None, args=args))
    err = capsys.readouterr().err
    assert "sounddevice" in err
