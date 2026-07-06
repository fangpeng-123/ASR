import os
import pytest


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """测试默认提供假 key，避免误用真实密钥。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
