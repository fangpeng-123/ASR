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
