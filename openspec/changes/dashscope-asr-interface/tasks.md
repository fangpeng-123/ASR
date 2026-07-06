## 1. 项目骨架与依赖

- [ ] 1.1 创建 `F:\code\Agent\ASR` 目录结构（`api/`、`cli/`、`tests/`）
- [ ] 1.2 编写 `requirements.txt`，包含 `fastapi`、`uvicorn`、`pydantic`、`pyyaml`、`python-dotenv`、`httpx`、`httpx-ws`、`dashscope`
- [ ] 1.3 编写 `config.yaml` 与 `pytest.ini`

## 2. 配置与模型

- [ ] 2.1 实现 `api/config.py`：加载 YAML、读取 DashScope API Key、定义 `AppConfig`
- [ ] 2.2 实现 `api/models.py`：定义 `ASRUploadResponse`、`ASRSentence`、`WSControlMessage`、`WSResultMessage`

## 3. 非流式识别服务

- [ ] 3.1 实现 `api/service.py`：封装 `recognize_file()`，调用 `Recognition.call(file=...)`
- [ ] 3.2 解析 `RecognitionResult`，生成 `text`、`sentences`、`duration_ms`
- [ ] 3.3 添加临时文件落盘与清理逻辑

## 4. 实时识别器封装

- [ ] 4.1 实现 `api/realtime_recognizer.py`：`RealtimeRecognizer` 类与 `_Callback` 桥接
- [ ] 4.2 实现 `start()` / `send_audio_chunk()` / `stop()` / `cancel()` 生命周期方法
- [ ] 4.3 实现服务端侧 20ms 音频切片逻辑
- [ ] 4.4 通过 `asyncio.Queue` 将 SDK 回调结果转给 WebSocket 协程

## 5. API 路由

- [ ] 5.1 实现 `api/routes/health.py` 健康检查
- [ ] 5.2 实现 `api/routes/asr.py`：`POST /api/v1/asr` 文件上传路由
- [ ] 5.3 实现 `api/routes/asr.py`：`/api/v1/asr/ws` WebSocket 实时识别路由
- [ ] 5.4 实现 `api/main.py` 应用工厂与路由注册

## 6. CLI 客户端

- [ ] 6.1 实现 `cli/asr.py` 参数解析：`--file`、`--stream`、`--microphone`、`--model`、`--format`、`--sample-rate`、`--output`
- [ ] 6.2 实现文件上传模式：调用 `POST /api/v1/asr` 并输出/保存结果
- [ ] 6.3 实现实时流式模式：通过 WebSocket 推送文件或麦克风音频，实时打印识别结果

## 7. 测试

- [ ] 7.1 编写 `tests/test_service.py`：Mock `Recognition` 验证非流式识别结果解析
- [ ] 7.2 编写 `tests/test_asr_route.py`：使用 `TestClient` 验证文件上传路由
- [ ] 7.3 编写 `tests/test_realtime.py`：Mock `RealtimeRecognizer` 验证 WebSocket 协议状态机

## 8. 文档与验证

- [ ] 8.1 编写 `README.md`，包含启动命令、API 示例、CLI 示例
- [ ] 8.2 运行 `pytest -q -p no:cacheprovider` 确保所有测试通过
- [ ] 8.3 手动验证 CLI 文件识别与实时流式识别
