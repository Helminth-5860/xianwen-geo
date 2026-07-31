# XW-0101 用户模型与密码会话认证

## 范围

XW-0101 建立后续账号功能复用的用户身份基础：

- UUID 自定义用户模型
- 中国大陆手机号规范化与唯一约束
- Django 官方密码哈希和验证器
- 密码登录、当前会话退出、CSRF 获取和当前用户 API
- HttpOnly Django Session Cookie
- Redis 登录失败限流
- 只追加登录事件

本任务不实现注册、短信发送、短信登录、密码重置、设备管理、手机号修改、
账号注销、审核后台、套餐、额度或主体业务。

## 手机号

仅支持满足 `^1[3-9]\d{9}$` 的中国大陆手机号。输入可包含 `+86`、`0086`、
普通空格或短横线，保存前统一规范化为 `+8613800138000` 形式。

用户表对规范化结果建立唯一约束。手机号不是主键。登录事件和 Redis Key
只使用基于服务端秘密的 HMAC-SHA256 指纹；应用日志不记录完整手机号。

## 用户状态

审核状态与账号状态是两个独立字段：

- `approval_status`: `pending/approved/rejected`
- `account_status`: `active/frozen/cancel_pending/cancelled`

`active` 和 `cancel_pending` 对应 `is_active=True`；`frozen` 和 `cancelled`
对应 `is_active=False`。Manager 状态服务、模型保存逻辑和数据库约束共同防止
两个字段漂移。审核状态不影响是否允许登录。

## Session 和 CSRF

- 只使用 Django SessionAuthentication，不启用 BasicAuthentication 或 JWT。
- Session Cookie 名为 `xianwen_session`，HttpOnly、SameSite=Lax、Path=/、
  host-only；production 强制 Secure。
- Cookie 在浏览器关闭后失效；服务端绝对有效期为登录后 12 小时，不滑动续期。
- CSRF Cookie 名为 `xianwen_csrf`，允许前端读取并通过 `X-CSRFToken` 回传；
  production 强制 Secure。
- 密码登录和退出都执行真实 CSRF 校验。
- Django 在登录时轮换 Session ID 和 CSRF Token，前端登录成功后应读取最新
  `xianwen_csrf` Cookie。

## API

- `GET /api/v1/auth/csrf`
- `POST /api/v1/auth/login/password`
- `POST /api/v1/auth/logout`
- `GET /api/v1/me`

所有 JSON 响应使用统一 Envelope，并返回相同的 `X-Request-ID`。不存在手机号、
错误密码、冻结和已注销账号均使用相同的外部凭证错误提示。

`/api/v1/me` 只返回 ID、昵称、脱敏手机号、审核状态和账号状态。

## 登录限流

Redis 固定窗口默认配置：

- 手机号与 IP 组合：15 分钟 5 次失败
- 单手机号：15 分钟 10 次失败
- 单 IP：15 分钟 30 次失败
- 命中后限制 15 分钟

阈值可通过环境变量调整。命中后统一返回 429，不公开具体阈值。成功登录只清理
对应手机号/IP组合的短期计数。production Redis 不可用时登录失败关闭并返回
通用 503。

## 本地验收

完整门禁：

```powershell
.\scripts\check.ps1 all
```

Compose 联合验收必须使用全新本地 PostgreSQL 数据卷和真实 Redis，不得连接或
清空云数据库。获取 CSRF 后使用 Cookie Jar 完成登录、`/me` 和退出流程，并核对
Session ID/CSRF Token 轮换、Cookie 属性、登录事件及日志脱敏。
