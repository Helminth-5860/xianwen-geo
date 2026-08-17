# XW-0405 — 真实检测适配器：豆包

## 1. 范围

XW-0405 只实现豆包的 `geo_detection` 单次真实调用 Adapter 和独立合约验收。

本任务不实现：

- GEO 检测 Job、快照或额度冻结；
- 队列、信号量、用户并发、Worker retry 或取消；
- 引用 URL 抽取、SSRF 核验或评分；
- 豆包图片生成；
- 通义、混元、文心、Kimi、GLM、星火 Adapter。

这些能力仍分别属于 XW-0406 及 XW-0412～XW-0415。

## 2. 当前官方火山方舟 API 边界

实现依据 2026-08-17 的火山方舟官方文档：

- Base URL：`https://ark.cn-beijing.volces.com/api/v3`
- 检测调用：`POST /responses`
- 鉴权：`Authorization: Bearer <API key>`
- 豆包实际 model/endpoint ID 由调用方在 `model` 字段传入
- Responses API 支持 `instructions`、`input`、`thinking`、`temperature`、
  `max_output_tokens`、`store` 和 token usage
- Responses API 可配置 Web Search 工具，但工具授权、引用返回和费用属于独立能力

因此：

- Adapter 不硬编码豆包 model ID，实际 ID 来自 XW-0402 `provider_model_id`
- Provider origin/path 固定，不允许后台提供任意 URL
- 本检测路径不发送 `tools`，`web_search_requested=true` 时如实返回
  `web_search_used=false`、`degraded=true` 和空 citations
- XW-0415 再负责正文 URL、来源提取及安全核验

官方参考：

- https://www.volcengine.com/docs/82379/1795150
- https://www.volcengine.com/docs/82379/1958524
- https://www.volcengine.com/docs/82379/1783703
- https://www.volcengine.com/docs/82379/1299023

## 3. 统一契约

复用 XW-0404 已建立的 `DetectionPayload`：

- `provider_model_id`
- `system_prompt`
- `user_question`
- `web_search_requested`
- `temperature`
- `max_output_tokens`

映射到 Responses API：

- `system_prompt` → `instructions`
- `user_question` → `input`
- `provider_model_id` → `model`
- `max_output_tokens` 保持相同语义
- `stream=false`、`store=false`、`thinking.type=disabled`

Adapter 不发送 `AIAdapterRequest.metadata`，不使用 `previous_response_id`，每个检测点保持
独立会话。

`DetectionOutput` 返回 Provider 实际 model ID、最终回答文本、联网请求/实际/降级状态和引用。
当前路径 citations 固定为空。完整 Provider JSON 和 reasoning item 不进入业务 output。

## 4. Credential

真实密钥只经 XW-0403 `DatabaseCredentialResolver` 解密后临时注入
`AdapterCredential`。

Adapter：

- 不读取 `DOUBAO_API_KEY`、`ARK_API_KEY` 或 `VOLCENGINE_API_KEY`
- 不把 key 放入 payload、repr、response、metadata 或 log
- 缺失或解密失败时 fail closed
- 不提供 plaintext reveal

## 5. Runtime config

XW-0402 是 enable/pause、provider model ID、timeout、retry、concurrency 和 cost 的权威来源。
调用方先通过 `resolve_detection_adapter()` 获得不可变 runtime snapshot 和 Adapter。

Adapter 单次调用只消费 `AIAdapterRequest.timeout_seconds`，不自行重试。

## 6. HTTP 边界

- 固定 HTTPS origin 和 `/responses` path
- Bearer API Key
- `Content-Type: application/json`
- 不跟随重定向
- 不使用宿主 proxy 环境
- 单次 timeout
- 非流式、`store=false`
- 不发送用户 ID 或内部 metadata

## 7. Thinking、Web Search 与引用

豆包 Seed 2.0 可启用深度思考。GEO 检测路径固定发送 `thinking.type=disabled`，避免保存或暴露
reasoning。即使响应中意外带有 reasoning item，Adapter 也只提取唯一 assistant message 的
`output_text`。

火山方舟 Responses API 支持 Web Search 工具，但当前 Adapter 未冻结插件授权、引用结构和额外
费用语义，因此不发送工具。它不会根据请求意图谎报联网，也不会从回答文字中虚构 citations。

## 8. 响应、usage 和安全 metadata

只接受：

- HTTP 200
- 小于等于 2 MB 的 JSON
- `object=response` 且 `status=completed`
- 唯一 assistant message 和非空 `output_text`
- 非负整数 `input_tokens`、`output_tokens` 和 `total_tokens`
- 有效 Provider model ID

