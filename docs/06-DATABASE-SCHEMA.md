# 06. 数据库模型与数据字典

## 1. 总体原则

- 数据库使用 PostgreSQL 16。
- 主键统一使用 UUID。
- 时间统一保存 UTC，前端按中国标准时间展示。
- 业务表必须包含 `created_at`、`updated_at`；历史快照表通常只追加不更新。
- 用户业务数据按 `user_id` 和 `subject_id` 双重隔离。
- 删除默认使用状态／软删除；审计、额度和历史检测不可物理删除。
- 大文件、图片、PDF、Word 和原始附件放 COS；数据库只保存对象键、哈希、大小和元数据。
- API 密钥正文不得存普通字段；使用密钥管理或应用层加密，仅保存掩码、密文引用和版本信息。
- JSONB 只用于模型供应商差异字段、快照和扩展元数据；核心查询字段必须规范化。

## 2. 命名约定

- 表：复数小写下划线，如 `geo_detection_jobs`
- 外键：`<entity>_id`
- 状态：字符串枚举或数据库受控值，不使用任意文本
- 版本号：整数递增＋稳定版本标识
- 金额：V1 不记录实际交易；套餐展示价格可使用 `numeric(12,2)`，仅展示
- 数量：`bigint`，避免 Token、字节和流水量溢出

## 3. 高层关系

```mermaid
entityRelationshipDiagram
    USERS ||--o{ SUBJECTS : owns
    USERS ||--o{ USER_SUBSCRIPTIONS : has
    USER_SUBSCRIPTIONS ||--o{ QUOTA_ACCOUNTS : grants
    QUOTA_ACCOUNTS ||--o{ QUOTA_LEDGER_ENTRIES : records
    SUBJECTS ||--o{ SUBJECT_VERSIONS : versions
    SUBJECTS ||--o{ KEYWORD_SETS : has
    SUBJECTS ||--o{ QUESTION_BANK_VERSIONS : has
    SUBJECTS ||--o{ GEO_DETECTION_JOBS : detects
    GEO_DETECTION_JOBS ||--|| GEO_DETECTION_SNAPSHOTS : locks
    GEO_DETECTION_JOBS ||--o{ MODEL_CALLS : contains
    MODEL_CALLS ||--|| SCORE_RESULTS : scores
    GEO_DETECTION_JOBS ||--|| GEO_REPORTS : produces
    GEO_REPORTS ||--o{ STRATEGY_REPORTS : advises
    SUBJECTS ||--o{ ARTICLES : creates
    ARTICLES ||--o{ ARTICLE_SOURCE_PACKS : uses
    ARTICLES ||--o{ CHANNEL_ADAPTATIONS : adapts
    SUBJECTS ||--o{ IMAGES : owns
    USERS ||--o{ USER_DOCUMENTS : uploads
```

## 4. 账号与认证

### 4.1 `users`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid PK | 用户 ID |
| phone | varchar unique | 手机号，按规范化值唯一 |
| nickname | varchar | 昵称 |
| password_hash | varchar | 密码哈希 |
| approval_status | varchar | pending/approved/rejected |
| account_status | varchar | active/frozen/cancel_pending/cancelled |
| approval_reason | text nullable | 拒绝原因 |
| approved_at | timestamptz nullable | 审核时间 |
| approved_by_id | uuid nullable | 管理员 |
| cancel_requested_at | timestamptz nullable | 注销申请时间 |
| cancel_effective_at | timestamptz nullable | 注销执行时间 |
| last_login_at | timestamptz nullable | 最近登录 |
| trial_ever_granted | boolean | 是否曾获得试用 |

索引：`phone`、`approval_status`、`account_status`、`created_at`。

### 4.2 `user_sessions`

保存登录会话、设备、IP、过期时间、是否撤销。Cookie 只保存不可预测会话标识。

### 4.3 `login_events`

字段：用户、手机号、方式、成功／失败、IP、User-Agent、设备摘要、失败原因、时间。

### 4.4 `sms_verification_codes`

