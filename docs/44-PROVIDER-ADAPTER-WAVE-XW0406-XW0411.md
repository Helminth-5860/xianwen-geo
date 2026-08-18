# XW-0406~XW-0411 Provider Adapter Wave

## Scope

本 Wave 一次实现六个真实 GEO Detection Adapter，但每个 XW 仍是独立验收单元：

- XW-0406 通义千问（qwen）
- XW-0407 腾讯混元（hunyuan）
- XW-0408 百度文心（wenxin）
- XW-0409 Kimi（kimi）
- XW-0410 智谱 GLM（glm）
- XW-0411 讯飞星火（spark）

本 Wave 不实现 Detection Job、队列、并发信号量、Worker 重试、引用抽取、评分或内容生成。

## Shared architecture

六个 Provider 均通过各自官方 OpenAI-compatible Chat Completions/兼容 HTTP 接口接入，因此复用一个受限的 `OpenAICompatibleDetectionAdapter`：

- 固定官方 HTTPS origin；
- Bearer credential 来自 XW-0403 `DatabaseCredentialResolver`；
- `provider_model_id` 来自 XW-0402 runtime config；
- 单次非流式调用；
- Adapter 内不重试；
- `trust_env=false`；
- 禁止 redirect；
- timeout 由 runtime snapshot 控制；
- 仅保留最终文本、token usage、finish reason、safe request id 和白名单 metadata；
- 不保留 raw Provider JSON、reasoning_content、Authorization 或 credential plaintext。

共享 HTTP wire contract 不代表六个 XW 被批量验收。每个 Provider 仍分别执行同一 contract test matrix。

## Frozen provider contracts

| XW | Provider | Internal key | Fixed base URL | Path | Auth |
|---|---|---|---|---|---|
| XW-0406 | 阿里云百炼 / Qwen | `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `/chat/completions` | Bearer API Key |
| XW-0407 | 腾讯混元 | `hunyuan` | `https://api.hunyuan.cloud.tencent.com/v1` | `/chat/completions` | Bearer API Key |
| XW-0408 | 百度千帆 / 文心 | `wenxin` | `https://qianfan.baidubce.com/v2` | `/chat/completions` | Bearer API Key |
| XW-0409 | Kimi | `kimi` | `https://api.moonshot.cn/v1` | `/chat/completions` | Bearer API Key |
| XW-0410 | 智谱 GLM | `glm` | `https://open.bigmodel.cn/api/paas/v4` | `/chat/completions` | Bearer API Key |
| XW-0411 | 讯飞星火 | `spark` | `https://spark-api-open.xf-yun.com/v1` | `/chat/completions` | Bearer APIPassword |

Qwen 当前官方文档推荐北京业务空间专属域名；旧 `dashscope.aliyuncs.com` 仍受支持。本 Wave 为保持固定可信 origin、避免引入新的 arbitrary base URL 配置，冻结现有官方北京兼容域名。后续若切换 Workspace 专属域名，应作为独立配置设计变更评审。

## Request contract

标准请求：

```json
{
  "model": "<runtime provider_model_id>",
  "messages": [
    {"role": "system", "content": "<neutral system prompt>"},
    {"role": "user", "content": "<question>"}
  ],
  "stream": false,
  "temperature": 0.2,
  "max_tokens": 256
}
```

`max_tokens` 仅在 request payload 指定时发送。

本 Wave 不发送 Provider-specific thinking/reasoning 开关，也不启用 tools、联网增强、搜索插件或 Function Calling。

## Thinking / reasoning

不同 Provider 的 thinking/reasoning 语义并不一致，因此共享 Adapter 不强制统一控制。

- 不请求 reasoning output；
- Provider 如返回 `reasoning_content`，Adapter 不持久化、不写 safe metadata；
- `provider_model_id` 由管理员选择适合当前 Detection 场景的真实 Provider 模型；
- thinking 模式的独立 Provider-specific 优化不属于本 Wave。

## Web search / citations

