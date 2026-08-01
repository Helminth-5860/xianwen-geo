# XW-0111 套餐申请

## 边界

XW-0111 只建立 `PlanApplication` 与追加式 `PlanApplicationEvent`，统一 API 为
`/api/v1/plan-applications` 和 `/api/v1/admin/plan-applications`。本任务没有
Subscription、QuotaAccount、订单、支付、退款、发票或合同，也不会因申请、联系或关闭
自动授予、撤销任何套餐权益。试用套餐只公开展示“由管理员审核后发放”，不能通过本 API 申请。

## 资格与状态机

只有已认证普通用户、`is_active=true`、`account_status=active` 且审核状态为
pending/approved 可以创建申请。rejected、cancel_pending、frozen、cancelled、staff、
superuser 或存在 AdminProfile 的身份均失败关闭。active/cancel_pending 用户可以取消自己的
pending/contacted 申请；历史读取继续服从既有 Session 与账号状态边界。

状态只有 pending、contacted、closed、cancelled。管理员 contact 仅允许
pending→contacted，close 允许 pending/contacted→closed，用户 cancel 允许
pending/contacted→cancelled。重复或非法转换返回稳定 409，不提供 reopen、activate 或 DELETE。

## 幂等、版本绑定和并发

创建必须携带 16–128 字符的 `Idempotency-Key`。原文不进入日志或数据库；服务端从系统密钥
按用途派生 HMAC 子密钥，只保存摘要。唯一范围是 applicant + key digest。同 key、同 canonical
请求重放返回原记录（首次 201、重放 200），不同 payload 返回 IDEMPOTENCY_CONFLICT；不同 key
命中同用户同 Plan 的 open 条件唯一约束时返回 PLAN_APPLICATION_ALREADY_OPEN。

事务锁定 Plan 与 current published PlanVersion，并重新验证客户端提交的 plan_version_id。
申请只保存当前公开 Serializer 产生的最小快照、版本号和 config digest，不保存完整
effective_config。PostgreSQL trigger 禁止通过 save、update、bulk 或原始 SQL 修改绑定字段；
Plan 下架、归档、版本退休或发布新版本不会重绑旧申请。XW-0112 默认使用申请绑定版本，任何换版
都必须另行显式确认和审计。

## 范围、风险动作与安全数据

管理员 QuerySet 动态复用当前 CustomerAssignment：own、role、all 和 superuser 规则与 XW-0105
一致，未分配客户仅 all/superuser 可见；手机号筛选在 scoped QuerySet 后执行，越权详情与动作返回
404。申请表不复制负责人，负责人变化立即改变可见性。

`plan_application.contact` 与 `plan_application.close` 的默认及最低模式均为 confirm，可由
RiskPolicy 提高为 password/two_person。旧 HTTP 写入口必须经过统一风险编排、静态 Handler、严格
payload Serializer、scope 与 expected_version 重检。领域事件、固定模板 Notification、AuditEvent
与状态变化处于同一 PostgreSQL 事务；任一写入失败会回滚。完整手机号仅管理员详情按最小业务需要
返回，不进入 Event、AuditEvent、Notification 或日志；密码、Cookie、Session、幂等原文和摘要均
不在 API 返回。

## 迁移与回滚

plans 0004 创建申请、事件、索引和约束，0005 安装 PostgreSQL 不可变/追加式触发器；users 0005
增加固定通知类型与可空关联；admin_rbac 0010 幂等 Seed 权限、RiskAction 与默认 RiskPolicy。
Seed reverse 使用 noop，不单独删除可能已被审批或审计引用的代码目录证据；trigger reverse 只移除
数据库保护，不恢复或改写数据。完整回退基础迁移会丢失申请和历史证据。生产逆向迁移前必须审查
并备份，优先前向修复或备份恢复。本任务没有连接腾讯云 PostgreSQL/Redis。

## 验收

快速回归运行 `./scripts/check.sh all` 或 `./scripts/check.ps1 all`。真实 PostgreSQL 并发、动态 scope、
事务回滚和 trigger 使用 `./scripts/test-plan-applications.sh` 或
`.\scripts\test-plan-applications.ps1`；脚本使用随机本地凭证并在结束时执行
`docker compose down --volumes --remove-orphans`。Docker Compose Job 继续运行 RBAC、管理员安全、
高风险审批、套餐版本和套餐申请五层专属套件。
