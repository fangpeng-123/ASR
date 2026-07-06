import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
from httpx_ws import aconnect_ws

DEFAULT_URL = "http://localhost:8000"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m cli.asr", description="DashScope ASR CLI")
    p.add_argument("--file", help="本地音频文件路径")
    p.add_argument("--stream", action="store_true", help="实时流式识别")
    p.add_argument("--microphone", action="store_true", help="从麦克风采集（仅 --stream）")
    p.add_argument("--model", default="paraformer-realtime-v2")
    p.add_argument("--format", default="pcm")
    p.add_argument("--sample-rate", type=int, default=16000)
    p.add_argument("--enable-diarization", action="store_true")
    p.add_argument("--output", help="将结果写入 JSON 文件（文件模式）")
    p.add_argument("--base-url", default=DEFAULT_URL)
    return p


def _die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def cmd_file(args: argparse.Namespace) -> None:
    try:
        with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
            with open(args.file, "rb") as f:
                files = {"file": (Path(args.file).name, f)}
                data = {"model": args.model, "format": args.format,
                        "sample_rate": str(args.sample_rate)}
                if args.enable_diarization:
                    data["enable_diarization"] = "true"
                resp = client.post("/api/v1/asr", files=files, data=data)
    except httpx.ConnectError:
        _die("无法连接 ASR 服务，请先启动: python -m api.main")
    if resp.status_code != 200:
        _die(f"ASR 请求失败 {resp.status_code}: {resp.text}")
    result = resp.json()
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(result.get("text", ""))


def _strip_wav_header(data: bytes) -> bytes:
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    idx = 12
    while idx + 8 <= len(data):
        chunk_id = data[idx:idx + 4]
        chunk_size = int.from_bytes(data[idx + 4:idx + 8], "little")
        if chunk_id == b"data":
            return data[idx + 8:idx + 8 + chunk_size]
        idx += 8 + chunk_size
    return data


async def cmd_stream(args: argparse.Namespace) -> None:
    ws_url = args.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/v1/asr/ws"
    try:
        async with aconnect_ws(ws_url) as ws:
            await ws.send_json({
                "action": "start", "model": args.model, "format": args.format,
                "sample_rate": args.sample_rate, "enable_diarization": args.enable_diarization,
            })
            ready = await ws.receive_json()
            if ready.get("type") == "error":
                _die(f"启动失败: {ready}")

            async def sender():
                data = await _read_stream_audio(args)
                chunk = max(2, int(args.sample_rate * 2 * 0.02))  # 20ms
                for i in range(0, len(data), chunk):
                    await ws.send_bytes(data[i:i + chunk])
                    await asyncio.sleep(0.02)
                await ws.send_json({"action": "finish"})

            async def receiver():
                while True:
                    msg = await ws.receive_json()
                    t = msg.get("type")
                    if t == "partial":
                        print(f"\r{msg.get('text', '')}", end="", flush=True)
                    elif t == "sentence":
                        print(f"\r{msg.get('text', '')}", flush=True)
                    elif t == "done":
                        print(flush=True)
                        return
                    elif t == "error":
                        print(f"\n错误: {msg}", file=sys.stderr)
                        return

            await asyncio.gather(sender(), receiver())
    except httpx.ConnectError:
        _die("无法连接 ASR 服务，请先启动: python -m api.main")


async def _read_stream_audio(args: argparse.Namespace) -> bytes:
    if args.microphone:
        try:
            import sounddevice as sd
        except ImportError:
            _die("麦克风需要 sounddevice，请安装: pip install sounddevice numpy")
        import numpy as np
        rec = sd.rec(int(args.sample_rate * 5), samplerate=args.sample_rate,
                     channels=1, dtype="int16")
        sd.wait()
        return rec.tobytes()
    with open(args.file, "rb") as f:
        data = f.read()
    if args.format == "wav":
        data = _strip_wav_header(data)
    return data


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if not args.file and not args.stream:
        print("用法: python -m cli.asr --file <audio> | --stream [--file <audio> | --microphone]", file=sys.stderr)
        sys.exit(2)
    if args.stream:
        asyncio.run(cmd_stream(args))
    else:
        if not args.file:
            _die("文件模式需要 --file")
        cmd_file(args)


if __name__ == "__main__":
    main()
