# XW-0110 套餐与不可变版本

## 边界

本任务只建立套餐模板、版本权益、展示价格、权限与发布快照。不创建套餐申请、订阅、试用发放、额度账户、订单、支付、退款、发票、合同或财务流水。`display_price` 只是 CNY 展示价格，不是交易价格。

## 模型与状态机

`Plan` 使用 UUID 主键、规范化小写 ASCII `code`、`fixed/contact` 展示模式、`draft/published/offline/archived` 状态、乐观 `version` 和 `current_published_version` 指针。首次发布后 `code` 不可修改，V1 没有物理 DELETE API。

`PlanVersion` 使用单调 `version_no`、`draft/published/retired` 状态、乐观 `version` 和 canonical `effective_config`。每个 Plan 最多一个 draft 和一个 published。发布新草稿会原子退役旧 current；offline 状态发布新版本后仍保持 offline。archived 是终态。

跨表指针一致性由领域服务中的 `transaction.atomic()`、`select_for_update()`、`assert_pointer_consistency()`、系统检查和 PostgreSQL 专属测试共同保证。

## Limit Catalog

`config/plan-limit-keys.json` 是代码所有的兼容目录。保留 `subject_active_limit`、`concurrent_detection_jobs`、`article_credits`、`image_credits`、现有 `*_per_cycle`、`assistant_messages_per_cycle`、保留与到期策略键；只新增 `allow_user_model_selection`。`allowed_model_keys` 已 inactive，模型权限只由 `PlanModelPermission` 表达。

`storage_kind` 防止重复事实：`valid_days` 和 `queue_priority` 位于 PlanVersion；八模型位于 PlanModelPermission；其余键位于 PlanLimit。已被 published 版本使用的 value type、scope、unit 机器含义、quota type 和破坏性 enum 不允许原地漂移。语义变化必须新建稳定 key 并停用旧 key。

`sync_plan_catalog` 默认只检查，`--apply` 幂等同步。它只允许更新中文名称、说明、排序和非破坏性展示元数据；检测到已发布语义 drift 时失败关闭。

## Typed values 与八模型

PlanLimit 快照 key/type，并使用 integer/boolean/text/json 四个互斥列。数据库 CheckConstraint 和服务双重验证恰好一个 typed value。bigint 非负、安全边界，拒绝 float、NaN、Infinity、隐式 bool/int、未知/重复/inactive key；JSON 只接受目录中声明的白名单结构。

固定模型为 deepseek、doubao、qwen、hunyuan、wenxin、kimi、glm、spark。可多选默认模型；排序和 model key 均不可重复。发布至少授权和默认一个模型，默认数不得超过 `max_models_per_detection`。

正式综合分能力同时检查授权模型数、单次模型上限和固定默认组合。无法形成正式综合分时仍可发布，但必须显式提交 `confirm_informal_composite=true`，并通过统一 AuditEvent 留下安全摘要。

## Snapshot 与数据库不可变性

发布事务只生成一次 `snapshot_generated_at`。canonical JSON 固定 schema、排序、UTF-8、分隔符、模型顺序和 generated_at，并以 SHA-256 计算 digest。客户端不能提交 effective_config 或 config_digest。未来订阅只能复制完整发布快照，不能动态读取最新模板。

plans/0003 在 PostgreSQL 创建触发器：

- published/retired PlanVersion 的权益和快照禁止更新或删除；只允许 published 到 retired 的受控状态转换。
- 非 draft 父版本下，PlanLimit 和 PlanModelPermission 禁止 INSERT/UPDATE/DELETE。
- QuerySet.update、bulk_update 和原始 SQL 同样受保护。

## 风险、权限和 API

10 个写动作全部进入 RiskPolicy、静态 Handler 和 AuditEvent；没有旧写路径。默认模式遵循冻结表，其中 publish/online/offline/retire/archive 为 password，其余动作使用 confirm。验证通过后直接执行并写入操作记录。

菜单权限 `menu.admin.plans`，动作权限按 plans、plan_versions、plan_limits 分离；普通角色不会自动获得，superuser 只获得 active catalog 权限。管理员写请求要求完整安全 Session、真实 CSRF、RBAC、expected_version 和风险策略。

公开 `/api/v1/plans` 只返回 on-shelf published Plan 及其 current published 权益摘要，不暴露 digest、原始快照、草稿、retired 版本、RiskPolicy 或 Handler。

## 迁移与回滚

- plans/0001：表、索引、条件唯一约束和 typed value 约束。
- plans/0002：代码目录 Seed，reverse 为 noop。
- plans/0003：PostgreSQL 不可变触发器；逆向迁移只安全移除触发器和函数。
- admin_rbac/0009：权限与 RiskAction/RiskPolicy Seed，reverse 为 noop。

单独回退 Seed 不删除目录、权限、策略或证据，也不恢复已安全收敛的元数据。完整回退 plans/0001 会删除全部套餐模板、版本和快照证据。生产环境优先前向修复或备份恢复；任何逆向迁移前必须审查影响并完成可恢复备份。

本任务未连接、迁移或清理腾讯云 PostgreSQL/Redis。

## 本地验收

```powershell
.\scripts\check.ps1 all
.\scripts\test-plans.ps1
```

Compose 验收会在隔离的本地 PostgreSQL/Redis 中执行迁移和 8 个 plans 专属测试，然后清理容器、网络和数据卷。手工验收应覆盖 fixed/contact、发布、公开展示、新版本、旧 digest 不变、offline 发布、online、archive 审批、并发冲突、触发器拒绝原始 SQL和 AuditEvent。
