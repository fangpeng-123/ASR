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
