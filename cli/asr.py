import argparse
import json
import sys
from pathlib import Path

import httpx

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


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if not args.file and not args.stream:
        print("用法: python -m cli.asr --file <audio> | --stream [--file <audio> | --microphone]", file=sys.stderr)
        sys.exit(2)
    if args.stream:
        # Task 12 实现
        _die("流式模式尚未实现")
    else:
        if not args.file:
            _die("文件模式需要 --file")
        cmd_file(args)


if __name__ == "__main__":
    main()
