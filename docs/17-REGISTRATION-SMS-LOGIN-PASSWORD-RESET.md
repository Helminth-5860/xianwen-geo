# XW-0103 注册、短信登录和密码重置

## 范围

XW-0103 在 XW-0101 会话认证和 XW-0102 短信挑战基础上交付：

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login/sms`
- `POST /api/v1/auth/password/reset`
- `/register`、`/login`、`/forgot-password`
- purpose-aware 短信发送策略
- 按用途隔离的认证提交失败限流

本任务不包含用户审核后台、套餐、额度、主体、修改手机号、设备管理、账号注销或真实腾讯云短信 Provider。

## 注册

注册请求包含手机号、昵称、register 用途验证码和密码。昵称 trim 后不能为空、不能包含
控制字符且最大 50 字符；密码使用 Django 官方验证器和哈希体系。

验证码先在 Redis 原子消费，再执行 PostgreSQL 事务。手机号唯一约束是最终并发保护。
两者不存在分布式事务：数据库失败或唯一约束冲突时不恢复验证码，用户需要重新获取。
手机号已注册仅在有效验证码消费后返回 `409 ACCOUNT_ALREADY_EXISTS`。

新用户使用 UUID；当前 Auth Policy 在 register 验证码成功消费后直接写入
`approval_status=approved`、`account_status=active` 和 `approved_at`，注册成功后
通过 Django `login()` 建立最长 12 小时、浏览器关闭失效的 HttpOnly Session。注册不创建
套餐、额度、试用或主体记录。

## purpose-aware 短信发送

- register：格式合法即真实发送，即使手机号已注册。
- login：仅存在且未 cancelled 的用户真实发送。
- password_reset：存在且未 cancelled 的用户真实发送；frozen 仍可接收。

被抑制的 login/password_reset 请求仍通过同一 Redis Lua 路径占用手机号、IP、组合周期限流
和 60 秒冷却，但删除旧挑战、不创建新挑战、不调用 Provider，并返回与真实发送相同的 Envelope。
Provider 本地不可用在任何计数前返回通用 503，不伪装成发送成功。

## 短信登录

login 验证码原子消费后查询用户。不存在用户不自动创建；无效、过期、重放验证码及不存在
用户统一返回 `401 AUTH_CREDENTIALS_INVALID`。active/cancel_pending 可登录，frozen/cancelled
返回 `403 ACCOUNT_UNAVAILABLE`，审核状态不影响登录。历史 pending/rejected 用户不会被本轮
自动迁移；审核字段与后台治理继续作为兼容状态和人工风险处置能力保留。

成功调用 Django `login()` 轮换 Session ID，并写入 `LoginEvent(login_method=sms)`；事件写入
失败时立即 logout，客户端只收到通用 500。

## 密码重置

password_reset 验证码成功消费后，存在且未 cancelled 的用户在 PostgreSQL 事务中调用
`set_password()`。frozen 用户可重置但保持冻结；不存在或 cancelled 用户不创建、不修改，
对外返回相同的 `{"reset": true}`。

重置不自动登录，也不调用 `update_session_auth_hash`。密码哈希变化使所有旧 Session 在后续
认证请求时失效。数据库失败时验证码保持已消费。

## 提交失败限流

register、login、password_reset 使用独立命名空间，默认均为：

- 手机号+IP：15 分钟 5 次失败
- 手机号：15 分钟 10 次失败
- IP：15 分钟 30 次失败
- 命中后限制 15 分钟

仅无效验证码/凭证计数；普通 Serializer 422、503 和业务冲突不计数。有效验证后清理组合
短期失败计数。Key 只包含服务端 HMAC 指纹，Redis 不可用时失败关闭。

## CSRF、Cookie 和前端

三个 POST 均允许匿名访问但显式执行真实 CSRF。前端集中客户端先获取 `/auth/csrf`，所有
请求使用 `credentials: include` 和 `X-CSRFToken`。不使用 JWT、localStorage Token 或大型
状态管理库。短信成功后按服务端 `resend_after` 开始倒计时；429/503 不伪造倒计时。

Session Cookie 继续使用 `xianwen_session`、HttpOnly、SameSite=Lax、host-only；production
强制 Secure。浏览器代码不包含 Mock outbox 或固定验证码。

## 迁移

`users.0002_alter_loginevent_login_method` 仅将 LoginEvent method choices 从 password 扩展为
password/sms，不新增业务表或验证码表。

## 验收

完整质量门禁运行 `./scripts/check.ps1 all`。Compose 联合验收使用隔离的本地 PostgreSQL 和
Redis；Mock 验证码只允许在同一测试进程通过依赖注入 outbox 获取，不增加公开 HTTP 路由。
