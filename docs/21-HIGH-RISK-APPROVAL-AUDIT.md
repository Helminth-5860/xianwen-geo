# XW-0107 高风险审批与统一安全审计

## 范围

本任务提供固定高风险动作目录、三种风险保护模式、V1 双人审批和追加式统一安全审计。它不是通用 BPM、多级审批、会签或任意执行器。业务执行只能从 risk_handlers.py 的编译期静态注册表进入，数据库 handler_key 不能触发动态 import、URL、SQL、shell、Celery 名称或任意 callable。

首批 12 个动作由代码目录、迁移 Seed 和 sync_admin_rbac --apply 幂等同步共同管理。同步不会删除未知动作；系统检查会报告目录、策略、Handler 和数据库漂移。风险策略自身修改固定要求有效超级管理员、当前密码、真实 CSRF、expected_version 和显式确认，不能递归降级。

## 三种模式

目录内只有 `SMS_STEP_UP_REQUIRED_ACTIONS` 明确列出的安全关键动作，才在进入以下风险模式前
要求当前管理员 Session 绑定的 5 分钟短信 Step-Up proof；对应双人审批的发起人与执行审批者
应用相同 action-key 策略。普通业务高风险动作不默认触发短信，但现有 confirm/password/two_person
数据值与执行逻辑保持不变，避免 RiskPolicy 与历史审批记录的 schema/API 破坏；password 模式仍
保留当前密码再验证，two_person 仍要求另一名有效超级管理员。

- confirm：调用方显式传入 confirmed=true，在一个 PostgreSQL 事务中锁定策略和目标、执行领域服务并写入 AuditEvent。
- password：除目标版本外要求当前登录密码再验证。密码只存在于调用栈，不进入审批、审计、日志或前端持久化。
- two_person：原业务端点只创建 ApprovalRequest 并返回 202；必须存在另一名当前有效超级管理员。批准者不得是发起人，并需再次输入自己的当前密码。

模式强度固定为 confirm < password < two_person。当前策略必须属于动作支持模式且不低于最低模式。策略版本变化会使旧 pending 请求在批准时变为 stale。

## 审批状态机与事务

终态为 rejected、cancelled、expired、stale、executed 或 execution_failed，不保留长期 approved 状态。默认有效期为 24 小时；list、detail 和 approve 均会处理过期，不依赖 Celery。

批准过程使用外层事务和 ApprovalRequest 行锁。Handler 在 savepoint 内执行：

- 成功时领域状态、领域事件、AuditEvent 和 executed 同事务提交。
- Handler 失败时回滚 savepoint，外层只保存 execution_failed 和安全失败审计。
- 安全审计写入失败时整个外层事务回滚，业务状态不得放行。
- requester 权限、数据范围、目标版本、策略版本或 payload digest 变化时标记 stale。
- PostgreSQL 条件唯一约束阻止同一 requester/action/target/payload 的重复 pending 请求。

V1 不公开 POST /api/v1/admin/approvals。审批只能由现有业务动作端点发起；审批 API 仅支持 list、detail、approve、reject 和 cancel。

## Payload 与审计边界

每个动作使用独立 Serializer，拒绝未知字段、敏感字段、控制字符、HTML、URL、SQL 和代码/import 标记。canonical JSON 的 SHA-256 摘要同时绑定 action、目标、目标版本和安全 payload，批准执行前重新计算。

AuditEvent 只保存白名单 before/after/result 摘要、稳定错误码、不可逆 IP 指纹和 User-Agent 摘要。模型和 QuerySet 禁止普通 update/delete，API 只读且仅超级管理员可见。它不会保存完整 payload、手机号/IP、密码、验证码、Cookie、Session、challenge、API Key、基础设施密钥或原始异常。

本版本保留 UserStatusEvent、AdminRbacEvent 和 AdminSecurityEvent，不迁移、不删除、不回填伪历史。V1 不实现全局 hash chain、外部 WORM 或 SIEM；数据库管理员仍可能绕过应用层追加保护，因此生产保全需要备份、数据库权限隔离和后续外部不可变存储。

## 迁移与回滚

- users 0004 增加 status_version 和大于等于 1 的约束。
- admin_rbac 0006 创建 RiskAction、RiskPolicy、ApprovalRequest、AuditEvent、索引和基础约束。
- admin_rbac 0007 Seed 固定动作、默认策略和权限，反向为 RunPython.noop。
- admin_rbac 0008 增加审批人/发起人、状态时间和策略模式约束。

单独回退 Seed 不删除目录、默认策略或权限；这避免把仍被历史审批和审计引用的安全证据误删。完整回退建表迁移会删除审批和统一审计表及证据。生产环境优先前向修复或从经过验证的备份恢复；任何逆向迁移前必须完成影响审查和可恢复备份。本任务未连接腾讯云 PostgreSQL、Redis 或短信服务。

## 验收

PowerShell 运行 .\scripts\test-risk-approval.ps1，POSIX 运行 ./scripts/test-risk-approval.sh。

Compose risk-approval-test profile 执行 tests/test_risk_approval_postgres.py，覆盖并发批准 exactly-once、approve/cancel 竞态、目标/权限 stale、pending 条件唯一、Handler savepoint 回滚、AuditEvent 失败全事务回滚和既有 last-superuser 保护。GitHub Actions 的 Docker Compose Job 必须真实运行该套件并在结束后删除容器、网络和测试卷。


## 核验修复补充

- list、detail、approve、cancel 触发的 pending -> expired 全部进入同一事务服务：锁定审批、更新终态、追加一条 AuditEvent；审计失败时审批仍为 pending，重复检查不会重复审计。
- cancel 已过期审批稳定返回 410 APPROVAL_EXPIRED，不执行 Handler，也不写 cancelled_at。
- 批准时重新验证 approver 的完整管理员安全 Session、superuser 身份、active 状态和当前密码；disabled、locked、缺安全上下文、非 superuser、自批及错误密码均不能执行 Handler。
- pending 请求绑定 policy_version 和 two_person 模式；策略版本或模式变化会将旧请求标记 stale 并审计，不能因降级为 password 或升级为 two_person 绕过。
- 12 个既有业务入口按动作目录支持模式执行。confirm、password、two_person 及不支持模式均由参数化 HTTP 测试覆盖；管理员、角色和客户通用 PATCH 明确拒绝高风险字段、嵌套对象、别名及普通/高风险混合字段。
- 客户详情提供 customer.assignment.change 前端入口，只显示负责人昵称和脱敏手机号；分配、转交和解除都携带 expected_version，并复用统一 RiskActionButton。审批 payload 不写入 URL、localStorage 或 sessionStorage。
- payload 递归拒绝 password、current_password、sms_code、cookie/cookies、session/session_id、challenge/challenge_id、api_key、secret、private_key、access_token/refresh_token、sql、command、url/callback_url、import_path、callable，以及控制字符、HTML 和超限内容。
- OpenAPI 对 risk-actions、risk-policies、approvals 和 audit-events 的每个 operation 明确声明 401，并按实现列出 403/404/409/410/422/429/503；current_password 均为 writeOnly，仍无通用 POST approvals。

真实 PostgreSQL/Redis 专属套件现在为 15 项，包含 approve/expire 两种终态赢家、policy stale、disabled/locked approver、并发过期 exactly-once 审计与审计失败回滚。PowerShell 与 POSIX 脚本、Compose profile 和 GitHub Actions Docker Compose Job 均运行同一 tests/test_risk_approval_postgres.py，快速 SQLite 套件只收集并跳过这些专属测试。
