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
