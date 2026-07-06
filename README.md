# DashScope ASR

基于 DashScope 的自动语音识别服务，与 TTS 项目对称。提供 HTTP 文件上传识别、WebSocket 实时流式识别与 CLI。

## 安装

```bash
pip install -r requirements-dev.txt
export DASHSCOPE_API_KEY=你的密钥   # Windows: 设系统环境变量 DASHSCOPE_API_KEY
```

## 启动服务

```bash
python -m api.main
# 监听 http://0.0.0.0:8000
```

## HTTP 文件上传

```bash
curl -X POST http://localhost:8000/api/v1/asr \
  -F file=@hello.wav \
  -F model=paraformer-realtime-v2 \
  -F format=wav \
  -F sample_rate=16000
```

返回：`{"text": "...", "sentences": [...], "duration_ms": ...}`

## WebSocket 实时流式

1. 连接 `ws://localhost:8000/api/v1/asr/ws`
2. 发 `{"action":"start","model":"paraformer-realtime-v2","format":"pcm","sample_rate":16000}` → 收 `{"type":"ready"}`
3. 发二进制 PCM 帧 → 收 `partial` / `sentence`
4. 发 `{"action":"finish"}` → 收 `{"type":"done","duration_ms":...}`
5. 或发 `{"action":"cancel"}` 中断

错误码：`invalid_start` / `not_started` / `cancelled` / `internal`

## CLI

```bash
# 文件识别
python -m cli.asr --file hello.wav --format wav --sample-rate 16000
python -m cli.asr --file hello.wav --output result.json

# 流式（文件）
python -m cli.asr --stream --file hello.pcm --format pcm --sample-rate 16000

# 流式（麦克风，需 pip install sounddevice numpy）
python -m cli.asr --stream --microphone --format pcm --sample-rate 16000

# 说话人分离
python -m cli.asr --file meeting.wav --enable-diarization
```

## 测试

```bash
pytest -q -p no:cacheprovider
```

## 支持组合

| model | sample_rate |
|---|---|
| paraformer-realtime-v2 | 16000 |
| paraformer-realtime-8k-v2 | 8000 |

格式：pcm / wav / mp3。可在 `config.yaml` 调整。
