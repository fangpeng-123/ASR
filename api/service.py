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
