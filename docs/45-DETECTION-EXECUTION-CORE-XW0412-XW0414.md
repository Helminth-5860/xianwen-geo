# XW-0412 ~ XW-0414：GEO 检测执行核心

本文记录 XW-0412、XW-0413、XW-0414 的实现边界和部署约束。三个任务作为一个 Detection Execution Core Wave 实施，但仍分别保留验收责任。

## 1. 范围

- XW-0412：检测问题/模型选择、服务端估算、不可变输入快照、检测点冻结、创建幂等。
- XW-0413：套餐队列优先级、用户并发、全站/模型并发信号量、队列顺序、排队超时。
- XW-0414：问题 × 模型调用矩阵、Worker、可重试错误、用户取消、部分结算、模型暂停/禁用处理。

不在本 Wave：引用提取、SSRF 来源核验、程序化评分、语义评分、聚合报告、进度页面。它们从本 Wave 持久化的 `ModelResponse` / `ModelCall` 读取结果。

## 2. 事实源

PostgreSQL 是检测任务、调用状态和额度结算的事实源。Redis 只用于短期并发租约；Celery 只负责运输和执行。Redis/Celery 状态丢失不得改变 PostgreSQL 中已确认的任务事实。

创建时服务端冻结：

- 当前主体版本；
- 当前关键词集版本；
- 当前蒸馏集；
- 当前确认问题库版本；
- 被选问题的文本、分类、优先级、类型和评分参与标志；
- 被选模型及当时的 provider model ID、timeout、retry、网络策略、并发上限和 runtime version；
- entitlement snapshot；
- prompt/scoring rule version；
- 套餐 queue priority。

客户端 estimate 仅用于展示；创建任务时服务端必须重新校验问题、模型、套餐和预计检测点。

## 3. 持久化结构

新增：

- `GeoDetectionJob`
- `GeoDetectionSnapshot`
- `GeoDetectionQuestionSnapshot`
- `GeoDetectionModelRun`
- `ModelCall`
- `ModelCallAttempt`
- `ModelResponse`

Snapshot、question snapshot 和 model response 在应用层及 PostgreSQL trigger 层保持不可变。检测历史和调用历史不可删除。

`ModelCall` 唯一键为 job + question snapshot + model。`ModelCallAttempt` 唯一键为 model call + attempt number。

## 4. 额度语义

一次问题 × 一模型 × 一 provider call 单元计划占用一个 `detection_points`。

创建任务时：

1. 锁定有效 Subscription / quota account；
2. 服务端重新计算 `question_count × model_count`；
3. 在同一数据库事务中创建 Job/Snapshot/Calls；
4. 通过现有 `freeze_quota(...)` 冻结完整计划点数，`business_type=geo_detection`。

结算：

- provider 成功：consume 1；
- 最终失败：release 1；
- 排队超时 / 模型暂停 / 用户取消未开始调用：release 1；
- retry 属同一 ModelCall，不再冻结/消耗第二个点；
- settlement 使用稳定 idempotency key，保证 exactly-once。

## 5. Queue / concurrency

执行 call 使用 Celery `geo_detection` queue。Beat 周期扫描 PostgreSQL 中到期 queued/retry-wait call，并按：

1. job queue priority 降序；
2. call queued_at 升序；
3. call id 稳定排序。

并发同时受：

- 套餐 `concurrent_detection_jobs`；
- `GEO_DETECTION_GLOBAL_MAX_CONCURRENCY`；
- XW-0402 runtime `max_concurrency`。

Redis semaphore 使用有过期时间的 sorted-set lease，Worker 完成后释放。Redis 不可用时 fail closed，不绕过并发限制。

## 6. Retry / pause / cancel

Adapter 保持单次 HTTP attempt；retry 由 Worker 调度。

只有现有 `AIAdapterError.retryable=True` 才进入 retry-wait，并使用创建时冻结的 runtime max retries / base seconds / backoff。每个新 attempt 前重新读取 live runtime：模型 paused/disabled 时不再调用 Provider，且不自动替换其他模型。

取消任务后：

- 标记 `cancel_requested_at`；
- 不再 dispatch 新 call；
- queued/retry-wait 且未开始 provider 调用的 call 取消并释放点数；
- running call 不尝试强杀上游 HTTP；完成后按最终成功/失败正常结算；
- Job 允许得到 cancelled / partial 等终态。

## 7. API

本 Wave 实现并同步 OpenAPI：

- `GET /geo/models`
- `GET /subjects/{id}/geo/detection-options`
- `POST /subjects/{id}/geo/estimate`
- `GET /subjects/{id}/geo/detections`
- `POST /subjects/{id}/geo/detections`
- `GET /geo/detections/{id}`
- `GET /geo/detections/{id}/model-progress`
- `POST /geo/detections/{id}/cancel`

创建接口要求 `Idempotency-Key`。Key 使用独立 `GEO_DETECTION_IDEMPOTENCY_HMAC_KEY` 派生摘要，数据库不保存原始 key。

## 8. Provider / response 安全

Worker 继续通过 XW-0401/0402/0403：

runtime snapshot → registry → `DatabaseCredentialResolver` → Adapter。

不得保存 credential plaintext、Authorization、原始 Provider request 或不受控 raw JSON。`ModelResponse` 保存最终回答正文、正文 SHA-256 和 Adapter 已白名单化的 provider metadata。错误只保存稳定 code/category 和安全摘要。

## 9. 运行配置

新增：

- `GEO_DETECTION_IDEMPOTENCY_HMAC_KEY`
- `GEO_DETECTION_GLOBAL_MAX_CONCURRENCY`（默认本地 32）
- `GEO_DETECTION_QUEUE_TIMEOUT_SECONDS`（默认本地 900）
- `GEO_DETECTION_DISPATCH_BATCH`（默认本地 100）
- `GEO_DETECTION_INTERNAL_MAX_RETRIES`（默认本地 3，仅 Celery/Django 内部故障保护，不替代 Provider retry policy）

Production 必须提供独立、强随机的 GEO idempotency HMAC key，不得复用 Django/Quota/Question/Plan 等 secret。

## 10. 测试

Dedicated PostgreSQL/Redis Gate：`scripts/test-geo-detection.*`。

至少覆盖：

- estimate / create snapshot / matrix；
- create idempotency replay/conflict；
- user concurrency；
- success consume + safe response persistence；
- retryable failure 在同一 point 上重试；
- live model pause fail closed + release；
- cancel unstarted call + release；
- DB queue priority ordering；
- Redis global/model semaphore；
- PostgreSQL tables / immutable guard triggers；
- XW-0401~XW-0411 adapter/runtime/credential regressions。

## 11. 部署影响

- Environment/config：新增上述 5 个 `GEO_DETECTION_*` 配置名。
- Django migrations：YES，`geo.0001` / `geo.0002`。
- PostgreSQL：新增检测执行表、constraints、indexes、immutability/no-delete triggers。
- Redis：新增 GEO concurrency semaphore keys；拓扑不变。
- Celery：新增 `geo_detection` queue；主 Worker 必须消费该 queue；Beat 增加 dispatcher。
- Ports：NONE。
- External Python dependencies：NONE。
- Docker/startup：Worker queue 参数变化，发布后确认 API、worker、beat 均加载最新代码和配置。

推荐 rollout：数据库 migration → API/worker/beat image rollout → Worker 确认消费 `geo_detection` → Redis/DB health → 创建最小 Staging 检测任务 smoke。真实 Provider credential/smoke 仍受各 Provider 的 Deployment Acceptance 条件约束。