保存哈希后的验证码、用途、手机号、过期时间、尝试次数、使用时间。不得保存明文验证码。

### 4.5 `user_notification_preferences`

站内消息和允许用户配置的短信通知偏好。

## 5. 管理员、角色与审批

### 5.1 `admin_users`

后台管理员账户，包含状态、2FA 策略、最近登录和超级管理员标志。

### 5.2 `admin_roles`

自定义角色：名称、说明、状态、客户可见范围、是否强制 2FA、IP 白名单模式。

### 5.3 `permissions`

稳定权限键，如：

- `users.review`
- `users.freeze`
- `plans.manage`
- `quotas.adjust`
- `models.manage`
- `api_credentials.manage`
- `reports.view_all`
- `audit.view`

### 5.4 `admin_role_permissions`

角色与权限多对多。

### 5.5 `admin_ip_allowlists`

管理员或角色允许的 IP／CIDR。

### 5.6 `approval_workflows`

操作类型、所需安全级别、是否双人审批、是否启用。

### 5.7 `approval_requests`

发起人、操作类型、目标、变更载荷、状态、审批人、意见、执行结果。

### 5.8 `admin_audit_logs`

不可删除追加表：管理员、动作、对象、前后值摘要、原因、IP、设备、审批请求和结果。

## 6. 套餐与订阅

### 6.1 `plans`

套餐稳定标识、名称、说明、展示价格、是否试用、状态、排序。

### 6.2 `plan_versions`

| 字段 | 说明 |
|---|---|
| id | 版本 ID |
| plan_id | 套餐 |
| version_no | 递增版本号 |
| effective_config | JSONB 完整权益配置快照 |
| valid_days | 有效天数 |
| queue_priority | 队列优先级 |
| published_at/by | 发布记录 |
| status | draft/published/retired |

套餐限制同时应拆到规范表便于查询。

### 6.3 `plan_limits`

`plan_version_id`、`limit_key`、`integer_value`、`boolean_value`、`text_value`、`json_value`。`limit_key` 受控，见配置 JSON。

### 6.4 `plan_model_permissions`

套餐版本可用模型列表及排序、默认选择。

### 6.5 `package_applications`

用户申请套餐：目标套餐、联系人、联系电话、备注、状态、负责人、处理备注。

### 6.6 `user_subscriptions`

| 字段 | 说明 |
|---|---|
| user_id | 用户 |
| plan_version_id | 套餐版本 |
| entitlement_snapshot | 完整权益快照 |
| status | pending/active/expired/terminated/overridden |
| starts_at/ends_at | 生效和到期 |
| cycle_anchor_day | 月度重置锚点 |
| is_trial | 是否试用 |
| opened_by_id | 经办管理员 |
| note | 备注 |

数据库约束：同一用户最多一个 `active` 订阅。

### 6.7 `subscription_changes`

记录覆盖、累加、保留、顺延、升级、降级和续费的前后快照。

## 7. 额度与成本

### 7.1 `quota_accounts`

| 字段 | 说明 |
|---|---|
| user_id | 用户 |
| subject_id | 主体维度额度可为空 |
| subscription_id | 订阅 |
| quota_type | 额度类型 |
| available | 可用 |
| frozen | 冻结 |
| cycle_started_at/ends_at | 周期 |
| expires_at | 额度批次到期 |
| status | active/frozen/expired |

唯一性应包含用户、主体、订阅、额度类型和额度批次。

### 7.2 `quota_holds`

任务冻结记录：任务、额度类型、预计量、已结算量、状态、幂等键。

### 7.3 `quota_ledger_entries`

不可修改追加流水。字段见额度规则文档。`idempotency_key` 唯一。

### 7.4 `quota_cycle_resets`

重置批次、周期、执行状态和流水关联。

### 7.5 `system_test_quota_configs`

全站和每模型测试额度、周期、上限。

### 7.6 `system_test_quota_usage`

测试调用使用记录。

### 7.7 `api_cost_records`

供应商、模型、任务、Token、单位数、估算单价、估算成本、账单成本、币种标识、时间。