归一化：

- `id` → provider request id
- `output[].content[].text` → raw detection text
- usage → `AIUsage`
- elapsed monotonic time → `AIAdapterTiming`
- completed → `AIFinishReason.STOP`
- provider model、service tier、cached/reasoning token 计数 → bounded safe metadata

完整 raw response、reasoning summary、prompt、Authorization 和 API key 均不保留。

## 9. 错误映射

- 400 / 422 → invalid request
- 401 → authentication
- 402 → quota exhausted
- 403 → permission
- 404 → model unavailable
- 408 / 504 → timeout
- 429 → rate limit
- 500 → provider internal
- 502 / 503 / 其他 5xx → temporary provider failure
- transport timeout → timeout
- network/HTTP transport → network
- 其他 4xx → permanent provider failure
- 非法 JSON、状态、输出或 usage → response parse

Provider 原始错误 body 不进入异常。Adapter 不自行重试。

## 10. 12 项适配器验收边界

1. 正常中文问题：真实 Responses API 合同测试。
2. 联网能力：Provider 有独立工具能力，但当前路径未启用；如实降级，不冒充联网。
3. 引用解析：当前路径不返回 citations；XW-0415 负责来源提取和安全核验。
4. 超时：HTTP/transport timeout 映射 `TIMEOUT`，可重试。
5. 429：映射 `RATE_LIMIT`，可重试。
6. 无效密钥：401 映射 `AUTHENTICATION`，不泄露 body。
7. 供应商 5xx：500/502/503 映射可重试类别。
8. 重试幂等：Adapter 单次调用、无内部 retry；相同冻结 request 生成相同 body；真正调度属于
   XW-0414。
9. Token 和成本：Adapter 归一化真实 token usage；成本持久化/结算属于后续 ModelCall/Worker。
10. 原始回答脱敏存储：Adapter 只交付最终回答和白名单 metadata，不保留 raw JSON；持久化属于
    XW-0414。
11. 并发限制：runtime snapshot 已暴露 `max_concurrency`；真正信号量属于 XW-0413。
12. 暂停：XW-0402 `resolve_detection_adapter()` 在新调用前 fail closed；Worker 中途策略属于
    XW-0414。

本任务只声明 Adapter-level 合同证据，不提前宣称 XW-0412～XW-0415 完成。

## 11. 真实 Smoke

```text
python manage.py smoke_doubao_detection
```

命令使用固定非敏感中文问题，并通过 runtime snapshot 和数据库 credential resolver 真实调用。
只打印 provider/model、finish reason、token、latency、回答字符数、引用数、联网状态和安全 request
ID；不打印 API key、Authorization、raw JSON、完整 prompt 或回答正文。

Staging smoke 前必须：

1. XW-0403 已部署且配置独立 `FIELD_ENCRYPTION_MASTER_KEY`
2. 豆包 staging credential 已通过安全后台保存
3. `doubao` runtime config 已填写当前有效 `provider_model_id`
4. 模型 enabled 且未 paused
5. 运行环境允许到 `ark.cn-beijing.volces.com:443` 的 HTTPS egress

## 12. Impact Matrix

- 必须测试：豆包 request/response/error/usage/security/registry/runtime/smoke 合同
- 影响域回归：XW-0401 unified contract、XW-0402 runtime、XW-0403 credentials、XW-0404 DeepSeek
- Public API/OpenAPI/frontend：无变化
- 数据库/migrations：无变化
- Celery/quota/Detection Job：无变化
- Docker/CI：复用 `docker-compose.ai-key-management.yml`，仅加入新 deterministic test

## 13. DEPLOYMENT LINE IMPACT

- Environment variables：NONE（复用 XW-0403 已有变量）
- Django migrations：NONE
- Celery queues/workers：NONE
- Ports：NONE
- PostgreSQL：schema unchanged；需已有豆包 staging credential/runtime data
- Redis：UNCHANGED
- External dependencies：NONE（复用 XW-0404 的 `httpx==0.28.1`）
- Scheduled tasks：NONE
- Docker/startup：topology unchanged；部署包含新代码的镜像
- Provider credential：需要火山方舟 API key，由数据库安全保存，不进入环境变量或 CLI
- Egress：`ark.cn-beijing.volces.com:443`
- Rollout：部署代码 → 配置/核对 runtime model ID → 保存 staging credential → 保持 disabled →
  真实 smoke PASS → 再启用
- Staging smoke：运行 `smoke_doubao_detection`，只核对安全摘要和日志无敏感内容
