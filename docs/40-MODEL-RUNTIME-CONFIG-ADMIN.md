# XW-0402 模型和运行配置后台

## 1. 范围

XW-0402 为固定 8 个 GEO 检测模型提供后台运行配置。它复用 XW-0401 的统一
Adapter/Model Registry，但不注册真实检测 Adapter，也不保存 API 密钥或密钥引用。

固定模型 key 为：`deepseek`、`doubao`、`qwen`、`hunyuan`、`wenxin`、`kimi`、
`glm`、`spark`。Provider/model machine identity、canonical name/order、built-in 标志不可修改，
且没有新增或删除模型 API。Seed 默认全部停用，直到后续真实 Adapter 单独验收。

## 2. 数据边界

- `AIProvider`：固定 Provider identity。
- `AIModel`：固定模型 identity、canonical display metadata 和 `geo_detection` purpose。
- `AIModelRuntimeConfig`：一对一保存 display override、provider model ID、API version、启停、
  排序、联网策略、超时、重试、并发、估算成本和暂停状态。
- `version` 是运行配置的乐观并发版本。所有写入必须精确推进一次。

成本币种固定 CNY。成本可以未配置、按百万 Token 配置 input/output 单价，或按请求配置单价；
三种状态由数据库约束互斥。本任务不创建用户账单、额度流水或供应商账单同步。

## 3. 运行消费合同

`apps.ai.runtime` 返回不可变 `AIModelRuntimeSnapshot`。未来检测创建/Worker 应通过该服务读取，
不得依赖管理员 serializer 或裸数据库行。新任务读取时：

- disabled：`AI_MODEL_DISABLED`，失败关闭；
- paused：`AI_MODEL_PAUSED`，失败关闭；
- 配置缺失：`AI_MODEL_RUNTIME_CONFIG_MISSING`，失败关闭；
- XW-0401 Registry 无对应 `geo_detection` Adapter：按统一 Registry 错误失败关闭。

配置不缓存，只影响后续读取的新任务。XW-0413/0414 才消费重试、并发和暂停策略。

## 4. 管理接口与权限

- `GET /api/v1/admin/ai-models`
- `GET /api/v1/admin/ai-models/{model_id}`
- `GET /api/v1/admin/ai-model-runtime-configs`
- `GET/PATCH /api/v1/admin/ai-model-runtime-configs/{model_id}`
- `POST /api/v1/admin/ai-models/{model_id}/enable|disable|pause|unpause`

读取要求 `models.list`，写入要求 `models.manage`；全部复用管理员安全 Session。写请求要求
CSRF 和 `expected_version`。暂停还要求有界纯文本原因。每次成功写入同事务追加安全 AuditEvent，
审计摘要不保存 API key、secret、provider raw response、provider model ID 或 pause reason 正文。

## 5. PostgreSQL guards 与回滚

数据库约束固定 8 个 key、GEO purpose、数值范围、成本形状和暂停原因。PostgreSQL triggers
拒绝 Provider/Model identity 变化、built-in 删除、RuntimeConfig model rebinding、删除和非精确版本推进。

Seed migration reverse 为 noop，避免孤立后续引用；guard reverse 仅卸载 triggers/functions。完整回退
会删除模型配置表，生产逆向迁移前必须停止相关写入、审查并备份，优先前向修复或备份恢复。

## 6. 部署影响

- Environment variables：NONE
- Django migrations：YES
- Celery queues/workers：NONE
- Ports：NONE
- PostgreSQL：新增 3 表、固定 Seed、约束和 guards
- Redis：UNCHANGED
- External dependencies：NONE
- Scheduled tasks：NONE
- Docker/startup：UNCHANGED

发布时先部署兼容代码，单独执行 migration 并检查退出码，再滚动 web。部署后核对 8 条 Seed、
后台读写与 AuditEvent，以及 disabled/paused/缺失 Adapter 的失败关闭行为。

## XW-0404 DeepSeek consumption

The DeepSeek detection Adapter consumes `provider_model_id` and `timeout_seconds` from the immutable
runtime snapshot. No DeepSeek model ID is hardcoded into the registry identity. The fixed internal
identity remains `provider_key=deepseek`, `model_key=deepseek`; current provider model aliases are
runtime data. Enabled/paused checks remain in `resolve_detection_adapter()` before new calls.
