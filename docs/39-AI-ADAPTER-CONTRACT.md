# XW-0401 AI 适配器统一契约

## 范围

XW-0401 在 `apps.ai` 建立内部、可复用的单次模型调用边界，并把已经上线的主体补充、
关键词生成、关键词蒸馏和问题库生成 Mock Provider 接入同一契约。现有业务 API、异步
Job、额度结算、草稿/正式版本和 provenance 行为保持不变。

本任务不实现真实模型调用，不创建模型管理后台、运行配置表或密钥管理能力；这些分别属于
XW-0402、XW-0403 和后续真实适配器任务。

## 统一请求和响应

`AIAdapterRequest` 冻结以下调用事实：

- request/correlation id；
- provider/model 稳定 machine key；
- capability；
- adapter/prompt version；
- 单次调用 timeout；
- 领域专属结构化 payload 和仅供内部追踪的 metadata。

payload 中的主体字段、关键词、问题、文件/网页正文及模型回答始终是不可信数据，不得提升为
system/developer 指令。

`AIAdapterResponse` 返回：

- 与请求一致的 provider/model identity；
- 领域结构化 output；
- 可选 provider request id；
- normalized usage；
- latency；
- normalized finish reason；
- 构造时强制清洗的 bounded provider metadata。

请求 payload 和响应 output 均从 `repr` 排除。完整 raw provider response 不进入业务返回值。

## 错误分类

`AIAdapterError` 使用稳定类别，覆盖 configuration unavailable、authentication、permission、
timeout、rate limit、provider quota、network、temporary/permanent provider failure、invalid
request、content policy、model unavailable、provider internal、response parse、unknown
provider/model、unsupported capability 和 internal adapter failure。

每个错误显式提供：

- `retryable`；
- `configuration_failure`；
- `provider_failure`；
- `schema_failure`。

异常字符串和 `repr` 只含安全稳定信息，不携带 provider 原始错误、正文或 credential。现有四个
业务域继续使用原稳定错误码；兼容层把统一类别映射为原业务错误，不改变 API 可观察语义。

## Model Registry

Registry 是 code-level metadata/adapter registry，键为 provider、model 和 capability。它负责：

- 唯一注册；
- adapter factory lookup；
- provider/model/capability 分层错误；
- Mock 与 unavailable adapter 注册；
- 稳定 descriptor 和 legacy provenance 属性的一致性。

Registry 不保存 enabled、排序、timeout、retry、并发、成本或暂停状态，也不创建数据库表。

## Mock 和 production 边界

共享 Mock 基类提供确定性 success，并统一模拟 timeout、rate-limit、temporary、permanent 和
invalid-response 场景。四个领域保留各自严格输出 Schema 和既有确定性样例。

Mock 仍必须由 local/test 显式配置。Production 继续拒绝 Mock 和尚未实现的 provider；真实
adapter 缺失时仅允许 unavailable 并在任务创建前失败关闭，不自动 fallback。

## Raw response 和日志安全

`sanitize_provider_payload` 在任何保留或记录之前执行递归清洗：

- Authorization、Cookie、API key、token、credential、password 和 secret 脱敏；
- prompt、message、input/output、source text、raw body/response 和 diagnostics 脱敏；
- signed URL 字段完全脱敏，其他 HTTP(S) URL 移除 userinfo、query 和 fragment；
- 深度、元素数、key 长度和字符串长度有界；
- 未知对象不调用其 `repr`，只返回安全占位。

持久化的 provider metrics 使用更严格白名单，只允许非负计数/耗时和 Mock 标识。日志只允许
稳定 identity、request/correlation id、错误类别和已清洗 metadata；不得记录 payload、raw
response、provider exception text 或 secret。

## Timeout、retry 和 credential 边界

Adapter 只执行一次调用，消费请求中的单次 timeout 并分类 retryability；adapter 不自行重试。
现有 Celery durable Job 继续独占 retry schedule、退避、lease/generation、late-worker 防护和
额度 hold 的 consume/release。

`CredentialResolver` / `AdapterCredential` 只定义未来真实 adapter 的非持久化注入边界，并把
secret 从 `repr` 排除。XW-0401 不读取、保存、轮换或展示生产 credential。

## 数据、API 与部署

- Django migrations：NONE；
- PostgreSQL/Redis schema 和使用：UNCHANGED；
- Public API/OpenAPI：UNCHANGED；
- Environment variables：NONE；
- Celery queues/workers/scheduled tasks：UNCHANGED；
- Ports、Docker/startup 和外部依赖：UNCHANGED。

合并后按普通应用发布顺序更新 web 和现有 `ai_content` worker，无迁移或配置前置步骤。上线后
验证 production Mock 拒绝、unavailable fail-closed，以及四条既有 AI Job 的创建、重试、结果
写入与 provenance。

## XW-0403 credential resolver integration

XW-0403 在不改变统一 Adapter request/response 的前提下实现数据库凭据 Resolver：
active credential 先由独立 `FIELD_ENCRYPTION_MASTER_KEY` 解密，再临时封装为 `AdapterCredential`。
密钥明文不进入 request、response、provenance、日志或持久化 result。XW-0403 的 `/test`
只检查本地存储与解密边界；真实 Provider 验证继续由 XW-0404 及后续真实 Adapter 负责。

## XW-0404 DeepSeek detection integration

XW-0404 registers the first real `geo_detection` Adapter in the shared code-level registry.
The Adapter consumes XW-0402 runtime model IDs/timeouts and XW-0403 `DatabaseCredentialResolver`,
performs exactly one provider HTTP call, returns the XW-0401 normalized response contract, and
maps provider/network failures into the existing `AIAdapterError` taxonomy. It does not implement
retry scheduling, queues, ModelCall persistence, scoring, or text-generation capabilities.

## XW-0405 Doubao detection integration

XW-0405 registers `doubao/doubao/geo_detection` independently against the current Volcengine Ark
Responses API. It reuses the same runtime and database credential boundaries without treating the
DeepSeek wire protocol as generic. The Adapter performs one non-streaming, non-stored request with
thinking disabled, does not enable Web Search tools in this contract, and truthfully reports requested
search as degraded with no fabricated citations. Full details are in
`docs/43-DOUBAO-DETECTION-ADAPTER.md`.
