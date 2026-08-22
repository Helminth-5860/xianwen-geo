# 显问 GEO 智能体系统 V1 完整开发需求包

版本：V1.0  
状态：产品功能冻结，可进入分阶段开发  
目标实施工具：Codex  
产品语言：简体中文  

## 1. 使用说明

本需求包是显问 GEO 智能体系统 V1 的开发源文件。开发、测试、验收应以本目录中的文档为准，不应直接依据聊天记录或口头描述实现。

优先阅读顺序：

1. `docs/00-DECISION-REGISTER.md`
2. `docs/01-PRD.md`
3. `docs/02-USER-FLOWS.md`
4. `docs/03-ADMIN-FUNCTIONS.md`
5. `docs/04-GEO-SCORING-RULES.md`
6. `docs/05-QUOTA-BILLING-RULES.md`
7. `docs/06-DATABASE-SCHEMA.md`
8. `docs/07-API-SPECIFICATION.md`
9. `docs/08-AI-MODEL-ADAPTERS.md`
10. `docs/09-SECURITY-PERMISSIONS.md`
11. `docs/10-DEPLOYMENT.md`
12. `docs/11-ACCEPTANCE-TESTS.md`
13. `docs/12-CODEX-TASKS.md`
14. `docs/13-IMPLEMENTATION-INPUTS.md`
15. `codex/CODEX-START-HERE.md`

## 2. 目录结构

```text
xianwen_geo_v1_dev_package/
├── README.md
├── docs/
│   ├── 00-DECISION-REGISTER.md
│   ├── 01-PRD.md
│   ├── 02-USER-FLOWS.md
│   ├── 03-ADMIN-FUNCTIONS.md
│   ├── 04-GEO-SCORING-RULES.md
│   ├── 05-QUOTA-BILLING-RULES.md
│   ├── 06-DATABASE-SCHEMA.md
│   ├── 07-API-SPECIFICATION.md
│   ├── 08-AI-MODEL-ADAPTERS.md
│   ├── 09-SECURITY-PERMISSIONS.md
│   ├── 10-DEPLOYMENT.md
│   ├── 11-ACCEPTANCE-TESTS.md
│   ├── 12-CODEX-TASKS.md
│   └── 13-IMPLEMENTATION-INPUTS.md
├── openapi/
│   └── openapi-v1.yaml
├── sql/
│   └── schema-outline.sql
├── config/
│   ├── env.example
│   └── plan-limit-keys.json
└── codex/
    ├── CODEX-START-HERE.md
    └── TASK-PROMPT-TEMPLATE.md
```

## 3. V1 核心目标

建立一个通过网站使用的商业化 GEO 智能体系统，形成以下闭环：

```text
注册与审核
→ 创建主体
→ 完善主体资料
→ 生成关键词
→ 关键词蒸馏
→ 生成并确认问题库
→ 8 模型 GEO 检测
→ GEO 评分报告
→ GEO 改善策略
→ 文章与图片内容建设
→ 渠道适配与发布检测
→ 持续复测
```

## 4. 已冻结的关键产品决策

- 第一版不做视频生成。
- 第一版不做在线支付，不记录线下收款或成交金额。
- 第一版不做网页端自动化检测，只调用官方 API。
- 第一版固定接入 8 个检测模型：DeepSeek、豆包、通义千问、腾讯混元、百度文心、Kimi、智谱 GLM、讯飞星火。
- 每个模型独立评分；综合分按成功的正式模型等权平均。
- 至少 6 个正式模型得分，才产生正式综合分。
- 单个模型的问题调用成功率达到 80%，才产生正式模型得分。
- 所有用户端和后台界面均使用简体中文。
- 单账号使用，不支持团队成员、子账号或多人协作。
- 套餐、额度、模型权限和限制均由后台动态配置。
- 同一账号同一时间仅允许一个生效套餐。
- 关键词支持可选的短关键词、长尾关键词、地区关键词；三者不是互斥分类，也不是必选项。
- 文章只保留当前稿；优化时临时对比原稿和优化稿，用户二选一后只保留选中稿。
- 报告分享默认展示完整报告，并允许下载 PDF。
- 显问 AI 助手固定使用 DeepSeek，不保存聊天记录，不直接执行扣费操作。

