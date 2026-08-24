# XW-0112 用户订阅

## 边界

本任务只建立订阅事实、正式申请激活和管理员试用发放。状态仅为
active / expired / terminated。不包含额度账户、订单、支付、续费、升级、
覆盖、周期重置或 XW-0115 到期任务。

## 事实与状态机

- 正式订阅只可由 PlanApplication 的 pending/contacted -> activated 创建。
- 试用是唯一允许 source_application=NULL 的订阅。
- 创建即 active；只允许 active -> expired/terminated。
- 用户当前订阅查询使用 active、starts_at <= now、ends_at > now，且 GET 不写数据库。
- 同一用户至多一个 active，同一来源申请至多一个订阅，同一用户历史至多一次试用。
- 到期开通新订阅时，在 User 行锁内先写 expired 及事件，再创建新订阅。

## 事务和锁

正式开通在一个 PostgreSQL 事务内创建 Subscription，将申请置为 activated，追加
SubscriptionEvent、PlanApplicationEvent、Notification，并由风险执行器追加
AuditEvent。任一步失败都整体回滚。

套餐锁顺序统一为 Plan -> PlanVersion。订阅并发入口还使用 User 行锁及数据库条件
唯一约束；Redis 不是订阅事实来源。

## 版本与快照

默认严格使用申请永久绑定的 requested_plan_version，完整复制 immutable
effective_config 并重算验证 SHA-256 digest。不会静默切换最新版本。

- archived 套餐禁止激活。
- offline 套餐或 retired 版本要求额外确认和原因。
- override 仅允许同一 Plan 的 published/retired 版本，需要独立权限、显式确认、
  原因及页面二次确认。
- 原申请版本绑定永不修改。

## 风险、权限和数据范围

subscription.open、subscription.grant_trial、subscription.terminate 的
supported/default/minimum mode 均固定为 confirm，换版另需
subscriptions.override_version。

订阅列表、详情和动作复用 CustomerAssignment own/role/all 数据范围，越权对象返回
404。直接执行阶段重新验证操作人权限、数据范围、目标版本、状态和单 active 约束。

## API

- GET /api/v1/subscription
- GET /api/v1/admin/subscriptions
- GET /api/v1/admin/subscriptions/{id}
- POST /api/v1/admin/plan-applications/{id}/activate
- POST /api/v1/admin/users/{id}/subscriptions/trial
- POST /api/v1/admin/subscriptions/{id}/terminate

写接口使用完整管理员 Session、CSRF、expected_version 和统一 Envelope。用户响应
不返回完整 entitlement snapshot、digest、内部备注或风险 payload。

## 数据库防护与回滚

PostgreSQL 触发器禁止 Subscription DELETE，禁止终态回到 active，禁止改写用户、
套餐、套餐版本、来源申请、权益快照/digest、起止时间和试用标志等绑定字段；
SubscriptionEvent 禁止 UPDATE/DELETE；activated 申请不能回退。

迁移回滚会删除订阅表及订阅历史证据，因此生产环境必须先审查和备份，优先使用
前向修复或备份恢复。代码目录 Seed 采用 no-op reverse，单独回退不会删除权限和
风险目录记录。本任务未连接腾讯云 PostgreSQL 或 Redis。

## 时间与安全日志

开通使用 timezone-aware 当前时间；结束时间为本地日历起点加 valid_days 后转换回
同一时区。cycle_anchor_day 只作为后续周期输入；本任务不执行月度周期重置。
审计和事件只保存白名单摘要、稳定错误码、actor/request_id 和记录 ID，不保存完整
权益快照、digest、手机号、Cookie、密码、验证码或审批原始 payload。