当前六条直接 Chat Completions 路径均不在本 Wave 内启用 provider tools/search。

因此统一 truthfulness 规则：

- `web_search_requested=false` → used=false, degraded=false；
- `web_search_requested=true` → used=false, degraded=true；
- citations 为空；
- 不虚构 URL、引用或“已联网”声明。

后续 XW-0415 负责统一引用抽取/安全边界。

## Response contract

标准 OpenAI-compatible 非流式响应抽取：

- `choices[0].message.content`
- `choices[0].finish_reason`
- `usage.prompt_tokens`
- `usage.completion_tokens`
- `usage.total_tokens`
- safe `id`
- safe `model`
- optional safe `system_fingerprint`

讯飞星火官方非流式响应存在兼容差异：

- 顶层 `code==0` 才是业务成功；
- request id 优先使用 `id`，否则使用 safe `sid`；
- 响应可能不返回 `model`，此时使用本次已冻结 request 的 `provider_model_id`；
- 非零业务 code fail closed。

## Error mapping

HTTP 边界统一归一化：

- 400/422 → INVALID_REQUEST
- 401 → AUTHENTICATION
- 402 → QUOTA_EXHAUSTED
- 403 → PERMISSION
- 404 → MODEL_UNAVAILABLE
- 408/504 → TIMEOUT
- 429 → RATE_LIMIT
- 500 → PROVIDER_INTERNAL
- 502/503/other 5xx → TEMPORARY_PROVIDER_FAILURE
- timeout/network transport → TIMEOUT/NETWORK
- malformed 2xx response → RESPONSE_PARSE

讯飞星火额外安全映射：

- 10013/10014/10019 → CONTENT_POLICY
- 10007/11201/11202/11203 → RATE_LIMIT
- 11200 → PERMISSION
- 10907 → INVALID_REQUEST
- 其他非零业务码 → PERMANENT_PROVIDER_FAILURE

Provider raw error body/message 不进入 public error、DB 或日志。

## 12-item acceptance matrix

以下 12 项必须对六个 Provider 分别产生测试实例/证据：

1. 正常中文问题；
2. 联网能力 truthfulness；
3. citation 不伪造；
4. timeout；
5. 429；
6. invalid key / 401；
7. Provider 5xx；
8. request deterministic / Adapter no internal retry；
9. token usage；
10. raw response / reasoning sanitization；
11. runtime max_concurrency contract snapshot（实际信号量归 XW-0413）；
12. paused model blocks new resolution。

共享 pytest parametrization 会为每个 Provider 生成独立 test case，而不是用一个 Provider 代表全部。

## Safe smoke

新增通用命令：

```bash
python manage.py smoke_provider_detection --model-key qwen
python manage.py smoke_provider_detection --model-key hunyuan
python manage.py smoke_provider_detection --model-key wenxin
python manage.py smoke_provider_detection --model-key kimi
python manage.py smoke_provider_detection --model-key glm
python manage.py smoke_provider_detection --model-key spark
```

只输出：

- model
- finish reason
- token counts
- latency
- answer length
- citation count
- web_search_used
- degraded
- provider_request_id

不输出 key、Authorization、prompt、answer body、raw JSON 或 reasoning。

真实 Provider smoke 属 Deployment Acceptance，不作为 CI/merge 硬阻塞。

## Deployment impact

- Environment variables：NONE
- Django migrations：NONE
- Celery queues/workers：NONE
- Ports：NONE
- PostgreSQL schema：UNCHANGED
- Redis：UNCHANGED
- New dependencies：NONE
- Scheduled tasks：NONE
- Docker/startup topology：UNCHANGED
- Required egress：
  - `dashscope.aliyuncs.com:443`
  - `api.hunyuan.cloud.tencent.com:443`
  - `qianfan.baidubce.com:443`
  - `api.moonshot.cn:443`
  - `open.bigmodel.cn:443`
  - `spark-api-open.xf-yun.com:443`
- Required operational data：各 Provider 的 encrypted staging credential + valid runtime `provider_model_id`