## 5. 明确不在 V1 范围内

- 视频生成
- 自动登录第三方平台并自动发布文章
- 在线支付、退款、发票、财务结算
- 多语言系统
- 企业成员协作、代理商子账号
- 完整 CRM、合同、回款和销售业绩管理
- AI 产品网页端自动化、验证码处理和真实官网截图
- 逐条生成证据卡片或大量证据图片
- 文章多版本历史与恢复
- 用户自定义模型 API 接口
- 复杂低代码表单条件联动
- WebSocket 实时流式进度；V1 使用轮询

## 6. 分阶段交付

### 阶段一：GEO 核心闭环

账号、审核、套餐、主体、关键词、蒸馏、问题库、8 模型检测、评分、报告、复测、改善策略、AI 助手。

### 阶段二：内容建设闭环

文章、大纲、质量检测、优化对比、图片、渠道适配、发布链接即时检测、报告导出与分享。

### 阶段三：商用后台与上线

完整权限、客户记录、API 管理、审核、公告、反馈、统计、审计、安全、备份、告警、COS、短信、部署和压力测试。

## 7. 当前外部依赖状态

| 依赖 | 状态 |
|---|---|
| 应用服务器 | 已具备：4 vCPU / 8 GiB / 5 Mbps |
| PostgreSQL | 已具备：PostgreSQL 16.14，高可用，2 vCPU / 4 GiB / 100 GB |
| Redis | 已具备：Redis 7.0，1 GB，1 主 1 副 |
| 8 个检测模型 API | 已取得凭证；仍需逐一完成接口可用性验收 |
| DeepSeek 内容生成能力 | 尚未完成开通或验收 |
| 豆包图片生成能力 | XW-0710～0717 代码与隔离测试已实现；真实凭据/COS smoke 留作 Stage 3 UAT |
| 腾讯云 COS | 尚未开通 |
| 短信服务 | 尚未开通 |

## 8. 文档优先级与冲突规则

发生冲突时按以下顺序执行：

1. `docs/04-GEO-SCORING-RULES.md`
2. `docs/05-QUOTA-BILLING-RULES.md`
3. `docs/09-SECURITY-PERMISSIONS.md`
4. `docs/01-PRD.md`
5. 其他文档

如实现过程中发现文档之间仍有矛盾，不允许 Codex 自行猜测。应创建变更记录，并由产品负责人确认后更新本需求包。

## 9. 开发纪律

- 每个功能必须先完成数据模型、权限、额度规则、异常回滚和自动化测试设计，再写页面。
- 禁止直接修改额度余额；所有额度变化必须通过不可删除的流水。
- 禁止同步阻塞式执行多模型检测、文章生成、图片生成和报告导出。
- 禁止将 API 密钥放入前端、代码仓库、日志或错误响应。
- 禁止使用一个超大 Codex 任务一次性生成整个系统。
- 数据库迁移必须可回滚，生产环境禁止手工改表。

## 10. 本地开发（XW-0001）
状态：XW-0001 and XW-0002 integration verified.


要求：

- Docker Desktop（含 Docker Compose）
- PowerShell 7，或兼容 POSIX shell

一条命令启动：PowerShell 运行 `.\scripts\dev.ps1`，Linux/macOS 运行 `./scripts/dev.sh`。

首次运行会从 `.env.example` 创建仅供本地开发的 `.env`，随后构建并启动
PostgreSQL、Redis、Django API、Celery Worker 和 Next.js 前端。

启动后访问：

- 前端：<http://localhost:3000>
- 前端健康检查：<http://localhost:3000/api/health>
- 后端健康检查：<http://localhost:8000/api/v1/health/>

