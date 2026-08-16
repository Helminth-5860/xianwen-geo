# XW-0304 问题分类后台实现

## 产品边界

XW-0304 只实现问题分类和辅助标签目录。它不创建问题、问题库、问题库版本、生成任务、Provider、Prompt 或额度结算；这些属于 XW-0305 及后续任务。

系统迁移内置十个稳定分类：品牌认知、产品／服务、推荐选择、竞品对比、使用场景、购买决策、地域服务、风险与口碑、价格与成本、售后与保障。需求没有给出内置辅助标签，因此迁移不虚构标签，标签由管理员创建。

## 数据与约束

`QuestionCategory` 与 `QuestionTag` 是全局目录项，包含稳定 `key`、名称、规范化名称、说明、状态、排序、内置标志和乐观并发 `version`；分类另有纯文本 `generation_guidance`。两个显式关联表将目录项映射到 `SubjectType`：没有关联表示适用于全部主体，有关联表示只适用于所列主体类型。

输入名称执行 NFKC、空白折叠、控制字符拒绝和 casefold 唯一匹配；key 执行 NFKC 后必须是小写 snake_case。应用服务使用事务、行锁和 `expected_version`，管理员审计只记录稳定 key、状态、版本和主体类型 ID，不记录说明或生成提示正文。

V1 不提供 DELETE API，前端也没有删除控件。PostgreSQL guard 保护 key、`is_builtin` 和严格 `version + 1` 更新，并禁止直接删除内置目录项。未来问题表引用分类或标签时必须使用保护性外键，不得删除历史引用事实。

## 权限与 API

公共的认证用户端点 `GET /api/v1/question-categories` 只返回启用项，可用 `subject_type_id` 过滤。管理端提供分类和标签的查询、创建、详情、修改、启用与停用端点；写请求需要管理员安全会话、CSRF、对应 capability 和 `expected_version`。目录管理不要求 Subscription，不消耗任何 quota，也不复用 AI/risk feature guard。

后台页面 `/admin/question-categories` 支持分类与标签的创建、编辑、排序值、适用主体和启停。稳定 key 创建后不可修改，空适用主体明确显示为“全部主体”。

## 部署影响

- 环境变量：无新增。
- Django migration：新增 questions 初始表、十个内置分类、PostgreSQL catalog guard，并新增管理员权限目录迁移。
- PostgreSQL：新增分类、标签及两个主体类型关联表与触发器。
- Redis、Celery、队列、Beat、端口：无变化。
- Python、Node 依赖：无新增。
- Docker 运行服务：无变化；仅新增隔离的 `questions-test` Compose profile 用于 CI。

部署时先执行 migration，再滚动重启 API 和前端即可。无需重启 Celery worker，也没有新的周期任务。

## 验证

专用 PostgreSQL 套件通过 `scripts/test-questions.ps1` 或 `scripts/test-questions.sh` 运行：长期 PostgreSQL 依赖先启动，migration 单独执行并检查退出码，最后由真实 question catalog pytest 容器退出码决定结果，cleanup always。
