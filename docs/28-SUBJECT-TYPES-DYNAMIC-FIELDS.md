# XW-0201 主体类型与动态字段目录

## 范围

`apps.subjects` 只负责主体类型目录和可配置表单 Schema。本任务不创建 Subject、
SubjectVersion、主体额度、文件上传、COS 预签名、AI 补充、关键词或任何 XW-0202
业务写入路径。PostgreSQL 是目录、字段绑定、选项和并发版本的事实源；Redis 不参与
Schema 保存或锁。

## 数据模型与不可变语义

- `SubjectType` 保存稳定 `key`、用户可见 metadata、`status`、独立
  `schema_version` 和对象 `version`。
- `SubjectFieldDefinition` 保存稳定 `field_key`、`field_type`、`scope`、
  `owner_subject_type` 和 `is_builtin`。机器语义创建后不可修改。
- `SubjectTypeFieldConfig` 是管理 API 的编辑资源，保存 label、description、required、
  default、排序、启停、`used_for_ai`、`name_role` 和对象 `version`。
- `SubjectFieldOption` 保存稳定 `option_key`，label、启停和排序可修改。未来主体数据只应
  引用 `option_key`，不得引用可变 label。

四类行均禁止物理删除。PostgreSQL 函数 `subjects_reject_delete` 及
`subjects_*_no_delete` Trigger 拒绝原始 SQL DELETE；`subjects_guard_type`、
`subjects_guard_definition`、`subjects_guard_config`、`subjects_guard_option` 拒绝机器语义
或绑定关系修改。字段类型创建错误时，管理员必须停用旧 Config，并使用新 key 创建新字段。

`subjects_assert_schema` 由三个延迟约束 Trigger 调用，提交时验证：

- 同一 form-schema 的 `field_key` 大小写不敏感唯一，custom/common 不可冲突；
- custom Definition 只能绑定自己的 SubjectType；
- active 类型恰有一个 enabled、required、official_name 字段；
- active Schema 中每个非 none `name_role` 唯一；
- 只有 single/multi/select 可以拥有 Option，启用的选择字段至少有一个启用 Option；
- Option key 在 Config 内大小写不敏感唯一；
- default 严格匹配字段类型，number 拒绝 bool，image/file 只能为 null。

## 静态目录与同步

Seed 仅包含十类：enterprise、brand、product、person、organization、store、service、
project、place、professional_institution。公共字段仅包含 name、summary、
core_products_services、target_audience、service_regions、official_url，不 Seed 未冻结的
类型专属字段。name 默认 enabled、required 且 `name_role=official_name`。

创建 SubjectType 时，在同一事务为全部公共 Definition 创建安全默认 Config，不允许先创建
空 active Schema。`sync_subject_catalog --apply` 只创建缺失内置目录并验证不可变机器语义；
检测 drift 时非零失败，不覆盖管理员修改过的 label、description、required、default、启停、
排序、AI 用途或 name role。

范围重申：XW-0201 不创建 Subject、SubjectVersion，也不实现任何 XW-0202 写入逻辑。

## 并发版本与事务

所有改变 form-schema 的写操作都锁定 SubjectType，校验 `expected_schema_version`，并使
`schema_version` 单调递增。修改 Type、Config 或 Option 时还校验对应 `expected_version`；
任一过期版本返回稳定 409。完整字段排序必须提交当前类型全部 Config ID 和各对象版本，
重复、遗漏或跨类型 ID 均失败且整笔回滚。

管理写操作使用 `transaction.atomic`，Schema 事实、版本递增和 `AuditEvent` 同事务提交。
XW-0201 不增加 RiskAction；全局目录不应用 CustomerAssignment own/role/all 数据范围。

## API 与权限

用户只读接口：

- `GET /api/v1/subject-types`
- `GET /api/v1/subject-types/{id}/form-schema`

认证且账号可用的 pending、rejected、approved 用户均可读取；inactive 类型返回 404。GET
不写数据库、不隐式同步目录。公共响应不返回 Config/Option version 或内置标记。

管理接口以 SubjectType 和 FieldConfig 为资源，使用 Session、真实 CSRF 和 RBAC：

- `/api/v1/admin/subject-types` 及类型详情、enable、disable；
- `/api/v1/admin/subject-types/{id}/fields` 原子创建 custom Definition + Config；
- `/api/v1/admin/subject-type-fields/{config_id}` 修改展示和业务配置；
- Config 下创建 Option、按 Option ID 修改 label/启停/排序；
- `/api/v1/admin/subject-types/{id}/field-order` 替换完整排列。

不提供 Definition、Config、Option DELETE，不提供字段类型切换、上传、预签名或调试 API。
管理员输入按纯文本和长度上限验证，前端不使用 `dangerouslySetInnerHTML`。image/file 仅作为
Schema 声明并明确显示“上传能力尚未启用”。

## 迁移与回滚

- `subjects.0001_initial` 创建四个目录表、约束和索引。
- `subjects.0002_seed_builtin_subject_catalog` 使用 historical models 幂等 Seed；reverse 为
  noop，避免静默删除已经被管理员配置或未来业务引用的目录证据。
- `subjects.0003_postgresql_schema_guards` 安装大小写不敏感索引、不可变/不可删除 Trigger 和
  延迟 Schema 约束；反向只移除数据库保护，不删除目录数据。
- `admin_rbac.0016_seed_subject_catalog_permissions` Seed 菜单和动作权限；reverse 为 noop。

生产逆向迁移前必须停止目录写入、审查引用并备份。优先使用前向修复或备份恢复；完整回退
0001 会删除主体目录表及配置证据。本任务验收不连接腾讯云 PostgreSQL/Redis。

## XW-0202 冻结边界

XW-0202 创建 Subject/SubjectVersion 时，必须保存提交时的 `schema_version`、canonical
schema snapshot 和 digest。历史主体语义不能仅通过未来“当前 Schema”回查，也不能在
XW-0201 提前创建 Subject 或 Schema 历史业务表。

## 验收

快速检查运行 `./scripts/check.sh all` 或 `.\scripts\check.ps1 all`。真实 PostgreSQL/Redis
约束套件运行 `./scripts/test-subject-schema.sh` 或 `.\scripts\test-subject-schema.ps1`；
专属 Compose project 在退出时清理容器、网络和数据卷。远程 `Docker Compose` Job 必须
真实执行同一脚本，失败会阻断合并。
