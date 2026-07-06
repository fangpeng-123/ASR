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
