# XW-0102 短信验证码抽象与 Mock

## 范围

XW-0102 提供短信验证码发送和内部验证消费基础：

- `POST /api/v1/auth/sms/send`
- `register/login/password_reset` 三种用途
- Redis 临时挑战、冷却和周期限流
- local/test Mock Provider
- production Provider 协议和未配置实现
- 供 XW-0103 调用的 `verify_and_consume`

本任务不实现注册、短信登录、密码重置、修改手机号、真实腾讯云短信、前端认证页面、
套餐、额度或审核后台。验证码不保存到 PostgreSQL。

## Provider

`SmsProvider` 只在调用栈内接触规范化手机号和随机验证码。`MockSmsProvider` 将消息
保存在测试进程内 outbox，供依赖注入的自动化测试读取；没有公开 outbox HTTP 路由，
也不会把验证码写入日志。`UnavailableSmsProvider` 在任何 Redis 计数前返回服务不可用。

production 禁止 `SMS_PROVIDER=mock`。未配置真实 Provider 时应用仍可启动，但发送接口
统一返回 `503 SERVICE_TEMPORARILY_UNAVAILABLE`。真实腾讯云适配器属于 XW-1002。

## 验证码和 HMAC

- 验证码由 `secrets.randbelow` 生成并格式化为 6 位数字。
- 有效期 300 秒，错误上限 5 次，发送冷却 60 秒。
- `SMS_VERIFICATION_HMAC_KEY` 是独立服务端密钥；production 必填、检查强度，并拒绝
  复用 Django 密钥、数据库凭证或 Redis 凭证。
- 主密钥按标签派生手机号、IP、手机号与 IP 组合及验证码摘要四个子密钥。
- 验证码摘要包含手机号、用途、generation ID 和验证码，阻止跨用途或跨代复用。

## 客户端 IP

默认只使用 `REMOTE_ADDR`，完全忽略客户端提供的 `X-Forwarded-For`。
启用 `TRUSTED_PROXY_HOPS` 时，`REMOTE_ADDR` 还必须属于 `TRUSTED_PROXY_CIDRS`；
只有受信代理链才按从右侧计算的跳数取客户端 IP。生产 Nginx 必须覆盖或追加
`X-Forwarded-For`，并禁止客户端直接访问应用容器。

## Redis

Key 使用 `auth:sms:v1` 前缀，手机号和 IP 只以 HMAC 指纹出现：

```text
auth:sms:v1:code:<phone_fp>:<purpose>
auth:sms:v1:cooldown:<phone_fp>
auth:sms:v1:limit:phone:<phone_fp>
auth:sms:v1:limit:ip:<ip_fp>
auth:sms:v1:limit:combination:<phone_ip_fp>
```

发送预约 Lua 脚本原子检查冷却/周期阈值、递增计数并设置 TTL，再写入
`generation_id/code_digest/state=pending/attempts=0`。Provider 成功后由条件 Lua
脚本激活同一 generation；旧 Provider 结果不能激活新 generation。

Provider 本地不可用不消耗计数。实际调用失败或超时保留发送计数、删除匹配 generation，
并返回通用 503。

验证消费 Lua 脚本只接受当前 active generation：错误时原子递增 attempts，第 5 次立即
删除；正确时原子删除并仅返回一次成功。Redis 不可用时失败关闭，不回退 LocMem 或数据库。
Lua 使用 `EVALSHA`，遇到 `NOSCRIPT` 自动重新加载。

## API

请求：

```json
{"phone":"13800138000","purpose":"register"}
```

成功：

```json
{
  "success": true,
  "data": {"sent": true, "expires_in": 300, "resend_after": 60},
  "request_id": "uuid"
}
```

接口 `AllowAny`，但作为状态修改请求强制真实 CSRF。三种用途响应一致，不查询或暴露账号
是否存在；不返回验证码、Provider 结果或具体限流阈值。

## XW-0103 用途策略扩展

XW-0103 保持公开成功 Envelope 不变，并在发送前增加内部用途策略：register 始终真实发送；
login/password_reset 对不存在或 cancelled 账号抑制发送。抑制路径仍原子消耗相同冷却和三维
周期限流，但不创建挑战、不调用 Provider，并删除该用途旧挑战。Provider 明确不可用仍返回
503。该策略用于阻止不存在账号取得可消费挑战，详情见
`17-REGISTRATION-SMS-LOGIN-PASSWORD-RESET.md`。
## 默认限流

- 手机号与 IP 组合：15 分钟 5 次
- 手机号：1 小时 10 次
- IP：1 小时 60 次

三个周期维度跨用途共享；验证码状态按手机号与用途隔离。阈值可由服务端环境变量调整，
对外只返回通用 429。

## 验收

完整门禁：

```powershell
.\scripts\check.ps1 all
```

Compose 验收必须使用本地真实 Redis。不得通过跨 Gunicorn 进程读取 Mock outbox 伪造
端到端结果；应在同一容器进程内注入 Mock Provider，验证 Redis TTL、旧码替换、五次失败、
并发单次消费和重放失败。停止 Redis 后发送接口必须返回通用 503。验收结束删除本地容器
和数据卷。
