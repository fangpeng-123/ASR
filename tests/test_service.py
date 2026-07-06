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
