# XW-0114 套餐变更

## 范围

XW-0114 实现管理员发起的续费、升级、降级、替换和试用转正式，以及用户只读变更记录。
它不实现 Beat、自动到期、自动周期推进、scheduled change 自动执行、订单或支付。

套餐变更事实保存在 `SubscriptionChange`，状态只有 `scheduled`、`executed`、`cancelled`。
它只保存确认后的领域事实，不创建等待队列。执行后的新订阅通过
`Subscription.source_change -> SubscriptionChange.from_subscription` 形成不可变链，不伪造
`PlanApplication`。

## 状态、分类与生效

- renewal 只允许 current-end 排期，不提前创建 Subscription 或 QuotaAccount。
- upgrade、downgrade、replacement 立即执行并继承旧订阅 `ends_at` 和周期锚点。
- trial_conversion 立即执行，结束时间为执行时间加目标 `valid_days`，锚点重置为上海本地日。
- 服务端按 Limit Catalog 和模型权限重新分类；同时有升有降固定为 replacement，不使用价格推断。
- 目标 PlanVersion 必须明确提交。archived/draft 拒绝；offline/retired 必须额外确认和原因。

`SubscriptionChange` 的 executed/cancelled 是不可逆终态，`SubscriptionChangeEvent` 只追加。
同一来源订阅最多一个 scheduled/executed 后继。相同派生幂等摘要重放原结果，不同 payload 稳定冲突。

## 权限、确认与安全

公开管理员动作只有 `subscription.change` 和 `subscription.change.cancel`，两项
supported/default/minimum 都固定为 `confirm`。执行阶段重新校验完整
管理员 Session、`subscriptions.change`、own/role/all 客户范围、对象级 404、来源状态和版本。
所有 POST 要求真实 CSRF；change/cancel 还要求 `Idempotency-Key` 与 `expected_version`。

原始 Idempotency-Key 只在请求调用栈内使用。数据库、AuditEvent、Notification、
日志和响应只接收带 key version 的 HMAC 摘要及 canonical request digest。前端每次动作在内存生成
随机键，不写 URL、localStorage 或 sessionStorage。

## 事务与锁

立即执行统一按以下顺序加锁：

`Plan -> PlanVersion -> User -> Subscription -> QuotaAccount(UUID) -> QuotaHoldGroup -> QuotaHold(UUID)`

风险 Handler 是静态 action-key 注册表。执行前重新计算分类和快照 digest，并拒绝存在
open/partially-settled Hold 或 `frozen != 0` 的来源订阅；系统不会自动释放 Hold。
Subscription、SubscriptionChange/Event、QuotaAccount/Ledger/Transfer、Notification 和 AuditEvent
处于一个 PostgreSQL 事务；失败注入时整体回滚。

## 额度迁移

- overwrite：用 `plan_change_forfeit` 将仍可用旧余额归零。
- accumulate：用不可变 `QuotaTransfer` 绑定成对 `transfer_out/transfer_in` 流水，迁入目标基础账户。
- retain：在新订阅创建 `entitlement_amount=0` 的 carryover 批次，保留原消费截止时间。
- 已过期余额统一 forfeit；执行后旧订阅账户必须 `available=0` 且 `frozen=0`。

`QuotaHoldGroup` 是业务冻结事实，`QuotaHold` 是跨批次分配行。冻结按
`spendable_until -> batch_type -> UUID` 最早到期优先。PostgreSQL 延迟 Trigger 校验 Group 汇总和
Transfer 两侧的用户、额度类型及金额一致性。迁入余额不修改目标 `entitlement_amount`，也不伪装为
grant/compensate。

## API

- `POST /api/v1/admin/subscriptions/{id}/change/preview`
- `POST /api/v1/admin/subscriptions/{id}/change`
- `GET /api/v1/admin/subscription-changes`
- `GET /api/v1/admin/subscription-changes/{id}`
- `POST /api/v1/admin/subscription-changes/{id}/cancel`
- `GET /api/v1/subscription/changes`

没有 scheduled 手工执行、任意时间调度、reopen、直接额度迁移或历史订阅修改 API。用户响应不包含
内部批次、账户、Transfer、幂等摘要、审批 payload 或迁移细节。

## 迁移与回滚

迁移顺序为 plans 0008-0011、quotas 0004-0005、admin_rbac 0013-0015。数据迁移使用 historical
models 回填已有订阅 source_type，并将历史单账户 Hold 转为一组一行。Catalog Seed 只前向同步，
反向为 noop，避免删除已被审批和审计引用的证据。

plans/quotas PostgreSQL Trigger 的逆向迁移只移除本任务增加的保护；不会安全地还原已经执行的套餐
变更、额度迁移或来源链。完整回退模型迁移会删除套餐变更、HoldGroup 和 Transfer 证据。生产环境
必须先停止相关写入、审查引用并完成备份，优先使用前向修复或备份恢复。不得在未审查的生产数据上
直接逆向，也不得用本任务连接腾讯云 PostgreSQL/Redis。

## 验收

运行快速门禁：

```powershell
.\scripts\check.ps1 all
```

运行隔离的真实 PostgreSQL/Redis 套件：

```powershell
.\scripts\test-plan-changes.ps1
```

专属套件覆盖并发 exactly-once、幂等、数据库终态/来源保护、HoldGroup 汇总、Transfer 配对、
最早到期优先、Hold/变更竞态、失败注入回滚和统一锁顺序死锁回归。脚本使用独立 Compose project，
结束时删除本项目容器、网络和数据卷。