V1 只做系统成本，不与用户收费金额关联。

## 8. 客户记录

### 8.1 `customer_profiles`

用户一对一扩展：来源、客户状态、负责人、内部备注。

### 8.2 `customer_statuses`

系统和自定义状态，支持排序和停用。

### 8.3 `customer_tags` 与 `customer_tag_links`

客户标签。

### 8.4 `customer_contact_logs`

联系时间、方式、内容、管理员、下次跟进时间。

### 8.5 `customer_followups`

待办状态、到期时间、负责人、完成／延期／取消。

## 9. 主体类型与动态字段

### 9.1 `subject_types`

类型键、名称、说明、图标、状态、排序、风险类型关联、生成模板配置。

### 9.2 `subject_field_definitions`

| 字段 | 说明 |
|---|---|
| subject_type_id | 主体类型 |
| field_key | 稳定代码键 |
| label | 中文名称 |
| field_type | text/textarea/number/date/single/multi/select/url/image/file |
| required | 是否必填 |
| options | JSONB |
| default_value | JSONB |
| sort_order | 排序 |
| used_for_ai | 是否参与生成 |
| name_role | none/official_name/alias/english_name/product |
| enabled | 启用 |

公共字段也以固定定义存在，后台只能按主体类型调整必填和启用状态，不改变字段键语义。

## 10. 主体与版本

### 10.1 `subjects`

用户、当前主体类型、当前版本、状态、审核状态、风险类型、是否启用／归档／回收站、删除时间。

### 10.2 `subject_versions`

不可变快照：版本号、主体类型、完整字段 JSONB、官方链接、资料完整度、确认状态、创建来源、创建人。

为关键字段建立冗余索引列，避免全部依赖 JSONB。

### 10.3 `subject_names`

按版本保存完整名称、别名、英文名、历史名及是否有效提及匹配。

### 10.4 `subject_products`

产品正式名、简称、型号、是否唯一、是否计入提及、确认状态。

### 10.5 `subject_reviews`

主体人工审核记录。

### 10.6 `risk_types` 与 `risk_rules`

风险类别、规则、功能限制和审核配置。

## 11. 用户资料与文件

### 11.1 `user_documents`

用户、主体、用途（资料库／仅文章）、文件名、COS 对象键、MIME、大小、哈希、状态、回收站和保留时间。

### 11.2 `document_versions`

原始文件版本、对象键、哈希、上传时间。

### 11.3 `document_parse_jobs`

解析任务状态、解析器版本、OCR 使用、错误。

### 11.4 `document_parsed_versions`

解析出的正文、表格 JSON、关键字段、疑似错误、确认状态、用户修订文本、确认时间。

历史文章引用确认后的解析版本。

### 11.5 `web_source_imports`

用户输入网页链接、抓取状态、标题、正文、哈希、访问时间和确认状态。

## 12. 关键词

### 12.1 `keyword_sets`

主体、主体版本、版本号、来源（AI／manual／restore）、状态、生成配置、是否当前版本。

### 12.2 `keywords`

| 字段 | 说明 |
|---|---|
| keyword_set_id | 关键词版本 |
| text | 关键词 |
| structure_type | short/long_tail/general |
| is_regional | 地区关键词 |
| country/province/city/district | 地域 |
| custom_region | 自定义地区 |
| base_keyword_id | 派生基础词 |
| business_category | 业务分类 |
| search_intent | 搜索意图 |
| relevance_score | 相关度 |
| priority | 高中低或分值 |
| ai_reason | 生成理由 |
| enabled | 当前版本是否启用 |

允许 `structure_type=general` 表示用户未选择短／长尾分类或 AI 自动通用词。

### 12.3 `keyword_generation_jobs`

保存不可变业务绑定与可推进执行状态：

- user、subject、冻结的 current SubjectVersion、创建时 KeywordSet expected_version。
- subscription、free_initial/regeneration 计费模式，以及 regeneration 对应的 QuotaHoldGroup。
- 目标数量、类型／地域配置、已确认历史排除词和冻结主体输入快照。
- provider/model/adapter/prompt 版本、输入摘要、请求摘要和 HMAC 幂等摘要。
- queued/running/retry_wait/succeeded/failed/conflict/superseded、lease generation、尝试次数、下次尝试时间和安全错误码。

