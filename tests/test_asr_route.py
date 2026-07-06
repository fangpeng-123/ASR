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
