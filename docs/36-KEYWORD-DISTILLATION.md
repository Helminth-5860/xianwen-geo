# XW-0303 关键词蒸馏实现

## 产品与版本边界

蒸馏严格读取主体当前的一份不可变 `KeywordSetVersion`，并同时固化该关键词版本绑定的 `SubjectVersion`。运行中若主体正式版本或当前关键词正式版本发生变化，任务以 `conflict` 结束，不能覆盖已有蒸馏草稿。任何动作都不更新或删除历史 `KeywordSetVersion` / `Keyword`。

机器结果、用户调整和正式确认是三层数据：

- `DistillationResult` 保存校验后的原始机器输出、摘要和白名单 metrics，永久不可变；
- `DistillationWorkspace` / `DistillationDraftItem` 是可修改的完整调整草稿，使用 `expected_version` 乐观并发；
- `DistillationSet` / `DistillationItem` 是用户明确确认后生成的连续、不可变历史版本。

## 动作语义

- `keep`：保留独立意图；
- `merge`：把至少两个输入关键词编入一个合并组，并选择组内一个输入关键词为 canonical；不生成新关键词；
- `delete`：仅表示后续不采用的建议，不删除关键词；
- `low_value`：保留为低价值/低优先级建议，与删除不同。

四种动作互斥，一个来源关键词恰好有一个动作且至多属于一个合并组。合并组使用 UUID；组内至少两个成员、canonical 必须是组内成员，且所有成员必须具有相同的地域签名。原始 `ai_reason` 与 provider/model/adapter/prompt、input/output digest 属于不可变 provenance；人工说明保存在独立 `user_reason`。

## 任务、幂等和额度

任务状态为 `queued/running/retry_wait/succeeded/failed/conflict/superseded`，复用 `generation` lease、attempt/retry、stale reclaim 和 late-worker 防护。每主体至多一个 active task。创建请求由独立 HMAC 密钥派生 owner/subject scoped 幂等摘要，相同 canonical 请求重放同一任务，不同请求返回冲突。

每主体第一次成功应用蒸馏草稿免费。已有成功任务时必须显式 `regenerate=true`，并冻结既有 `distillation_regenerations` 一次额度。只有校验后的 provider 结果与完整草稿在同一事务成功写入后才 consume；临时重试不重复冻结，永久失败、重试耗尽、stale version、workspace conflict 和 superseded 均 release。结算始终绑定原始 hold/account，跨周期不会转移到新账户。

## Provider 与安全

Provider 只接收冻结的主体字段值和正式关键词投影；外部文本一律是数据，不是系统指令。输出必须完整覆盖输入、动作合法、分组与地域合法，任何不完整或越界输出均 fail closed。日志、事件和 API 不保存/返回 prompt、主体输入正文、API key、幂等摘要或 provider raw response。

当前只有显式 local/test `mock` 与 `unavailable` adapter。Production 禁止 Mock；真实 production adapter 未实现时仅允许 `unavailable`，创建任务返回服务不可用。

## API 与前端

- `POST /api/v1/subjects/{id}/distillations`
- `GET /api/v1/distillation-jobs/{job_id}`
- `GET/PATCH /api/v1/subjects/{id}/distillations/draft`
- `GET /api/v1/subjects/{id}/distillations/current`
- `POST /api/v1/subjects/{id}/distillations/confirm`

关键词页面要求先存在当前正式关键词版本。用户启动任务、轮询结果、查看 AI 理由、调整动作/canonical/组/人工说明、保存草稿，再明确确认正式蒸馏版本。关键词或蒸馏存在本地未保存修改时禁止启动；蒸馏调整未保存时禁止确认，并注册 `beforeunload` 提示。

## PostgreSQL 与部署

迁移 `keywords.0006` 创建模型与约束，`keywords.0007` 安装 PostgreSQL 专用 guards：冻结 Job 事实和合法状态迁移；验证 hold 与终态 exactly-once 结算；保护 Result/Event/正式 Set/Item 不可变；验证 workspace、输入版本、来源结果、canonical 和延迟合并组完整性。

部署顺序：

1. 配置 `DISTILLATION_PROVIDER=unavailable` 和独立强随机 `DISTILLATION_IDEMPOTENCY_HMAC_KEY`，可选配置 timeout/retry/stale 参数；
2. 执行 Django migrations；
3. 重启 web、`ai_content` worker 和 Celery Beat；
4. 验证 production Mock fail-closed、草稿读取和 Beat dispatcher。

没有新端口、Redis keyspace、第三方 Python/前端依赖或 Docker 启动方式。新增任务 `keywords.execute_distillation` 路由到现有 `ai_content` 队列，Beat 每 60 秒执行 `keywords.dispatch_distillation_jobs`。

## 非目标

XW-0303 不创建问题分类、问题库或问题生成任务，不实现 XW-0304/XW-0305，不生成 GEO 检测、文章或其他下游产物。