PostgreSQL 条件唯一约束保证每个主体至多一个 active job。触发器限制合法状态迁移、冻结事实不可变、主体／版本／额度绑定一致，并要求终态与 exactly-once 额度结算相符。

### 12.4 `keyword_generation_results`

每个成功任务至多一条不可变结果，保存经过结构校验和规范化后的输出快照、输出摘要、条目数、实际写入的草稿版本和白名单 provider metrics。不得保存 provider raw response。

### 12.5 `keyword_generation_events`

追加式安全事件，仅记录 started/retry_scheduled/succeeded/failed/conflict/superseded、稳定错误码、request/correlation id 与无敏感正文的 safe_summary。禁止更新或删除。

正式 KeywordSetVersion 与 Keyword 均保持不可变；正式 base_keyword 必须指向同一版本内其他关键词且不得形成环。AI 成功只替换 KeywordDraftItem 草稿，不创建正式版本。

`keyword_regenerations` 使用带 subject_id 的订阅周期 QuotaAccount。账户绑定不可变；跨周期晚到结算仍操作原 hold 绑定账户。

## 13. 关键词蒸馏

### 13.1 `distillation_jobs`

异步任务保存不可变 user/subject/SubjectVersion/KeywordSetVersion/subscription 绑定、冻结的主体与关键词输入快照、provider/model/adapter/prompt provenance、input/request/HMAC digest，以及可推进的 status/generation/attempt/retry/lease 字段。每主体至多一个 queued/running/retry_wait 任务。

第一次成功应用 workspace 草稿为 `free_initial`；后续成功历史要求显式 regeneration，并绑定 `distillation_regenerations` 的 `QuotaHoldGroup`。PostgreSQL guard 要求终态和原 hold 的 exactly-once consume/release 一致。

### 13.2 `distillation_results` 与 `distillation_events`

每个成功任务至多一个不可变 Result，只保存通过完整覆盖、动作、canonical、merge group 和地域约束校验的结构化输出、output digest、条目数、应用的 workspace version 及白名单 metrics。Event 仅追加安全状态摘要。两者均不得保存 prompt、API key、主体正文或 provider raw response。

### 13.3 `distillation_workspaces` 与 `distillation_draft_items`

每主体一个可变调整 workspace，绑定当前草稿所用的不可变 KeywordSetVersion 和原始 DistillationResult，并用 version 做乐观并发。DraftItem 为每个输入 Keyword 保存最终 action/canonical/merge group、不可变 AI action/reason 副本和独立 user_reason/user_overridden。重新蒸馏成功时原子替换完整草稿；普通人工保存不改机器 Result。

### 13.4 `distillation_sets` 与 `distillation_items`

用户明确确认后创建连续、不可变 DistillationSet。每个 Set 严格绑定一个 SubjectVersion、一个 KeywordSetVersion 和一个原始 Result，并保存 content digest、item_count、confirmed_by/at。Item 完整保存机器建议和人工调整事实。

`keep/merge/delete/low_value` 互斥。delete 仅是排除建议，不删除 Keyword；low_value 是单独的低价值分类；merge 只建立 UUID 分组并选择同组输入 Keyword 为 canonical，不创建新关键词。每组至少两个成员、canonical 必须为组内成员，且地域签名一致。任何蒸馏流程都不得更新历史 KeywordSetVersion 或 Keyword。

## 14. 问题库

### 14.1 `question_categories`

名称、说明、适用主体类型、排序、状态、是否系统内置。

### 14.2 `question_bank_versions`

主体、主体版本、蒸馏版本、版本号、状态、是否当前、确认时间。

### 14.3 `questions`

| 字段 | 说明 |
|---|---|
| question_bank_version_id | 问题库版本 |
| text | 问题 |
| primary_category_id | 主分类 |
| priority | high/medium/low |
| question_type | natural/brand_directed |
| participates_in_scoring | 是否评分 |
| ai_reason | AI 理由 |
| enabled | 当前版本启用 |

