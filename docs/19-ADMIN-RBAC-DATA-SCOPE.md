# XW-0105 管理员 RBAC 与客户数据范围

## 边界

管理员继续使用 `User` 的手机号、密码和 HttpOnly Session。`AdminProfile` 只保存独立管理
状态、单一角色和并发版本，不复制认证凭证。管理员 Step-Up、IP 白名单、确认／密码复核、密钥管理和
完整 CRM 不在本任务中。

## 权限与状态

超级管理员只由 Django `is_superuser` 识别，不依赖角色。普通管理员必须同时满足有效
AdminProfile、active 状态、staff、active Role 和 active Permission。权限目录由版本化
Seed 管理，明确区分 menu/action，普通角色不能绑定 superuser-only 权限。

管理员停用或锁定会在同一事务更新 AdminProfile、`is_staff` 和 `session_version`。全部旧
Session 立即失效，恢复后也不会重新有效。disable 要求先转交客户；紧急 lock 不受客户归属
阻止。最后一个有效超级管理员由 PostgreSQL 确定顺序行锁保护。


### Permission 状态的受控变更

Permission 状态只能通过 `admin_rbac.services.set_permission_status()` 修改；运维入口为：

```bash
python manage.py sync_admin_rbac --apply --permission-key users.freeze --permission-status inactive
```

禁止直接调用 `AdminPermission.save()` 修改状态。active -> inactive 会在同一 PostgreSQL 事务内锁定 Permission，并用数据库原子递增撤销实际绑定该权限的普通管理员 Session；重复停用幂等，重新启用不会恢复旧 Session。catalog 同步命令的状态选项复用同一服务，PostgreSQL 仍是唯一永久事实源。
## 客户范围

`CustomerAssignment` 保留一行当前唯一归属和单调 version。`owner_admin` 不可为空，并且只能
指向有效的非超级管理员 ADMIN；归属变更只更新既有记录而不删除后重建，从而避免 ABA。
ADMIN 只能看到直接归属自己的 USER，SUPER_ADMIN 可以看到全部 USER。该范围统一应用到用户列表、
详情、历史、审核和冻结 QuerySet；无权对象返回 404，手机号精确过滤不能扩大范围。

本任务只保存当前负责人及最小追加式 `AdminRbacEvent`。XW-0901 在此基础上扩展完整转交
历史、客户状态、联系记录和待办。

## 并发与验收

管理员、角色和归属写操作要求 expected_version。角色权限、数据范围、管理员角色或状态
变化会递增受影响用户的 session_version。PostgreSQL 是永久事实来源，本任务不缓存 RBAC。

真实 PostgreSQL 专属测试通过以下仓库资产重复执行：

```powershell
.\scripts\test-postgres-rbac.ps1
```

```bash
./scripts/test-postgres-rbac.sh
```

脚本使用隔离的 Compose `rbac-test` profile，不包含生产凭证或本机绝对路径。

## 回滚

优先 revert 应用提交。逆向迁移会删除角色、权限绑定、管理员资料、当前客户归属和最小
RBAC 事件，执行前必须备份。回滚不会创建或恢复任何密码、Cookie 或 Session。

### 0002 数据迁移的回滚限制

`0002_seed_catalog_and_profiles` 有意使用 `RunPython.noop`，不提供可能错误恢复权限的危险反向写入：

- 单独回退 0002 不恢复迁移时被安全收敛的普通 staff 身份。
- 单独回退 0002 不删除 Permission Seed 或 AdminProfile。
- 完整回退 0001 会删除全部 RBAC 表、归属和 RBAC 事件证据。
- 生产环境优先采用前向修复或从经过验证的备份恢复，不应盲目执行逆向迁移。
- 任何逆向迁移前必须审查影响并完成可恢复备份。
- 本任务及回滚验证均未连接腾讯云 PostgreSQL。
