## ADDED Requirements

### Requirement: CLI 支持文件上传识别模式
系统 SHALL 提供命令行入口 `python -m cli.asr --file <path>`，将本地音频文件提交到 `POST /api/v1/asr` 并输出识别结果。

#### Scenario: 识别本地文件并输出到控制台
- **WHEN** 用户执行 `python -m cli.asr --file hello.wav`
- **THEN** CLI 将识别文本打印到标准输出

#### Scenario: 识别本地文件并保存 JSON 结果
- **WHEN** 用户执行 `python -m cli.asr --file hello.wav --output result.json`
- **THEN** CLI 将完整响应以 JSON 格式写入 `result.json`

#### Scenario: 指定模型与采样率
- **WHEN** 用户执行 `python -m cli.asr --file hello.wav --model paraformer-realtime-8k-v2 --sample-rate 16000`
- **THEN** CLI 在请求中携带对应参数

### Requirement: CLI 支持实时流式识别模式
系统 SHALL 提供 `--stream` 参数，通过 WebSocket 连接 `/api/v1/asr/ws` 并推送音频数据，实时显示识别增量。

#### Scenario: 从文件实时识别
- **WHEN** 用户执行 `python -m cli.asr --stream --file audio.pcm --format pcm --sample-rate 16000`
- **THEN** CLI 按固定块大小读取文件并推送，实时打印 `partial` 与 `sentence` 结果

#### Scenario: 从麦克风实时识别
- **WHEN** 用户执行 `python -m cli.asr --stream --microphone --format pcm --sample-rate 16000`
- **THEN** CLI 从默认麦克风采集音频并推送（若未安装录音依赖则给出明确提示）

### Requirement: CLI 提供清晰的参数校验与错误提示
系统 SHALL 在参数缺失或冲突时给出明确错误信息，并在 API 连接失败时提示用户启动服务。

#### Scenario: 缺少输入源
- **WHEN** 用户执行 `python -m cli.asr` 且未指定 `--file` 或 `--stream`
- **THEN** CLI 打印用法并退出，返回非零状态码

#### Scenario: 服务未启动
- **WHEN** CLI 无法连接到 `http://localhost:8000`
- **THEN** CLI 提示“请先启动 ASR 服务: python -m api.main”
