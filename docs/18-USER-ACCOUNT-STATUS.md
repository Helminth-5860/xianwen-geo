# XW-0104 用户账号状态管理

## 1. 账号流程

用户完成注册短信验证后直接进入正常状态并建立登录 Session，不经过人工账号审核。手机号
验证、验证码、密码校验和管理员安全验证继续独立执行。

后台只向运营人员展示“正常”和“禁用”：

- 正常：账号可以登录并按套餐、额度和业务资源状态使用功能。
- 禁用：账号不能登录，已有 Session 全部失效。

注销冷静期和已注销属于用户生命周期内部状态，不构成人工账号审核流程。

## 2. 状态变更

- `active -> frozen`：后台“禁用账号”，设置 `is_active=False` 并递增 `session_version`。
- `frozen -> active`：后台“恢复账号”，设置 `is_active=True`，不回退 Session 版本。

重复或非法转换返回 `ACCOUNT_STATE_CONFLICT`。`cancel_pending`、`cancelled` 不经账号禁用接口
转换。所有状态写操作使用数据库事务和行锁，并写入 `UserStatusEvent` 与固定安全通知。

## 3. 接口

管理员接口：

- `GET /api/v1/admin/users`
- `GET /api/v1/admin/users/{user_id}`
- `GET /api/v1/admin/users/{user_id}/history`
- `POST /api/v1/admin/users/{user_id}/freeze`
- `POST /api/v1/admin/users/{user_id}/unfreeze`

用户接口：

- `GET /api/v1/me`
- `GET /api/v1/notifications`
- `POST /api/v1/notifications/{notification_id}/read`

所有写操作使用 HttpOnly Session 和 CSRF。管理员接口继续执行 RBAC 和用户归属范围校验。

## 4. 数据迁移

前向迁移删除用户表的人工审核字段，清理账号审核历史事件和审核通知，并删除用户审核权限、
拒绝审核风险动作及其策略。现有用户的 `account_status`、`is_active`、Session 版本和业务数据
保持不变。历史 migration 文件不修改。

## 5. 验收

1. 注册验证成功后返回正常账号并可立即登录。
2. 用户响应、后台列表和详情不包含人工审核字段。
3. 人工审核和重新提交接口不存在。
4. 禁用用户会撤销旧 Session，恢复后必须重新登录。
5. 管理员只能管理授权范围内用户，跨管理员访问继续 fail closed。
6. 手机验证码与管理员安全验证测试继续通过。