停止服务：`docker compose down`。

质量检查：运行 `.\scripts\check.ps1`，或分别使用 `backend/` 与 `frontend/`
README 中列出的命令。
## 11. 配置、日志和错误框架（XW-0002）

状态：XW-0001 and XW-0002 integration verified.

XW-0002 提供后续业务模块统一复用的工程边界：

- local、test、production 分环境 Django 配置
- 规范 UUID `request_id` 请求上下文
- `/api/v1` JSON 成功与错误 Envelope
- DRF 全局异常映射和简体中文错误消息
- local 可读日志、test 降噪、production 单行 JSON 日志
- 递归敏感字段脱敏

local 允许 SQLite/LocMem 安全回退，test 使用隔离配置。production 必须显式提供
密钥、PostgreSQL、Redis、主机和来源配置，并拒绝 DEBUG、SQLite、LocMem、
通配符主机及弱密钥。前端公开环境变量由 `frontend/lib/env.ts` 集中校验。

## 12. 持续集成基线（XW-0003）

CI 使用 Python 3.12 和 Node.js 24.18.0。Node.js 的唯一版本来源为
`frontend/.nvmrc`，本地开发、GitHub Actions、`package.json` 和前端 Docker
镜像必须保持一致。

安装依赖：

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

cd ..\frontend
npm ci
```

运行全部本地门禁：

```powershell
.\scripts\check.ps1 all
```

POSIX 环境使用 `./scripts/check.sh all`。也可传入 `backend`、`frontend`、
`security`、`docker`、`git`、`actionlint` 或 `gitleaks` 单独复现 CI 层。
详细的触发条件、检查项、缓存及敏感信息边界见
`docs/14-CI-BASELINE.md`。

GitHub Action 升级时，必须从官方仓库 release 核对完整 40 字符提交 SHA，同时更新
workflow 的版本注释，再运行结构测试和 actionlint。建立远程仓库后，应把
`Backend`、`Frontend`、`Security`、`Docker Compose` 配置为 `develop` 的
Required Checks。远程私有仓库已建立，XW-0003 Pull Request workflow 已完成真实验收。当前套餐不支持私有仓库分支保护，人工管理规则见 `docs/14-CI-BASELINE.md`。

若迁移到 GitLab、Gitee 或其他 CI 平台，只替换流水线入口，继续调用本地检查脚本，
不要复制检查逻辑。故障可用相应脚本模式本地复现；更多细节见
`docs/14-CI-BASELINE.md`。

## 16. 注册、短信登录和密码重置（XW-0103）

XW-0103 在现有 HttpOnly Session、CSRF 和 Redis 短信挑战基础上提供注册、密码/短信登录、
密码重置及对应前端页面。login/password_reset 发送采用 anti-enumeration 抑制策略，验证码、
密码、完整手机号和 Cookie 不进入响应或日志。详细边界见
`docs/17-REGISTRATION-SMS-LOGIN-PASSWORD-RESET.md`。
## 17. 用户审核与账号状态管理（XW-0104）

XW-0104 提供独立的审核状态和账号状态机、追加式状态历史、最小站内通知、管理员审核页面，
以及基于用户级 `session_version` 的全量 Session 撤销。冻结会使全部旧 Cookie 在下一次请求
时失效；解冻不会恢复旧会话。

管理员 API 仅允许有效 staff 使用，不提前建设完整 RBAC。完整接口、并发、迁移、日志和
回滚边界见 `docs/18-USER-APPROVAL-ACCOUNT-STATUS.md`。
## 18. 管理员 RBAC 与客户数据范围（XW-0105）

XW-0105 在唯一 User 认证身份之上提供 AdminProfile、单角色 RBAC、显式菜单/动作权限、
own/role/all 客户范围、管理员 Session 即时撤销和防 ABA 的客户当前归属。超级管理员能力固定
由 is_superuser 识别，普通角色不能模拟。实现与 PostgreSQL 并发验收方式见
`docs/19-ADMIN-RBAC-DATA-SCOPE.md`。
RBAC 的 0002 Seed 迁移反向操作为 `RunPython.noop`：单独回退不会恢复普通 staff，也不会删除 Permission Seed/Profile；完整回退 0001 会删除 RBAC 表及证据。生产逆向迁移前必须审查、备份，优先采用前向修复或备份恢复，且不得连接腾讯云数据库进行验证。
## 19. 管理员 2FA 与 IP 白名单（XW-0106）

XW-0106 增加独立管理员密码/短信登录、不可持久化的 Redis 两阶段 challenge、管理员安全 Session 上下文、角色及超级管理员 IPv4/IPv6 白名单、追加式安全事件、全部设备强制退出和服务器控制台紧急恢复。管理员身份不能从普通登录入口绕过；超级管理员短信 2FA 永久强制，production 未配置真实短信 Provider 时失败关闭。实现、迁移回滚限制和 PostgreSQL/Redis 专属验收见 `docs/20-ADMIN-2FA-IP-ALLOWLIST.md`。

## 20. 高风险审批与统一安全审计（XW-0107）

XW-0107 将首批 12 个高风险写操作接入固定 Catalog 和显式 Handler 注册表，并按 PostgreSQL 当前 RiskPolicy 执行确认、密码再验证或双人审批。V1 不公开通用审批创建 API，不提供 BPM、动态执行器或单人绕过。审批 payload 只保存动作专属安全字段和绑定目标版本的摘要；统一 AuditEvent 追加式保存白名单摘要，不保存密码、验证码、Cookie、Session、challenge、完整手机号/IP、基础设施秘密或原始异常。

迁移 Seed 使用 RunPython.noop 保留被审批/审计引用的目录证据；完整逆向迁移会删除审批和审计表，生产必须先审查并备份，优先前向修复或备份恢复。设计、API、安全边界及 PostgreSQL/Redis 专属验收见 docs/21-HIGH-RISK-APPROVAL-AUDIT.md。
## 套餐与不可变版本（XW-0110）

套餐模板使用独立 `plans` 应用、代码所有 Limit Catalog、typed value、八模型权限和 PostgreSQL 不可变触发器。展示价格仅用于 CNY 页面展示，不是交易价格；本阶段没有申请、订阅、订单、支付或财务流水。

本地专属验证运行 `.\scripts\test-plans.ps1`。Seed 迁移 reverse 为 noop，触发器逆向只移除数据库保护；完整回退会丢失套餐和发布快照证据，任何逆向迁移前必须审查并备份，生产优先前向修复或备份恢复。当前未连接腾讯云 PostgreSQL/Redis。

完整设计和回滚边界见 [docs/22-PLANS-PLAN-VERSIONS.md](docs/22-PLANS-PLAN-VERSIONS.md)。

## 套餐申请（XW-0111）

套餐申请统一使用 `PlanApplication`、`/api/v1/plan-applications` 和
`/api/v1/admin/plan-applications`。申请绑定创建时的 current published PlanVersion 与最小公开快照，
PostgreSQL 条件唯一约束、事务锁和数据库 trigger 保护幂等、单 open 申请及不可变绑定。管理员按当前
CustomerAssignment 动态应用 own/role/all 范围，contact/close 经统一风险编排；状态、追加式事件、
固定通知与 AuditEvent 同事务提交。

本阶段没有 activate、Subscription、Quota、订单或支付。真实 PostgreSQL 专属验证运行
`.\scripts\test-plan-applications.ps1`；Seed reverse 为 noop，trigger reverse 只移除保护，生产逆向
迁移前必须审查并备份，优先前向修复或备份恢复。完整设计与回滚边界见
[docs/23-PLAN-APPLICATIONS.md](docs/23-PLAN-APPLICATIONS.md)。
## 用户订阅（XW-0112）

订阅事实由 PostgreSQL Subscription 和追加式 SubscriptionEvent 保存。正式订阅只能
从套餐申请激活，试用只能由管理员审核发放；三项写操作均固定双人审批。用户通过
GET /api/v1/subscription 只读当前有效订阅，响应不会暴露完整权益快照或 digest。

状态、锁顺序、数据库触发器、权限和回滚边界见
[docs/24-SUBSCRIPTIONS.md](docs/24-SUBSCRIPTIONS.md)。
## Quota ledger (XW-0113)

Quota balances, holds, idempotency evidence, and append-only ledger history are
owned by PostgreSQL in the independent `apps.quotas` application. There is no
Subject UUID account and no public reset API in this task. Administrator
grant/compensate/manual-deduct operations are fixed two-person actions; user
responses omit internal business IDs and digest fields.

See [docs/25-QUOTA-LEDGER.md](docs/25-QUOTA-LEDGER.md). Run the real isolated

## 套餐变更（XW-0114）

套餐变更由 PostgreSQL `SubscriptionChange` 保存批准后的 scheduled/executed/cancelled 领域事实，
新订阅通过不可变 `source_change` 建立来源链。续费只排期；升级、降级、替换和试用转正式立即执行。
两项写动作固定双人审批，原始 Idempotency-Key 不进入持久化、日志或响应。

额度迁移只允许 overwrite、accumulate 和 retain。`QuotaHoldGroup` 支持跨到期批次冻结，
`QuotaTransfer` 用延迟 Trigger 校验成对流水；没有 scheduled 自动执行、Beat、订单或支付。
本地真实 PostgreSQL/Redis 验收运行 `.\scripts\test-plan-changes.ps1`。

Seed reverse 保留审批/审计引用；Trigger reverse 只移除保护，不能安全撤销已执行变更或迁移流水。
完整回退会删除领域证据，生产逆向迁移前必须停止写入、审查并备份，优先前向修复或备份恢复。
完整边界见 [docs/26-PLAN-CHANGES.md](docs/26-PLAN-CHANGES.md)。
PostgreSQL/Redis suite with `.\scripts\test-quotas.ps1`.

## Cycle reset and expiry processing (XW-0115)

Celery Beat scans due renewals, subscription expiries, and monthly quota
boundaries, while PostgreSQL stores all retry and exactly-once evidence.
Subscription expiry is never blocked by a scheduled renewal or Hold. Renewal
targets retain their approved effective window and can execute from an expired,
but never terminated, source.

Monthly reset creates immutable quota batches and ledger evidence; it never
rewrites old batches or releases Holds. There is no public execute or reset API.
Run the real isolated PostgreSQL/Redis suite with
`.\scripts\test-cycle-reset.ps1`. Full lifecycle, worker, migration, and
rollback boundaries are in [docs/27-CYCLE-RESET-EXPIRY.md](docs/27-CYCLE-RESET-EXPIRY.md).

## 主体类型与动态字段目录（XW-0201）

独立 `apps.subjects` 使用 PostgreSQL 保存主体类型、不可变字段定义、每类型 FieldConfig
和稳定 option_key。十类内置主体会在同一事务获得六个公共字段；所有 Schema 写入使用独立
`schema_version`、对象版本、真实 CSRF、RBAC 和同事务 AuditEvent。数据库 Trigger 拒绝
目录 DELETE、机器语义修改、字段冲突、无效默认值和 active Schema 丢失唯一正式名称。

本任务不创建 Subject/SubjectVersion，不提供文件上传、COS、AI 补充或主体额度。image/file
仅作为表单声明并显示“上传能力尚未启用”。XW-0202 必须保存提交时 schema_version、canonical
schema snapshot 和 digest，不得用未来当前 Schema 解释历史主体版本。

真实 PostgreSQL/Redis 套件运行 `.\scripts\test-subject-schema.ps1`；完整模型、API、迁移、
回滚与验收边界见 [docs/28-SUBJECT-TYPES-DYNAMIC-FIELDS.md](docs/28-SUBJECT-TYPES-DYNAMIC-FIELDS.md)。

## Subject drafts and active limits (XW-0202)

User-owned subjects persist an immutable canonical schema snapshot and digest at
draft creation, while `SubjectVersion` remains reserved with no production
write path until XW-0203. Existing drafts continue to use their saved schema
projection even when the administrator catalog changes.

PostgreSQL enforces immutable bindings, append-only events and versions, legal
status transitions, current-subject ownership, no-plan draft concurrency, and
the final active slot. Subscription, trial, plan-change, and renewal paths fail
closed when `subject_active_limit` would be exceeded; no subject is
automatically archived. There is no upload, AI enrichment, subject quota
account, commit, or version API in this task.

Run the real PostgreSQL/Redis suites with
`.\\scripts\\test-subject-schema.ps1`. Full API, lock order, migration,
rollback, and verification boundaries are documented in
[docs/29-SUBJECT-DRAFTS-ACTIVE-LIMITS.md](docs/29-SUBJECT-DRAFTS-ACTIVE-LIMITS.md).

## Subject formal versions, names, and products (XW-0203)

Saved drafts can now be committed as immutable, strictly contiguous formal
versions. The commit API accepts only a stale-write version and confirmations
for server-derived product candidates; field values, frozen schema, names,
products, digests, and version numbers are derived under the locked PostgreSQL
transaction. Draft and active subjects may commit without changing activation
or Subscription state. Archived subjects cannot commit.

Every formal version preserves its own schema snapshot, canonical field values,
official/alternate names, and product-confirmation semantics. Historical pages
therefore do not consult the mutable SubjectType catalog. PostgreSQL deferred
guards enforce version 1/contiguous chains, same-Subject maximum current pointer,
schema binding, exactly one official name, bound commit events, and append-only
semantic facts. No historical XW-0202 SubjectVersion is fabricated.

See [docs/30-SUBJECT-VERSIONS-NAMES-PRODUCTS.md](docs/30-SUBJECT-VERSIONS-NAMES-PRODUCTS.md).

## Subject risk catalog and review (XW-0204)

Subject risk types and rules are draft configuration. Only the fixed two-person
`subject_risk.catalog.publish` action activates an immutable catalog revision;
no production risk keywords, industry decisions, AI classifier, or external
moderation provider is seeded. Each formal SubjectVersion is classified against
and permanently bound to the then-current revision, while feature enforcement
uses the current published policy without rewriting historical evidence.

Scoped manual review is a direct single-administrator decision protected by a
secure admin Session, CSRF, RBAC, own/role/all customer scope, expected versions,
and append-only audit evidence. See
[docs/31-SUBJECT-RISK-RULES-REVIEW.md](docs/31-SUBJECT-RISK-RULES-REVIEW.md).
## XW-0205 私有文件与对象存储

文件上传使用受大小约束的 S3-compatible presigned POST、异步验证 Saga 和 PostgreSQL 不可变占用证据；本地集成使用 MinIO，不代表腾讯 COS 生产接入。完整边界、配置、收敛命令与回滚规则见 `docs/30-FILE-UPLOAD-COS-ABSTRACTION.md`。运行专属验收：`scripts/test-files.ps1`（Windows）或 `scripts/test-files.sh`（Linux/CI）。

## XW-0206 file parsing and user confirmation

Completed private files can be parsed asynchronously by the isolated `file_processing` worker.
The canonical root Compose defines `file-processing-worker`; release readiness derives its expected
queue set from the production Celery routes so a routed queue cannot be represented by a fake or
missing worker expectation.
Machine output and user-confirmed canonical text form an immutable PostgreSQL version chain;
tables/warnings remain machine facts, and downstream feature use must re-apply the current
XW-0204 risk policy. Local/test OCR is a mock only and production fails closed for image OCR.
See [docs/32-FILE-PARSING-USER-CONFIRMATION.md](docs/32-FILE-PARSING-USER-CONFIRMATION.md).

## XW-0207 public web import and SSRF protection

Public pages are fetched only by the isolated `web_fetch` Celery worker. The API process persists a
queued Saga but performs no outbound fetch. URL validation, all-answer DNS filtering, fixed-IP
connections, peer verification, manual redirect validation, TLS hostname verification and strict
response limits fail closed. The parser is static and does not execute JavaScript or load any
subresource.

Production keeps `WEB_IMPORT_ENABLED=false` unless deployment explicitly supplies both an independent
`WEB_IMPORT_IDEMPOTENCY_HMAC_KEY` and `WEB_IMPORT_NETWORK_POLICY_ENFORCED=true`. Production has no
allow-private switch or mock transport. Environment proxies and caller headers are never used.

The user APIs are owner-scoped, `no-store`, Session/CSRF protected, and expose only a query-free display
URL. Imported content remains unavailable to internal feature selectors until the owner creates an
immutable confirmation version. This task creates no storage allocation, quota, billing or AI fact.

Run the real isolated suite with `.\scripts\test-web-import.ps1` on Windows or
`bash scripts/test-web-import.sh` on Linux/CI. See
[docs/33-WEB-IMPORT-SSRF-PROTECTION.md](docs/33-WEB-IMPORT-SSRF-PROTECTION.md) for the network and
evidence boundaries.

- [XW-0208 主体 AI 补充 Mock 和流程](docs/34-SUBJECT-AI-ENRICHMENT-MOCK-FLOW.md)

### XW-0301 关键词数据模型和编辑器

关键词领域位于 `apps.keywords`：人工草稿使用乐观并发，正式 `KeywordSetVersion/Keyword` 为不可变历史，并绑定提交时的正式 `SubjectVersion`。XW-0301 不实现 AI 生成、蒸馏或关键词额度扣减。

专属 PostgreSQL 验证：`scripts/test-keywords.ps1` / `scripts/test-keywords.sh`。

## Stage 2 内容生成、分发与完整报告分享

文章类型/模板、确认资料包、正文/大纲、固定质量规则、临时优化对比、五种文章导出、独立渠道适配、SSRF-safe 发布链接检测、白标和完整报告快照分享构成内容分发波次。图片 `XW-0710`—`XW-0717` 已按独立豆包 ImageGenerations adapter、capability runtime/credential binding、逐图额度、私有存储、审核、主体图库、普通衍生图和 ZIP 下载实现；真实 Stage/Production 凭据与 COS smoke 仍是 Stage 3 UAT gate，不使用占位图伪造交付。

安全、额度、迁移、部署、测试和精确拆分依据见 [docs/56-STAGE2-CONTENT-DISTRIBUTION-WAVE.md](docs/56-STAGE2-CONTENT-DISTRIBUTION-WAVE.md)。专属 PostgreSQL 验证：`scripts/test-stage2-content.ps1` / `scripts/test-stage2-content.sh`。

## Stage 3 商用运营、发布加固与代码侧 UAT

Stage 3 code-only 波次提供按 own/role/all 范围隔离的客户状态/标签、不可变联系记录、跟进、任务安全投影、文章/图片人工审核、公告、反馈、一次性只读协助视角、运营看板和经确认的脱敏 CSV 导出。发布就绪 API 与命令始终 fail closed；真实 COS、短信、Provider、worker 和恢复演练必须为同一完整 deploy SHA 留下短期不可变证据，否则状态保持 `NOT_READY`。

仓库内的发布脚本只提供 ff-only、exact-SHA、dirty tree、迁移感知回滚、备份目录校验及原子 `DEPLOYED_SHA` guard，本轮不代表执行过部署。详细边界见 [docs/58-STAGE3-RELEASE-HARDENING-UAT-WAVE.md](docs/58-STAGE3-RELEASE-HARDENING-UAT-WAVE.md)；隔离 PostgreSQL/Redis 验证运行 `scripts/test-stage3-release.ps1` 或 `scripts/test-stage3-release.sh`。
