# XW-0404 — 真实检测适配器：DeepSeek

## 1. 范围

XW-0404 只实现 DeepSeek 的 `geo_detection` 单次真实调用 Adapter 和独立合约验收。

本任务不实现：

- GEO 检测 Job／快照／额度冻结；
- 队列、信号量或用户并发；
- Worker retry 调度和取消；
- 引用 URL 抽取／SSRF 核验；
- 程序评分或 DeepSeek 语义评分；
- DeepSeek 内容生成；
- 豆包、通义、混元、文心、Kimi、GLM、星火 Adapter。

这些能力仍分别属于 XW-0412 及后续任务。

## 2. 当前官方 DeepSeek API 边界

实现依据 2026-08-17 的 DeepSeek 官方 API 文档：

- OpenAI-compatible base URL：`https://api.deepseek.com`
- 检测调用：`POST /chat/completions`
- 当前 Chat Completions model ID：`deepseek-v4-flash`、`deepseek-v4-pro`
- 旧 `deepseek-chat` / `deepseek-reasoner` 已在 2026-07-24 后退役
- V4 Chat Completions 支持 `thinking`；本检测 Adapter 固定 `thinking.type=disabled`
- 当前直接 Chat Completions 合同未提供原生 web-search 请求字段或结构化 citation 字段

因此：

- Adapter 不硬编码 provider model ID，实际 model ID 来自 XW-0402 `provider_model_id`
- Provider endpoint 固定，不允许后台提供任意 URL
- `web_search_requested=true` 时不伪造联网；本 Adapter 返回
  `web_search_used=false`、`degraded=true`、空 citations
- XW-0415 再负责正文 URL / 来源提取和安全核验

官方参考：

- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/quick_start/error_codes/
- https://api-docs.deepseek.com/news/news260424/

## 3. 契约

`DetectionPayload` 冻结：

- `provider_model_id`
- `system_prompt`
- `user_question`
- `web_search_requested`
- `temperature`
- `max_output_tokens`

Adapter 只发送 system + user 两条消息，不发送 `AIAdapterRequest.metadata`。

`DetectionOutput` 返回：

- Provider 实际返回的 model ID
- 原始最终回答文本
- citations（DeepSeek 当前直接合同固定为空）
- `web_search_requested`
- `web_search_used`
- `degraded`

完整 provider JSON、`reasoning_content`、Authorization、API Key 不进入业务 output。

## 4. Credential

真实密钥只经 XW-0403 `DatabaseCredentialResolver` 解密后临时注入 `AdapterCredential`。

Adapter：

- 不读取环境变量里的 `DEEPSEEK_API_KEY`
- 不把 key 放入 request payload / repr / response / metadata / log
- 缺失或解密失败时 fail closed
- 不提供 plaintext reveal

## 5. Runtime config

XW-0402 继续是运行配置权威来源。

Adapter 不拥有：

- enable / pause
- provider model ID
- timeout
- retry count
- concurrency
- cost

调用方先通过 `resolve_detection_adapter()` 获取不可变 runtime snapshot 和 Adapter。

Adapter 单次调用只消费 `AIAdapterRequest.timeout_seconds`，不自行重试。

## 6. 请求

HTTP：

- 固定 HTTPS base URL
- `Authorization: Bearer <credential>`
- `Content-Type: application/json`
- 不跟随重定向
- 不使用宿主 proxy 环境
- 单次 timeout
- `stream=false`
- `thinking.type=disabled`

不发送用户隐私 `user_id`。

## 7. 响应和安全

只接受成功的单 choice Chat Completion。

归一化：

- `id` → provider request id
- `message.content` → raw detection text
- token usage → `AIUsage`
- latency → `AIAdapterTiming`
- finish reason → `AIFinishReason`
- model/system fingerprint/cache token 仅进入 bounded sanitized metadata

`reasoning_content` 明确丢弃，不保存、不返回。

Provider 原始错误 body 不进入异常、日志或响应。

## 8. 错误映射

- 400 / 422 → invalid request
- 401 → authentication
- 402 → quota exhausted
- 403 → permission
- 404 → model unavailable
- 429 → rate limit
- 500 → provider internal
- 503 → temporary provider failure
- transport timeout → timeout
- network failure → network
- 非法 JSON / schema → response parse
- `insufficient_system_resource` → retryable provider internal

Adapter 不自行重试。

## 9. 12 项适配器验收边界

1. 正常中文问题：真实 Chat Completions 合同测试。
2. 联网能力：当前 direct Chat Completions 不声明原生 web search；Adapter 如实降级，不冒充联网。
3. 引用解析：当前 direct provider citation 为空；XW-0415 才做正文 URL / 来源提取。
4. 超时：映射 `TIMEOUT`，可重试。
5. 429：映射 `RATE_LIMIT`，可重试。
6. 无效密钥：401 映射 `AUTHENTICATION`，不泄露 provider body。
7. 供应商 5xx：500/503 映射可重试类别。
8. 重试幂等：Adapter 单次调用、无内部 retry；相同冻结 request 产生相同 provider body。
   真正 retry schedule 属于 XW-0414。
9. Token 和成本：Adapter 归一化 token usage；成本持久化/结算仍属于后续 ModelCall/Worker。
10. 原始回答脱敏存储：Adapter 只交付 raw final text 和白名单 metadata，不保留 provider raw JSON；
    ModelCall 持久化属于 XW-0414。
11. 并发限制：runtime snapshot 已暴露 `max_concurrency`；真正模型信号量属于 XW-0413。
12. 暂停：XW-0402 `resolve_detection_adapter()` 在新调用前 fail closed；
    Worker 中途暂停策略属于 XW-0414。

XW-0404 只声明 Adapter-level 合约通过，不提前宣称 XW-0412～XW-0415 的系统能力完成。

## 10. 真实 Smoke

新增：

```text
python manage.py smoke_deepseek_detection
```

该命令：

- 使用当前 runtime config
- 使用 XW-0403 安全 credential resolver
- 真实调用 DeepSeek
- 只打印 model、finish reason、token、latency、回答字符数等安全摘要
- 不打印 API Key、Authorization、原始 provider JSON 或回答正文

Staging smoke 前必须：

1. XW-0403 已部署并配置独立 `FIELD_ENCRYPTION_MASTER_KEY`
2. DeepSeek credential 已通过安全后台保存
3. `deepseek` runtime config 已设置当前有效 `provider_model_id`
4. 模型 enabled 且未 paused

## 11. 部署影响

- Environment variables：NONE
- Django migrations：NONE
- PostgreSQL schema：UNCHANGED
- Redis：UNCHANGED
- Celery queues/workers：UNCHANGED
- Ports：NONE
- Scheduled tasks：NONE
- External dependency：新增 `httpx==0.28.1`
- Docker/startup topology：UNCHANGED，需重建镜像以包含 HTTP client dependency

上线后先在 Staging 做真实 DeepSeek smoke，再决定是否在 Production 启用该模型。
