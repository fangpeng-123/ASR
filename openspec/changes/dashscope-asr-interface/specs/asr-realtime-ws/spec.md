## ADDED Requirements

### Requirement: WebSocket 实时识别会话通过控制帧启动
系统 SHALL 在 WebSocket 连接建立后等待客户端发送 `start` 控制帧，帧中携带 `model`、`format`、`sample_rate` 等参数，服务端校验通过后返回 `ready`。

#### Scenario: 正常启动实时识别会话
- **WHEN** 客户端发送 `{"action":"start","model":"paraformer-realtime-8k-v2","format":"pcm","sample_rate":16000}`
- **THEN** 服务端返回 `{"type":"ready"}`

#### Scenario: 启动参数无效
- **WHEN** 客户端发送的 `start` 帧缺少 `format` 或 `sample_rate`
- **THEN** 服务端返回 `{"type":"error","code":"invalid_start","message":"..."}` 并关闭连接

### Requirement: 客户端可推送二进制音频帧
系统 SHALL 在会话启动后接收客户端发送的二进制音频帧，并将音频数据送入实时识别器。

#### Scenario: 推送音频帧
- **WHEN** 客户端在 `start` 之后发送二进制音频数据
- **THEN** 服务端持续处理音频，不产生错误

#### Scenario: 未启动会话即推送音频
- **WHEN** 客户端在发送 `start` 之前发送二进制音频数据
- **THEN** 服务端返回 `{"type":"error","code":"not_started","message":"..."}` 并关闭连接

### Requirement: 服务端实时返回识别增量
系统 SHALL 在识别过程中向客户端发送 `partial` 帧表示中间结果，发送 `sentence` 帧表示一个完整句子的识别结果。

#### Scenario: 收到中间识别结果
- **WHEN** SDK 回调返回非句尾中间文本
- **THEN** 服务端发送 `{"type":"partial","text":"..."}`

#### Scenario: 收到完整句子
- **WHEN** SDK 回调返回句尾结果
- **THEN** 服务端发送 `{"type":"sentence","text":"...","begin_time":0,"end_time":1500}`

### Requirement: 客户端可结束或取消会话
系统 SHALL 支持 `finish` 控制帧结束识别并等待最终结果，支持 `cancel` 控制帧立即中断会话。

#### Scenario: 正常结束
- **WHEN** 客户端发送 `{"action":"finish"}`
- **THEN** 服务端冲刷残余音频，等待最终句子结果，发送 `{"type":"done","duration_ms":...}` 后关闭连接

#### Scenario: 取消会话
- **WHEN** 客户端发送 `{"action":"cancel"}`
- **THEN** 服务端立即停止识别，发送 `{"type":"error","code":"cancelled","message":"..."}` 后关闭连接

### Requirement: 服务端对大块音频进行二次切片
系统 SHALL 将客户端发送的任意大小二进制音频帧按 20ms 16bit mono 的字节长度切分为多段后再送入 SDK。

#### Scenario: 客户端发送 100ms 音频块
- **WHEN** 客户端一次性发送 100ms 的 PCM 数据
- **THEN** 服务端内部将其切分为 5 段 20ms 帧依次调用 `send_audio_frame`
