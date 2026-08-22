# 管理员密码登录、SMS Step-Up 与 IP 白名单

## 安全边界

管理员使用独立的 `/api/v1/admin/auth/*` 入口。普通用户登录入口在有效凭证或有效短信挑战后识别 `is_superuser`、`is_staff` 或既存 `AdminProfile`，阻止管理员身份建立普通 Session；公开短信发送不会接受 `admin_step_up` 用途，也不会向管理员身份实际发送普通登录验证码。

有效管理员提交正确密码并通过账号、AdminProfile、角色和 IP 白名单检查后，直接建立 password Session；登录、进入 dashboard 和普通低风险读取不会创建 challenge 或发送短信。历史 `require_sms_2fa` 字段与安全版本语义兼容保留，但不再作为登录门禁。短信只用于已认证管理员的安全关键 Step-Up；业务高风险动作不默认发短信，继续执行既有确认、当前密码、双人审批、目标/策略版本检查和追加式审计。local/test 使用随机 Mock outbox，production 未配置真实 Provider 时 Step-Up 失败关闭并返回通用 503，普通密码登录仍可用。本任务没有接入腾讯云短信密钥，也没有绕过、信任设备或万能验证码。

## Step-Up challenge、proof 与管理员 Session

密码登录与 Step-Up 端点都需要真实 CSRF。只有持有有效管理员 Session 的调用方才能请求 `/admin/auth/step-up/challenge`；该显式请求创建一次 256-bit 以上随机 challenge 并发送短信。Redis Key 使用 HMAC 指纹；challenge 绑定用户、Session/Profile/Role/Policy 版本、IP 指纹、User-Agent 摘要和安全上下文版本，TTL 为 300 秒。短信摘要绑定 challenge、用户、`admin_step_up` 用途和 generation；Lua 完成发送保留/条件激活、错误计数和一次性消费，并处理 EVALSHA/NOSCRIPT。Redis 故障失败关闭。

challenge 只保存在后台 Step-Up React 对话框内存，不进入 URL、localStorage、sessionStorage、Cookie 或日志。验证码正确消费后，服务端 Session 获得最长 300 秒的 proof；proof 绑定管理员、Session/Profile/Role/Policy 版本、IP 与 User-Agent，过期或上下文变化返回 `ADMIN_STEP_UP_EXPIRED`。验证码不能重放，proof 不由前端 flag 决定。

完整管理员 Session 除 Django 身份和 `session_version` 外，还保存非敏感的管理员认证标志、认证时间、Profile/Role/Policy 版本、认证因子和 IP 指纹。所有后台业务 API 集中校验这些值并在每次请求重新执行 IP 白名单判断。部署前旧 staff Session、普通用户被提升 staff 前的 Session，以及安全版本变化前的 Session 均不能访问后台。

## 角色与超级管理员策略

角色分别维护资料/权限 `version` 与安全 `security_version`。兼容的 `require_sms_2fa`、IP 开关或 CIDR 条目变化会在 PostgreSQL 事务内递增 `security_version`，并使用数据库原子表达式递增受影响普通管理员的 `session_version`。每个超级管理员拥有独立 `SuperuserSecurityPolicy`；其策略变化只撤销自己的旧 Session。`SMS_STEP_UP_REQUIRED_ACTIONS` 集中冻结需要短信的 Catalog 子集：`admin.disable`、`admin.lock`、`admin.role.change`、`admin.force_logout`、`role.permissions.replace`、`role.disable`、`role.security.update`、`role.ip_allowlist.update`、`superuser.ip_allowlist.update`、`user.freeze`、`quota.grant`、`quota.compensate`、`quota.manual_deduct`、`subject_risk.catalog.publish`。管理员/RBAC 状态治理、AI credential/runtime 写入、credential capability binding 和敏感 support-view 继续由直接 API 权限层强制 Step-Up。

`customer.assignment.change`、用户审核拒绝、套餐及套餐版本日常管理、套餐申请联系/关闭和订阅生命周期动作不在短信集合内；它们仍按冻结 RiskPolicy 执行 confirm/password/two_person、current-password、双人审批、乐观版本检查及审计。审批批准端根据待执行 `action_key` 应用相同集中策略，不会把业务审批重新升级为 blanket SMS gate。

CIDR 使用 Python `ipaddress` 规范化，支持 IPv4/IPv6，主机转换为 `/32` 或 `/128`。拒绝域名、通配符、正则、控制字符和无效 CIDR。条目只做 active/inactive，不提供物理删除；恢复相同 CIDR 复用原记录。启用白名单通常要求至少一个 active 条目。

所有策略写操作仅允许有效超级管理员、真实 CSRF、短时 Step-Up proof、`current_password` 和 `expected_security_version`。current_password 作为纵深再认证保留，错误使用 Redis/HMAC 短期限流且不持久化密码。新配置排除当前 IP 时先返回 `IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED`；只有显式 `confirm_lockout=true` 才执行并撤销相关 Session。

客户端 IP 继续复用可信代理解析：默认只使用 `REMOTE_ADDR`，仅在可信代理 CIDR/跳数满足时读取 X-Forwarded-For。数据库读取失败或白名单无法判定时失败关闭。日志与追加式 `AdminSecurityEvent` 仅保存 IP HMAC 指纹、设备摘要、稳定事件类型和版本，不保存完整 IP/手机号、密码、验证码、challenge、Cookie 或 Session ID。

## 强制退出与紧急恢复

`POST /api/v1/admin/admins/{id}/force-logout` 仅超级管理员可用，通过 `session_version + 1` 撤销目标全部设备，不遍历 Session。对自己执行不会改变账号有效性，但当前旧 Session 下一次请求失效。

服务器控制台紧急恢复命令仅关闭一个角色或超级管理员策略的 IP 白名单，不关闭高风险 Step-Up，不生成 bypass token：

```powershell
python manage.py recover_admin_ip_allowlist --role-id <uuid> --dry-run
python manage.py recover_admin_ip_allowlist --role-id <uuid>
python manage.py recover_admin_ip_allowlist --superuser-id <uuid> --dry-run
```

命令幂等；实际执行递增安全版本和受影响用户 `session_version`，并追加 `emergency_recovery_used`。输出不包含手机号、IP、凭证或安全条目。

## 验收

快速测试仍可使用 SQLite。并发、Lua、真实 Session/IP 与事务边界必须通过隔离 Compose PostgreSQL/Redis：

```powershell
.\scripts\test-admin-security.ps1
```

```bash
./scripts/test-admin-security.sh
```

CI 保持 Backend、Frontend、Security、Docker Compose 四个 Job；Docker Compose Job 必须明确执行 `tests/test_admin_security_postgres.py` 并全部通过。

## 迁移与回滚

`0004` 增加角色安全字段、角色/超级管理员 CIDR、超级管理员策略和追加式安全事件；`0005` 为已有 superuser 初始化默认关闭 IP 白名单的策略。新角色默认 `require_sms_2fa=false`、IP=false；字段为历史兼容保留。当前 Step-Up proof 复用 server-side Session 和既有 Redis challenge，不新增数据库字段，因此本轮无需 migration。

`0005` 的反向操作有意为 `RunPython.noop`，单独回退不会删除已创建的 superuser policy，避免在旧代码仍可能运行时移除安全事实。完整回退 `0004` 会删除白名单、策略与安全事件证据，并移除角色安全字段。生产环境应优先前向修复或从已验证备份恢复；任何逆向迁移前必须审查、停写并备份。当前实现和验收不连接、迁移或清理腾讯云 PostgreSQL/Redis。
