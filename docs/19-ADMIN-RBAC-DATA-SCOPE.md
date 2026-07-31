# XW-0105 管理员 RBAC 与客户数据范围

## 边界

管理员继续使用 `User` 的手机号、密码和 HttpOnly Session。`AdminProfile` 只保存独立管理
状态、单一角色和并发版本，不复制认证凭证。管理员 2FA、IP 白名单、双人审批、密钥管理和
完整 CRM 不在本任务中。

## 权限与状态

超级管理员只由 Django `is_superuser` 识别，不依赖角色。普通管理员必须同时满足有效
AdminProfile、active 状态、staff、active Role 和 active Permission。权限目录由版本化
Seed 管理，明确区分 menu/action，普通角色不能绑定 superuser-only 权限。

管理员停用或锁定会在同一事务更新 AdminProfile、`is_staff` 和 `session_version`。全部旧
Session 立即失效，恢复后也不会重新有效。disable 要求先转交客户；紧急 lock 不受客户归属
阻止。最后一个有效超级管理员由 PostgreSQL 确定顺序行锁保护。

## 客户范围

`CustomerAssignment` 保留一行当前归属和单调 version。`owner_admin=null` 表示未分配，不
删除后重建，从而避免 ABA。own、role、all 和超级管理员范围统一应用到 XW-0104 用户列表、
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
