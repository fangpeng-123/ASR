## ADDED Requirements

### Requirement: HTTP 接口接收本地音频文件并返回转写结果
系统 SHALL 提供 `POST /api/v1/asr` 接口，使用 `multipart/form-data` 接收本地音频文件，并返回完整识别文本与句子列表。

#### Scenario: 上传有效音频文件
- **WHEN** 客户端以 `multipart/form-data` 上传音频文件，并附带 `model`、`format`、`sample_rate` 参数
- **THEN** 服务端返回 HTTP 200，响应体包含 `text`、`sentences`、`duration_ms`

#### Scenario: 缺少音频文件
- **WHEN** 客户端请求中未包含 `file` 字段
- **THEN** 服务端返回 HTTP 422，提示缺少音频文件

#### Scenario: 不支持的模型
- **WHEN** 客户端指定了服务端不支持的 `model`
- **THEN** 服务端返回 HTTP 400，提示不支持的模型

### Requirement: 转写结果包含句子级时间戳与结束标记
系统 SHALL 在转写结果中返回每个句子的文本、开始时间、结束时间以及是否为句尾。

#### Scenario: 单句音频识别
- **WHEN** 上传一段仅包含一句话的音频
- **THEN** 返回的 `sentences` 列表包含一条记录，且 `is_final` 为 `true`

#### Scenario: 多句音频识别
- **WHEN** 上传一段包含多句话的音频
- **THEN** 返回的 `sentences` 列表包含多条记录，每条记录均包含 `begin_time`、`end_time`、`text`、`is_final`

### Requirement: 支持常用音频格式与采样率
系统 SHALL 支持 `pcm`、`wav`、`mp3` 格式，并支持 8000、16000、24000、44100、48000 Hz 采样率；对于不支持的组合返回明确错误。

#### Scenario: 提交不支持的格式
- **WHEN** 客户端指定 `format=ogg`
- **THEN** 服务端返回 HTTP 400，提示不支持的音频格式