### 14.4 `question_tags` 与 `question_tag_links`

辅助标签。

### 14.5 `question_keyword_links`

问题与关键词多对多。

### 14.6 `question_generation_jobs`

生成任务和次数结算。

## 15. GEO 模型配置

### 15.1 `ai_providers`

供应商标识、名称、状态。

### 15.2 `ai_models`

稳定模型键、供应商、显示名、用途（detection/text/image/scoring）、启用、排序。

### 15.3 `ai_model_versions`

模型 ID、API 版本、能力、Token 限制、联网能力、参数配置、发布时间和状态。

### 15.4 `ai_model_runtime_configs`

超时、重试、重试间隔、并发、联网失败策略、成本阈值、暂停／恢复策略。

### 15.5 `api_credentials`

只保存供应商、环境、掩码、密文引用、版本、状态、创建和替换记录。严禁普通查询返回密文。

### 15.6 `api_credential_audit`

密钥新增、替换、验证、停用记录。

## 16. 提示词与评分规则

### 16.1 `prompt_templates`

稳定模板键、用途和说明。

### 16.2 `prompt_template_versions`

版本号、内容、参数模式、状态（draft/testing/published/retired）、测试记录、发布人。

### 16.3 `prompt_test_cases`

固定案例或历史脱敏案例引用。

### 16.4 `prompt_test_runs`

新旧版本输出、Token、耗时、评价和测试额度使用。

### 16.5 `scoring_rule_versions`

GEO 权重、等级、口碑权重、曝光公式、评分模型版本和状态。V1 只读固定配置，但仍保存版本。

### 16.6 `article_quality_rule_versions`

文章质量权重和等级。

## 17. GEO 检测

### 17.1 `geo_detection_jobs`

| 字段 | 说明 |
|---|---|
| user_id/subject_id | 所属 |
| status | queued/running/partial/succeeded/failed/cancelled |
| planned_question_count | 计划问题数 |
| planned_model_count | 计划模型数 |
| planned_detection_points | 预计点数 |
| completed_calls | 已完成 |
| successful_calls/failed_calls | 成功失败 |
| queue_priority | 固化优先级 |
| queued_at/started_at/finished_at | 时间 |
| cancelled_at | 取消时间 |
| quota_hold_id | 冻结记录 |
| idempotency_key | 唯一 |

### 17.2 `geo_detection_snapshots`

不可变快照：主体版本、关键词版本、蒸馏版本、问题库版本、实际问题 ID 和文本、模型版本、提示词版本、评分规则版本、创建时间。

### 17.3 `geo_detection_model_runs`

每模型汇总状态、计划问题数、成功率、正式／临时、模型分、联网和降级摘要。

### 17.4 `model_calls`

每个问题 × 模型调用：

- 检测任务
- 问题快照
- 模型版本
- 请求状态
- 是否请求／实际联网
- 是否降级
- 尝试次数
- 开始／结束／耗时
- 供应商请求 ID
- 错误类别和安全摘要
- 额度结算状态
- 成本记录

唯一约束：检测任务＋问题快照键＋模型版本。

### 17.5 `model_call_attempts`

每次重试请求：错误码、耗时、Token 和响应摘要。不得记录密钥。

### 17.6 `model_responses`

完整原始文本、结构化原始 JSON（脱敏）、回答哈希、关键片段。

### 17.7 `response_citations`

来源名称、URL、域名、来源类型、访问状态、相关性、访问时间。

### 17.8 `score_results`

单题单模型六维得分、总分、问题类型、证据、评分模型、提示词和规则版本。

### 17.9 `model_scores`

模型 GEO 正式／临时分、口碑正式／临时分、成功率和问题统计。

### 17.10 `geo_reports`

综合 GEO 分、口碑分、曝光指数、等级、正式／临时状态、成功模型数、摘要、生成时间。

### 17.11 `competitor_entities` 与 `competitor_mentions`

