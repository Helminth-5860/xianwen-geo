# XW-0403 — API 密钥安全管理

## 1. 范围

本任务只实现固定 AI Provider 的密钥安全管理：

- 仅超级管理员；
- 加密保存；
- 保存后只返回掩码；
- 显式轮换；
- 本地安全存储测试；
- 追加式审计。

真实 Provider 网络调用、DeepSeek/豆包等检测 Adapter、API Key 远程真实性验证属于 XW-0404 及后续任务。

## 2. 加密边界

`FIELD_ENCRYPTION_MASTER_KEY` 是数据库外的独立 Fernet 主密钥。Production/Staging 必须各自配置，
不得使用 local 默认值，也不得复用 Django、HMAC、数据库、Redis 或对象存储凭据。

数据库 `secret_reference` 保存 Fernet 认证密文；API 永不返回该字段。应用只在创建、轮换、
resolver 解密和本地存储测试的调用栈中短暂持有明文。

## 3. 环境与 Resolver

凭据按固定 Provider + `staging|production` 分区。`API_CREDENTIAL_ENVIRONMENT` 决定运行时
`DatabaseCredentialResolver` 读取哪个环境的 active 凭据，这允许 Staging 继续使用 production
Django settings，同时仍与 Production 凭据隔离。

## 4. 版本与轮换

同一 Provider/环境最多一个 active 版本。新增已有 active 凭据返回冲突，必须走 rotate。

轮换：
1. 锁定当前 active 行并验证 `expected_version`；
2. 将旧版本状态设为 `replaced`；
3. 擦除旧行密文，保留 mask/version/history；
4. 创建 `version_no + 1` 的新 active 密文；
5. 业务变化、专属审计与统一 AuditEvent 同事务提交。

本任务不执行 Provider 侧密钥撤销；管理员必须在供应商侧完成真正的 credential rotation 生命周期。

## 5. Test 语义

`POST /admin/api-credentials/{id}/test` 只做：

- active/version 校验；
- Fernet 解密；
- `AdapterCredential` 注入对象构造；
- 安全审计。

成功响应明确 `storage_valid=true`、`remote_validated=false`。因此它不能被用于声称 Provider
凭据真实有效。XW-0404+ 接入真实 Adapter 后再扩展远程验证。

## 6. API 与权限

- `GET/POST /api/v1/admin/api-credentials`
- `POST /api/v1/admin/api-credentials/{id}/rotate`
- `POST /api/v1/admin/api-credentials/{id}/test`

全部要求完整管理员安全 Session 且 `user.is_superuser=true`。写操作要求真实 CSRF。
`api_credentials.manage` 权限被标记 `superuser_only`，用于前端 capability 展示，但 API 最终边界仍由
`HasSuperuserAdminSession` 强制。

## 7. 审计与日志

专属 `api_credential_audit` 与统一 `AuditEvent` 只保存 Provider、环境、版本、状态、mask、
操作结果和稳定错误码。敏感字段名由现有 audit/redaction infrastructure 拒绝或脱敏。

任何日志、异常、API、OpenAPI 或审计记录都不得保存：
- API Key 明文；
- Fernet 密文；
- Authorization/Cookie；
- Provider raw response。

## 8. PostgreSQL guards

关键数据库保护：

- Provider/环境/version 唯一；
- Provider/环境最多一个 active；
- active 必须存在密文；
- replaced 必须擦除密文并记录 replacement；
- 只允许 active -> replaced；
- Provider/环境/version/mask/creator/history identity 不可改写；
- credential 不可删除；
- credential audit 不可 update/delete。

## 9. 部署

新增：

- `FIELD_ENCRYPTION_MASTER_KEY`（Secret，Staging/Production 独立生成，禁止进 Git）
- `API_CREDENTIAL_ENVIRONMENT=staging|production`（非 Secret）

Migrations：
- `ai.0003_api_credentials`
- `ai.0004_api_credential_postgresql_guards`
- `admin_rbac.0020_seed_api_credential_permission`

部署顺序：
1. 先配置新的环境变量；
2. 部署含 `cryptography` dependency 的新镜像；
3. 执行 migrations；
4. 滚动 API / Frontend；
5. 不要求 Celery/Redis/端口拓扑变化；
6. 执行超级管理员 create/list/rotate/test smoke，并确认响应/日志无明文。

## XW-0404 real-call boundary

The DeepSeek detection Adapter resolves the active credential only through
`DatabaseCredentialResolver`. The XW-0403 admin `/test` endpoint remains a storage/decryption check;
XW-0404 adds a separate safe management-command smoke that performs a real provider call without
printing the API key, Authorization header, provider raw JSON, or answer text. This keeps the public
credential API stable while providing deployment-time remote validation for the first real Adapter.

## XW-0405 Doubao real-call boundary

The Doubao detection Adapter also resolves only the active environment-scoped database credential.
It adds no `DOUBAO_API_KEY`, `ARK_API_KEY`, or `VOLCENGINE_API_KEY` fallback. Its separate safe smoke
uses a fixed question and prints only bounded call metrics and identifiers, never the credential,
prompt, answer text, Authorization header, or Provider raw response.
