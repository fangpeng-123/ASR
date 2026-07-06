import asyncio
from typing import AsyncIterator, Optional

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from api.config import AppConfig, get_api_key


class _Callback(RecognitionCallback):
    """SDK 回调在 worker 线程触发；只把结果丢进 asyncio.Queue。"""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self._loop = loop
        self._queue = queue
        self._last_end_time = 0

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if sentence is None:
            return
        items = sentence if isinstance(sentence, list) else [sentence]
        for s in items:
            is_end = RecognitionResult.is_sentence_end(s)
            end_time = s.get("end_time")
            if end_time:
                self._last_end_time = max(self._last_end_time, int(end_time))
            self._put({
                "type": "sentence" if is_end else "partial",
                "text": s.get("text", ""),
                "begin_time": s.get("begin_time"),
                "end_time": end_time,
                "speaker": (str(s["speaker_id"]) if "speaker_id" in s else None),
            })

    def on_error(self, result: RecognitionResult) -> None:
        self._put({"type": "error", "code": "internal",
                   "message": getattr(result, "message", None) or "recognition error"})

    def on_complete(self) -> None:
        self._put({"type": "done", "duration_ms": self._last_end_time})

    def on_close(self) -> None:
        self._put({"type": "closed"})

    def _put(self, item: dict) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, item)


class RealtimeRecognizer:
    def __init__(self, config: AppConfig, model: str, format: str,
                 sample_rate: int, enable_diarization: bool = False,
                 loop: Optional[asyncio.AbstractEventLoop] = None):
        self._sample_rate = sample_rate
        self._frame_ms = config.frame_ms
        self._loop = loop or asyncio.get_event_loop()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._callback = _Callback(self._loop, self._queue)
        dashscope.api_key = get_api_key()
        self._recognition = Recognition(
            model=model, callback=self._callback,
            format=format, sample_rate=sample_rate,
        )
        self._kwargs = {"diarization_enabled": True} if enable_diarization else {}
        self._leftover = b""
        self._running = False

    def start(self) -> None:
        self._recognition.start(**self._kwargs)
        self._running = True

    def _frame_bytes(self) -> int:
        # 16-bit mono: 每帧字节数 = sample_rate * 2 * (frame_ms/1000)，并对齐到偶数
        size = int(self._sample_rate * 2 * (self._frame_ms / 1000))
        size -= size % 2
        return max(2, size)

    def send_audio_chunk(self, data: bytes) -> None:
        frame = self._frame_bytes()
        data = self._leftover + data
        # 只保留整样本（偶数长度），奇数尾巴留到下次
        if len(data) % 2:
            self._leftover = data[-1:]
            data = data[:-1]
        else:
            self._leftover = b""
        for i in range(0, len(data), frame):
            chunk = data[i:i + frame]
            if chunk:
                self._recognition.send_audio_frame(chunk)

    def stop(self) -> None:
        self._running = False
        self._recognition.stop()

    def cancel(self) -> None:
        # SDK 无 cancel：用 stop() 优雅停止，丢弃后续结果。
        self._running = False
        try:
            self._recognition.stop()
        except Exception:
            pass

    async def results(self) -> AsyncIterator[dict]:
        while True:
            item = await self._queue.get()
            yield item
            if item.get("type") in ("done", "error", "closed"):
                break