竞品标准实体、别名、出现问题、模型、排名和推荐状态。用户可标记非竞品。

## 18. 改善策略

### 18.1 `strategy_reports`

报告、周期、AI 原文、提示词版本、生成状态、是否首次免费、创建时间。

### 18.2 `strategy_notes`

用户个人备注，可修改和删除；与 AI 原文分离。

## 19. 报告导出与分享

### 19.1 `report_exports`

报告、格式、品牌配置快照、COS 对象键、状态、生成时间、过期时间。

### 19.2 `subject_white_label_configs`

主体默认白标：Logo、封面、品牌色、页眉页脚、联系方式和声明。

### 19.3 `report_shares`

分享令牌哈希、报告快照、品牌快照、密码哈希、有效期、关闭时间、访问次数、最近访问。

### 19.4 `report_share_access_logs`

访问时间、IP 摘要、User-Agent、结果。不要保存不必要的个人信息。

## 20. 文章类型和模板

### 20.1 `article_types`

名称、说明、适用主体类型、状态、排序。

### 20.2 `article_template_versions`

提示词版本、结构、联网策略、引用要求、允许资料范围和推荐渠道。

### 20.3 `article_source_packs`

文章专用资料包状态、生成时间、冲突状态、冻结快照。

### 20.4 `article_source_items`

来源类型、文档／网页引用、标题、URL、发布时间、可信度、核验状态、摘录、用户确认。

### 20.5 `article_outlines`

当前草稿的大纲文本、是否首次免费、任务状态。无需复杂历史版本；重新生成后替换当前未确认大纲，但保留最小审计记录。

### 20.6 `articles`

| 字段 | 说明 |
|---|---|
| user_id/subject_id | 所属 |
| subject_version_id | 绑定资料版本 |
| article_type_id | 类型 |
| custom_type | 自定义类型 |
| title/content | 当前唯一稿 |
| status | draft/generating/reviewing/ready/rejected |
| content_depth | concise/standard/deep |
| source_pack_id | 资料包 |
| current_quality_score | 当前质量分 |
| moderation_status | 审核状态 |
| autosaved_at | 自动保存时间 |

不建立用户可见文章版本历史。优化前后的临时对比稿应放临时表或缓存，确认后只写选中稿。

### 20.7 `article_generation_jobs`

生成、整篇优化、局部修改等任务，记录额度结算。

### 20.8 `article_comparison_candidates`
## XW-0113 implemented quota schema override

The earlier section 7 was a preliminary design. The implemented XW-0113 schema
is authoritative for this task: `QuotaAccount` has no `subject_id`, status,
or independent expiry; it binds an immutable Subscription and optional account
cycle. `QuotaHold` uniquely binds an account/business target, and
`QuotaLedgerEntry` is append-only with a strict per-account sequence.
PostgreSQL triggers protect balances, bindings, evidence, and terminal hold
state. There is no public reset API. See `25-QUOTA-LEDGER.md`.

短期临时表：原稿快照、优化稿、过期时间、选择结果。用户选择后删除或按短期审计策略清理，不作为文章版本。

### 20.9 `article_quality_checks`

总分、六项分数、建议、规则版本、是否首次免费。

### 20.10 `article_moderation_reviews`

自动和人工审核记录、责任归因、复核次数。

## 21. 渠道适配与发布

### 21.1 `publishing_channels`

渠道名称、Logo、官网、类型、说明、规则、状态和排序。

### 21.2 `channel_template_versions`

标题、结构、语气、标签、图片、外链和提示词版本。

### 21.3 `channel_adaptations`

原文章、渠道、当前适配稿标题和正文、模板版本、质量分、状态。它是关联发布稿，不是原文章版本。

### 21.4 `publication_link_checks`

主体、文章或适配稿、渠道、URL、结果（success/failed/unknown）、识别标题、失败原因、检测时间。

只保存即时检测，不创建周期监控。

## 22. 图片

### 22.1 `image_size_presets`

名称、比例、像素、豆包参数、适用渠道／用途、状态。

