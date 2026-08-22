# XW-0104 用户审核与账号状态管理

## 1. 边界

本任务实现用户审核、拒绝后重新提交、账号冻结/解冻、追加式状态历史、最小站内通知和
最小管理员页面。管理员 API 仅允许有效 `is_staff` 用户访问；完整 RBAC、管理员账号管理、
套餐、额度、主体和 AI 权限不在本任务中。

当前用户端点保持为 `GET /api/v1/me`，没有新增 `/api/v1/auth/me`。

当前注册策略的新增账号在短信验证成功后直接进入 `approved/active`，不再把普通首次登录
置于管理员审批之后。pending/rejected 转换、历史事件、筛选与人工审核 API 均为历史账号
和特殊治理场景兼容保留；本轮没有批量修改任何既有 pending 数据。

## 2. 状态机

审核状态和账号状态相互独立：

- `pending -> approved`：写入 `approved_at`、`approved_by`，清除当前拒绝原因。
- `pending -> rejected`：拒绝原因必填，清除 `approved_at`、`approved_by`。
- `rejected -> pending`：用户重新提交，可选在同一事务更新昵称，历史原因保留。
- `active -> frozen`：设置 `is_active=False` 并递增 `session_version`。
- `frozen -> active`：设置 `is_active=True`，不回退 Session 版本。

重复、过期或跨越状态的操作分别返回 `APPROVAL_STATE_CONFLICT` 或
`ACCOUNT_STATE_CONFLICT`。`cancel_pending`、`cancelled` 不经冻结接口转换，`cancelled`
不能解冻。审核状态不影响登录资格；账号状态控制登录资格。

所有状态写操作经过统一领域服务，使用 `transaction.atomic()` 和 `select_for_update()`。
用户当前状态、`UserStatusEvent` 和需要的 `Notification` 在同一 PostgreSQL 事务提交。

## 3. Session 全量失效

密码登录、短信登录和注册自动登录都会把用户当前 `session_version` 写入固定 Session 键。
Session 版本中间件在 Django 完成 Session 和用户认证后集中校验：

- 缺失、非正整数或不匹配时执行 logout/flush，并按匿名请求处理。
- 不遍历 Session 表，不反序列化任意 Session 内容。
- 不记录 Session ID 或版本值。

冻结与建立登录会话都锁定用户行。无论登录还是冻结先取得锁，冻结完成后所有旧 Cookie
下一次请求均返回 401。解冻不恢复旧 Cookie，用户必须重新登录。密码重置继续依赖 Django
密码认证哈希撤销旧 Session，并有回归测试覆盖。

## 4. 历史和通知

`UserStatusEvent` 按审核域和账号域记录 from/to 状态、事件类型、原因、操作者、request_id
和时间。普通 API 只提供分页读取，不提供更新或删除。拒绝原因限制 500 字符，拒绝控制字符
和 HTML；服务端日志不记录原因正文。

`Notification` 仅支持审核通过、审核拒绝、账号冻结和账号解冻四种固定安全模板。
`safe_summary` 不复制拒绝原因。用户只能读取和标记自己的通知，本任务不发送短信。

## 5. API 和权限

管理员接口：

- `GET /api/v1/admin/users`
- `GET /api/v1/admin/users/{user_id}`
- `GET /api/v1/admin/users/{user_id}/history`
- `POST /api/v1/admin/users/{user_id}/review`
- `POST /api/v1/admin/users/{user_id}/freeze`
- `POST /api/v1/admin/users/{user_id}/unfreeze`

用户接口：

- `GET /api/v1/me`
- `POST /api/v1/me/approval/resubmit`
- `GET /api/v1/notifications`
- `POST /api/v1/notifications/{notification_id}/read`

所有写操作使用 HttpOnly Session 和真实 CSRF。管理员列表默认不包含 staff/superuser，
状态服务也会再次锁定并确认 actor 仍是有效 staff，同时拒绝把 staff/superuser 作为业务
审核或冻结目标。

管理员列表支持审核状态、账号状态、规范化完整手机号精确筛选，以及 `page`、`page_size`
分页；每页最大 100。响应仅返回脱敏手机号，不返回 Session、安全凭据或权限集合。

## 6. 日志边界

结构化日志可记录 request_id、动作、用户 UUID、管理员 UUID、事件 UUID 和稳定错误码。
不得记录完整手机号、拒绝原因、密码、验证码、Cookie、CSRF Token、Session ID 或
Session 版本。请求完成日志只记录 URL path，不记录手机号查询字符串。

## 7. 迁移与回滚

迁移新增 `User.approved_by`、`User.session_version`、`UserStatusEvent` 和 `Notification`。
已有用户的 Session 版本为 1，不补造历史事件。支持全新 PostgreSQL 从零迁移及 develop
数据库向前升级。

回滚优先 revert 应用提交。逆向迁移会删除状态历史和通知数据，执行前必须备份并接受
数据丢失；不得对腾讯云数据库执行本任务迁移或清理。

## 8. 手工验收

1. 管理员查看 pending 列表和脱敏详情。
2. 拒绝用户，确认当前原因、追加历史和安全通知。
3. 用户可修改昵称并重新提交，手机号保持不变。
4. 管理员通过审核，确认 approved_at 和 approved_by。
5. 同一用户建立两个 Session，冻结后两个旧 Cookie 均返回 401。
6. 解冻后旧 Cookie 仍返回 401，新登录成功。
7. 并发 approve/reject、resubmit/review、freeze/unfreeze 只有合法状态转换成功。
8. 管理员页面完成列表、详情、审核、冻结、解冻和通知流程。
9. production JSON 日志不出现完整手机号、拒绝原因、Cookie 或 Session 信息。

Compose 验收结束后执行：

```powershell
docker compose down --volumes --remove-orphans
```
