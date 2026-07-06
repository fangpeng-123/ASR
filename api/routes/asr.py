import asyncio
import json
import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.status import WS_1008_POLICY_VIOLATION

from api.config import AppConfig
from api.models import ASRUploadResponse, WSControlMessage, WSResultMessage
from api.realtime_recognizer import RealtimeRecognizer
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


async def _send_error(ws: WebSocket, code: str, message: str) -> None:
    await ws.send_json(WSResultMessage(type="error", code=code, message=message).model_dump())


@router.websocket("/asr/ws")
async def asr_ws(websocket: WebSocket):
    await websocket.accept()
    cfg: AppConfig = websocket.app.state.config

    # 1) 等 start 帧；先收到二进制 → not_started
    first = await websocket.receive()
    if first.get("bytes") is not None:
        await _send_error(websocket, "not_started", "send start control frame first")
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return
    try:
        ctrl = WSControlMessage(**json.loads(first["text"]))
    except Exception:
        await _send_error(websocket, "invalid_start", "invalid start frame")
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return
    if ctrl.action != "start" or not ctrl.model or not ctrl.format or not ctrl.sample_rate:
        await _send_error(websocket, "invalid_start", "start requires model/format/sample_rate")
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return
    if not cfg.is_supported(ctrl.model, ctrl.format, ctrl.sample_rate):
        await _send_error(websocket, "invalid_start", "unsupported model/format/sample_rate")
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return

    loop = asyncio.get_running_loop()
    recognizer = RealtimeRecognizer(
        cfg, ctrl.model, ctrl.format, ctrl.sample_rate,
        ctrl.enable_diarization, loop=loop)
    try:
        recognizer.start()
    except Exception as e:
        await _send_error(websocket, "internal", str(e))
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return
    await websocket.send_json(WSResultMessage(type="ready").model_dump())

    async def forward_results():
        async for item in recognizer.results():
            await websocket.send_json(WSResultMessage(**item).model_dump())
            if item.get("type") in ("done", "error"):
                return

    async def receive_loop():
        while True:
            msg = await websocket.receive()
            if msg.get("bytes") is not None:
                recognizer.send_audio_chunk(msg["bytes"])
            elif msg.get("text") is not None:
                c = WSControlMessage(**json.loads(msg["text"]))
                if c.action == "finish":
                    recognizer.stop()
                    return "finish"
                if c.action == "cancel":
                    recognizer.cancel()
                    await _send_error(websocket, "cancelled", "session cancelled")
                    return "cancel"
            else:
                # websocket.disconnect — client went away without finish/cancel
                return "disconnect"

    fwd = asyncio.create_task(forward_results())
    rcv = asyncio.create_task(receive_loop())
    try:
        await asyncio.wait({fwd, rcv}, return_when=asyncio.FIRST_COMPLETED)
        if rcv.done() and not fwd.done():
            try:
                reason = rcv.result()
            except WebSocketDisconnect:
                reason = "disconnect"
            if reason == "finish":
                # 让 forward_results 把残余结果（含 done）发完
                try:
                    await asyncio.wait_for(fwd, timeout=5.0)
                except asyncio.TimeoutError:
                    fwd.cancel()
                except Exception:
                    pass
            else:
                fwd.cancel()
        elif fwd.done() and not rcv.done():
            rcv.cancel()
    except WebSocketDisconnect:
        recognizer.cancel()
    finally:
        for t in (fwd, rcv):
            if not t.done():
                t.cancel()
        await websocket.close()