### 22.2 `image_style_presets`

名称、说明、提示词模板、适用范围、示例图、状态。

### 22.3 `images`

用户、主体、文章、用途、COS 对象键、尺寸、格式、来源图、是否主体图片库、审核状态、回收站和删除时间。

### 22.4 `image_generation_jobs`

类型（generate/outpaint/recompose）、提示词、风格、尺寸、参考图快照、额度、状态和供应商请求 ID。

### 22.5 `image_reference_links`

任务和参考图片多对多，记录用途。

### 22.6 `image_moderation_reviews`

自动和人工审核、责任归因、返还结果。

### 22.7 `image_derivatives`

压缩、裁剪、格式转换和 AI 适配版本。标记是否调用 AI 和是否扣额度。

## 23. 通知、公告和反馈

### 23.1 `notifications`

用户站内消息：类型、标题、正文、已读状态、关联对象。

### 23.2 `notification_templates`

站内／短信模板和版本。

### 23.3 `announcements`

标题、正文、时间、置顶、状态。

### 23.4 `announcement_targets`

全体／套餐／用户目标。

### 23.5 `user_feedback`

用户、主体、模块、描述、状态、管理员回复、时间。

### 23.6 `feedback_attachments`

COS 对象键、MIME、大小和审核状态。

## 24. 用户视角协助

### 24.1 `support_view_requests`

管理员、用户、原因、是否强制、状态、用户授权、有效会话、开始／结束、撤销。

### 24.2 `support_view_audit_logs`

只读访问页面摘要，禁止记录用户敏感正文副本。

## 25. 系统配置、任务和告警

### 25.1 `system_settings`

受控键值、版本、修改人。敏感值不得放普通表。

### 25.2 `async_tasks`

可选统一任务索引：Celery task ID、业务任务类型、业务 ID、队列、状态、重试和时间。

### 25.3 `system_alerts`

告警类型、等级、来源、状态、首次／最后发生、通知结果、处理人。

### 25.4 `backup_records`

备份类型、范围、位置引用、加密、状态、校验、恢复测试。

### 25.5 `retention_jobs` 与 `deletion_jobs`

数据过期、回收站清理、账号注销清理的任务和结果。

## 26. 建议索引

关键索引：

- 所有业务表：`user_id, created_at`
- 主体级表：`subject_id, created_at`
- 任务：`status, queue_priority, created_at`
- 模型调用：`geo_detection_job_id, ai_model_version_id, status`
- 流水：`user_id, quota_type, created_at`
- 通知：`user_id, read_at, created_at`
- 文章／图片：`subject_id, status, created_at`
- JSONB 快照仅对明确查询路径建立 GIN 或表达式索引。

## 27. 分区建议

初期可不分区，但设计时预留。数据量增长后优先按月分区：

- `model_calls`
- `model_call_attempts`
- `api_cost_records`
- `quota_ledger_entries`
- `login_events`
- `admin_audit_logs`
- `report_share_access_logs`

## 28. 数据保留

- 额度流水、套餐变更、管理员审计和安全日志：长期保留或匿名化保留。
- 业务记录：按套餐期限。
- 用户注销：业务数据删除；必要日志去标识化。
- 临时优化对比稿、临时导出文件和抓取缓存：短期自动清理。

## 29. 数据库约束重点

- 同一用户仅一个 active 订阅。
- 同一主体仅一个 current 主体版本、关键词版本、蒸馏版本和问题库版本。
- 同一额度结算幂等键唯一。
- 同一检测任务的“问题 × 模型”调用唯一。
- 分享令牌只存哈希。
- 文章优化候选过期后自动删除。
- 管理员不能更新或删除审计流水。

## 30. 迁移顺序

1. 用户、管理员、权限
2. 套餐、订阅、额度
3. 主体类型、主体、资料
4. 关键词、蒸馏、问题库
5. 模型、提示词、检测、评分
6. 报告、策略、导出分享
7. 文章、资料包、质量审核
8. 图片、渠道和发布检测
9. 通知、反馈、CRM、审计和运维

