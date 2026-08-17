# 07. REST API 规格说明

## 1. 总体约定

- 前缀：`/api/v1`
- 内容类型：`application/json; charset=utf-8`
- 认证：HttpOnly Cookie 会话；修改请求要求 CSRF Token
- 文件上传：预签名 COS 上传或受控 multipart 初始化接口
- 时间：ISO 8601 UTC
- ID：UUID 字符串
- 请求标识：可通过 `X-Request-ID` 传入规范 UUID；响应头与 JSON `request_id` 完全一致
- 分页：游标或页码制统一一种；V1 建议页码制 `page/page_size`
- 异步任务：提交后返回业务任务 ID 和状态查询地址
- 幂等：所有扣额度或创建任务的 POST 要求 `Idempotency-Key`
- 错误不得包含 API 密钥、供应商完整请求、数据库堆栈或内部提示词

## 2. 响应格式

### 2.1 成功

```json
{
  "success": true,
  "data": {},
  "request_id": "uuid"
}
```

### 2.2 分页

```json
{
  "success": true,
  "data": {
    "items": [],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 0,
      "total_pages": 0
    }
  },
  "request_id": "uuid"
}
```

### 2.3 错误

```json
{
  "success": false,
  "error": {
    "code": "QUOTA_INSUFFICIENT",
    "message": "检测点不足",
    "details": {
      "required": 120,
      "available": 80
    }
  },
  "request_id": "uuid"
}
```

## 3. 通用错误码

| 错误码 | HTTP | 说明 |
|---|---:|---|
| AUTH_REQUIRED | 401 | 未登录 |
| CSRF_FAILED | 403 | CSRF 失败 |
| PERMISSION_DENIED | 403 | 权限不足 |
| RESOURCE_NOT_FOUND | 404 | 资源不存在或不可访问 |
| METHOD_NOT_ALLOWED | 405 | 请求方法不允许 |
| INVALID_JSON | 400 | JSON 请求体无法解析 |
| ACCOUNT_PENDING_REVIEW | 403 | 账号待审核 |
| ACCOUNT_FROZEN | 403 | 账号冻结 |
| PLAN_REQUIRED | 403 | 未开套餐 |
| PLAN_EXPIRED | 403 | 套餐到期 |
| SUBJECT_LIMIT_REACHED | 409 | 主体数量超限 |
| SUBJECT_NOT_READY | 409 | 主体资料未完成或待审核 |
| QUOTA_INSUFFICIENT | 409 | 额度不足 |
| CONCURRENCY_LIMIT_REACHED | 409 | 用户并发达到上限 |
| IDEMPOTENCY_CONFLICT | 409 | 幂等键对应不同请求 |
| TASK_NOT_CANCELLABLE | 409 | 任务不可取消 |
| RESOURCE_VERSION_CONFLICT | 409 | 编辑版本冲突 |
| VALIDATION_ERROR | 422 | 参数错误 |
| EXTERNAL_API_ERROR | 502 | 外部模型调用错误 |
| INTERNAL_ERROR | 500 | 服务器内部错误 |
| SERVICE_TEMPORARILY_UNAVAILABLE | 503 | 服务临时不可用 |
| RATE_LIMITED | 429 | 频率限制 |

## 4. 身份认证 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/sms/send` | 发送注册／登录／重置／换手机号验证码 |
| POST | `/auth/register` | 手机号、昵称、验证码、密码注册 |
| POST | `/auth/login/password` | 密码登录 |
| POST | `/auth/login/sms` | 短信登录 |
| POST | `/auth/logout` | 当前会话退出 |
| POST | `/auth/logout-all` | 退出其他设备 |
| POST | `/auth/password/reset` | 验证码重置密码 |
| GET | `/auth/sessions` | 登录设备列表 |
| DELETE | `/auth/sessions/{id}` | 撤销指定设备 |

### 4.1 注册请求

```json
{
  "phone": "规范化手机号",
  "nickname": "用户昵称",
  "sms_code": "验证码",
  "password": "密码"
}
```

返回用户状态 `pending`，同时建立登录会话。

### 4.2 XW-0103 认证行为

- 注册：验证码消费后创建 pending/active 用户并自动建立 Session；重复手机号此时才返回
  `409 ACCOUNT_ALREADY_EXISTS`。
- 短信登录：无效验证码和不存在账号统一 `401 AUTH_CREDENTIALS_INVALID`；冻结或注销账号
  返回 `403 ACCOUNT_UNAVAILABLE`。
- 密码重置：不存在或已注销账号在验证码有效时返回通用成功；不自动登录，旧 Session 因
  Django session auth hash 变化失效。
- login/password_reset 短信发送对不存在或已注销账号执行内部抑制，但公开响应与真实发送一致。
- 三个匿名 POST 均要求真实 CSRF，Redis 不可用时失败关闭。
## 5. 当前用户与设置

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/me` | 当前用户、审核和套餐摘要 |
| PATCH | `/me/profile` | 修改昵称 |
| POST | `/me/phone/change` | 验证旧／新手机号并更换 |
| PATCH | `/me/notification-preferences` | 通知偏好 |
| GET | `/me/usage-summary` | 额度和使用摘要 |
| POST | `/me/data-export` | 异步生成个人业务数据导出 |
| POST | `/me/cancellation` | 申请注销 |
| DELETE | `/me/cancellation` | 冷静期撤销注销 |

## 6. 套餐与申请

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/plans` | 可展示套餐列表 |
| GET | `/plans/{id}` | 套餐详情 |
| POST | `/package-applications` | 申请开通 |
| GET | `/package-applications` | 用户自己的申请记录 |
| GET | `/subscription` | 当前套餐和权益快照 |
| GET | `/quotas` | 各额度余额、冻结、周期和重置时间 |
| GET | `/quota-ledger` | 用户额度流水 |

## 7. 主体类型与字段

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/subject-types` | 可用主体类型 |
| GET | `/subject-types/{id}/form-schema` | 动态表单定义 |

## 8. 主体 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/subjects` | 主体列表 |
| POST | `/subjects` | 创建主体草稿 |
| GET | `/subjects/{id}` | 当前主体详情 |
| PATCH | `/subjects/{id}/draft` | 自动保存草稿 |
| POST | `/subjects/{id}/commit` | 校验并创建新资料版本 |
| POST | `/subjects/{id}/ai-enrichment` | AI 辅助补充任务 |
| GET | `/subjects/{id}/enrichment/{job_id}` | 补充进度和结果 |
| POST | `/subjects/{id}/enrichment/confirm` | 确认字段 |
| GET | `/subjects/{id}/versions` | 资料版本列表 |
| GET | `/subjects/{id}/versions/{version_id}` | 版本详情 |
| POST | `/subjects/{id}/archive` | 主动归档 |
| POST | `/subjects/{id}/activate` | 启用归档主体 |
| DELETE | `/subjects/{id}` | 进入回收站 |
| POST | `/subjects/{id}/restore` | 回收站恢复 |

### 8.1 创建主体

后端必须校验：

- 待审核用户允许创建草稿，但不能提交 AI 任务。
- 无套餐用户最多一个草稿。
- 有套餐用户总启用主体不超过上限。

## 9. 文件与资料库 API

### 9.1 上传

推荐三步：

1. `POST /files/upload-intents`
2. 前端上传 COS 私有桶
3. `POST /files/upload-intents/{id}/complete`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/files/upload-intents` | 校验存储额度并生成预签名参数 |
| POST | `/files/upload-intents/{id}/complete` | 完成上传登记 |
| GET | `/subjects/{id}/documents` | 主体资料库 |
| POST | `/documents/{id}/parse` | 异步解析 |
| GET | `/documents/{id}/parse-result` | 解析结果 |
| POST | `/documents/{id}/confirm` | 确认／修订解析文本 |
| PATCH | `/documents/{id}` | 修改用途或名称 |
| DELETE | `/documents/{id}` | 进入回收站 |
| POST | `/documents/{id}/restore` | 恢复 |
| POST | `/web-sources/import` | 导入公开网页 |

解析未确认的资料不得进入文章资料包。

## 10. 关键词 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/subjects/{id}/keywords/draft` | 草稿、绑定主体版本和写权限 |
| PATCH | `/subjects/{id}/keywords/draft` | expected_version 原子保存完整有序草稿 |
| GET | `/subjects/{id}/keywords/current` | 当前正式版本 |
| POST | `/subjects/{id}/keywords/commit` | 显式提交不可变正式版本 |
| GET | `/subjects/{id}/keywords/versions` | 正式版本列表 |
| GET | `/subjects/{id}/keywords/versions/{version_id}` | 正式版本详情 |
| POST | `/subjects/{id}/keywords/generate` | 创建或幂等返回 AI 生成任务 |
| GET | `/keyword-jobs/{job_id}` | 所有者范围内轮询安全任务投影 |

### 10.1 生成请求

必须同时携带 `Idempotency-Key` 和 CSRF header：

```json
{
  "expected_subject_version_id": "uuid",
  "expected_keyword_set_version": 3,
  "target_count": 80,
  "include_short": true,
  "include_long_tail": true,
  "include_regional": false,
  "regions": [],
  "regenerate": false
}
```

所有类型可为 false；此时生成通用关键词。选择地区词时必须提供规范化后唯一的地区列表。请求为 strict schema，未知字段返回 422。

`regenerate` 只是用户确认意图；服务端根据该主体是否已有成功写入草稿的生成任务决定 free_initial 或 regeneration。需要消费但未确认时返回 `409 KEYWORD_REGENERATION_CONFIRMATION_REQUIRED`。

### 10.2 任务响应与并发

创建接口返回 202；相同幂等键和相同 canonical 请求返回同一任务且不重复冻结。任务投影包含 status/version、计费摘要、生成配置、provider/model/adapter/prompt provenance、尝试次数和成功结果摘要，不返回主体输入快照、正文、prompt、摘要、幂等摘要或 provider raw response。

状态：`queued/running/retry_wait/succeeded/failed/conflict/superseded`。一个主体只允许一个 active job。主体正式版本或关键词草稿 expected_version 变化时以 conflict 结束并释放冻结，不覆盖现有草稿。

成功只原子替换完整关键词草稿并推进草稿 version；用户仍需调用 commit 创建正式版本。所有响应使用 `Cache-Control: no-store`。

## 11. 蒸馏 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/subjects/{id}/distillations` | 以当前不可变 KeywordSetVersion 发起任务 |
| GET | `/distillation-jobs/{job_id}` | owner-scoped 安全任务投影 |
| GET | `/subjects/{id}/distillations/draft` | 当前关键词输入与调整草稿 |
| PATCH | `/subjects/{id}/distillations/draft` | expected_version 全量保存用户调整 |
| GET | `/subjects/{id}/distillations/current` | 当前不可变确认版本 |
| POST | `/subjects/{id}/distillations/confirm` | 明确确认并创建连续正式版本 |

创建请求必须提供 `Idempotency-Key`、`keyword_set_version_id`、`expected_workspace_version` 和布尔 `regenerate`。只有主体当前 SubjectVersion 与关键词当前 KeywordSetVersion 均与输入绑定一致时才接受。相同幂等键与 canonical 请求重放原任务；一个主体至多一个 active job。

任务状态为 `queued/running/retry_wait/succeeded/failed/conflict/superseded`。第一次成功应用草稿免费；服务端检测到历史成功后，未显式确认返回 `409 DISTILLATION_REGENERATION_CONFIRMATION_REQUIRED`，确认后冻结既有 `distillation_regenerations`。只在结构化结果原子应用 workspace 后扣除；失败、冲突和过期结果释放。

PATCH 只接受 source_keyword_id、互斥 action、可选 canonical_keyword_id/merge_group_key 和 user_reason，不允许客户端覆盖 ai_reason/provenance。merge group 至少两个成员、canonical 在组内且地域签名一致。confirm 不修改 KeywordSetVersion/Keyword，只创建不可变 DistillationSet。所有响应为 `Cache-Control: no-store`，任务响应不暴露输入快照、prompt、digest、密钥或 provider raw response。

## 12. 问题库 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/question-categories` | 启用的分类和标签，可按 subject_type_id 过滤 |
| GET/POST | `/admin/question-categories` | 管理员查询／创建分类 |
| GET/PATCH | `/admin/question-categories/{id}` | 分类详情／expected_version 修改 |
| POST | `/admin/question-categories/{id}/enable`、`disable` | 分类启停 |
| GET/POST | `/admin/question-tags` | 管理员查询／创建辅助标签 |
| GET/PATCH | `/admin/question-tags/{id}` | 标签详情／expected_version 修改 |
| POST | `/admin/question-tags/{id}/enable`、`disable` | 标签启停 |
| POST | /subjects/{id}/question-banks/generate | Create a durable generation job; Idempotency-Key required |
| GET | /question-bank-jobs/{job_id} | Owner-scoped job state, billing and safe provenance |
| GET | /subjects/{id}/question-banks/current | Current immutable confirmed version |
| GET/PATCH | /subjects/{id}/question-banks/draft | Read/replace mutable draft with expected_version |
| POST | /subjects/{id}/question-banks/confirm | Confirm a new immutable version |
| GET | /subjects/{id}/question-banks/versions | Immutable version summaries |
| GET | /subjects/{id}/question-banks/versions/{version_id} | Immutable version detail |

XW-0305 is implemented. Generation requires the current confirmed DistillationSet, uses question_bank_limit, and only consumes question_bank_regenerations after a validated result atomically replaces the draft. Manual edit and confirmation are free.

## 13. 模型列表与检测配置

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/geo/models` | 当前套餐可用且系统启用的模型 |
| GET | `/subjects/{id}/geo/detection-options` | 问题上限、模型、额度和并发 |
| POST | `/subjects/{id}/geo/estimate` | 仅估算检测点，不创建任务 |

估算响应：问题数、模型数、预计点、可用点、是否可提交。

## 14. GEO 检测任务 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/subjects/{id}/geo/detections` | 创建任务 |
| GET | `/geo/detections/{id}` | 任务摘要和进度 |
| GET | `/geo/detections/{id}/model-progress` | 模型进度列表 |
| POST | `/geo/detections/{id}/cancel` | 取消未开始调用 |
| GET | `/subjects/{id}/geo/detections` | 检测历史 |
| POST | `/geo/reports/{report_id}/retest` | 快速或调整后复测 |

### 14.1 创建请求

```json
{
  "question_ids": ["uuid"],
  "model_ids": ["uuid"],
  "mode": "new"
}
```

服务端重新校验预计点，不能信任前端估算。

### 14.2 创建响应

```json
{
  "success": true,
  "data": {
    "detection_id": "uuid",
    "status": "queued",
    "planned_detection_points": 120,
    "quota_hold": 120,
    "status_url": "/api/v1/geo/detections/uuid"
  },
  "request_id": "uuid"
}
```

## 15. GEO 报告 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/geo/reports/{id}` | 首页报告摘要 |
| GET | `/geo/reports/{id}/questions` | 按问题分页的明细 |
| GET | `/geo/reports/{id}/questions/{question_key}` | 单问题 8 模型结果 |
| GET | `/geo/model-calls/{call_id}/response` | 完整原始回答和引用 |
| GET | `/subjects/{id}/geo/trends` | 可比趋势数据 |
| GET | `/geo/reports/{id}/comparison/{other_id}` | 可比性和并排对比 |

普通用户只能访问自己主体的报告。

## 16. 改善策略 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/geo/reports/{id}/strategies` | 首次／重新生成 |
| GET | `/strategy-jobs/{job_id}` | 进度 |
| GET | `/geo/reports/{id}/strategies` | 策略列表 |
| PATCH | `/strategies/{id}/note` | 用户个人备注 |

请求包含周期：`7d/30d/90d/custom` 和自定义天数。

## 17. 显问 AI 助手 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/assistant/respond` | 当前会话单次响应 |

请求：当前主体 ID、当前会话消息数组。后端不得保存聊天记录；仅记录一次使用日志和额度结算，不保存完整对话正文，除非安全审计要求短期脱敏缓存。

助手返回页面建议入口但不执行任务：

```json
{
  "answer": "...",
  "suggested_actions": [
    {"label": "查看检测报告", "route": "/subjects/.../reports/..."}
  ],
  "remaining_messages": 25
}
```

## 18. 文章类型与资料包 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/article-types` | 可用文章类型 |
| POST | `/articles/source-packs` | 创建资料包草稿 |
| POST | `/articles/source-packs/{id}/search` | 异步检索 |
| GET | `/articles/source-packs/{id}` | 来源、冲突和确认状态 |
| POST | `/articles/source-packs/{id}/confirm` | 用户确认来源和冲突 |

## 19. 文章 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/subjects/{id}/articles` | 文章列表 |
| POST | `/subjects/{id}/articles` | 创建文章草稿 |
| GET | `/articles/{id}` | 当前稿 |
| PATCH | `/articles/{id}/draft` | 自动保存当前稿 |
| POST | `/articles/{id}/outline/generate` | 首次或重新生成大纲 |
| PATCH | `/articles/{id}/outline` | 编辑大纲 |
| POST | `/articles/{id}/generate` | 生成正文 |
| POST | `/articles/{id}/quality-check` | 修改后复检 |
| POST | `/articles/{id}/optimize/local` | 局部优化 |
| POST | `/articles/{id}/optimize/full` | 整篇优化 |
| GET | `/article-comparisons/{id}` | 原稿和优化稿差异 |
| POST | `/article-comparisons/{id}/choose` | 选择保留 original/optimized |
| DELETE | `/articles/{id}` | 删除／回收站（如实现） |

### 19.1 生成前置

- 主体必须启用。
- 套餐有效。
- 资料包满足文章类型要求。
- 关键冲突已处理。
- 文章额度足够。

### 19.2 优化选择

请求：

```json
{"choice": "original"}
```

选择后服务端只保留选中内容；临时候选设为已结算并按清理任务删除。

## 20. 文章审核与质量

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/articles/{id}/quality` | 最新质量结果 |
| GET | `/articles/{id}/moderation` | 审核状态 |
| POST | `/articles/{id}/moderation/appeal` | 一次免费人工复核 |

## 21. 渠道适配 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/publishing-channels` | 渠道列表 |
| POST | `/articles/{id}/channel-adaptations` | 批量生成 |
| GET | `/channel-adaptation-jobs/{id}` | 进度 |
| GET | `/articles/{id}/channel-adaptations` | 关联渠道稿 |
| GET | `/channel-adaptations/{id}` | 当前稿和质量 |
| PATCH | `/channel-adaptations/{id}` | 手动编辑 |

批量响应应返回每个渠道的独立子任务状态和额度结算。

## 22. 图片 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/image-sizes` | 尺寸预设 |
| GET | `/image-styles` | 风格预设 |
| POST | `/articles/{id}/image-recommendations` | 推荐配图方案 |
| POST | `/subjects/{id}/images/generate` | 手动或文章配图生成 |
| GET | `/image-jobs/{id}` | 生成进度 |
| GET | `/subjects/{id}/images` | 主体图片库 |
| POST | `/images/{id}/save-to-library` | 临时图转主体图库 |
| POST | `/images/{id}/derive` | 普通裁剪或 AI 智能处理 |
| POST | `/images/batch-download` | 生成 ZIP 下载任务 |
| DELETE | `/images/{id}` | 回收站 |
| POST | `/images/{id}/restore` | 恢复 |
| POST | `/images/{id}/moderation/appeal` | 人工复核 |

## 23. 发布链接检测 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/publication-checks` | 即时检测 |
| GET | `/publication-checks/{id}` | 检测结果 |
| GET | `/subjects/{id}/publication-checks` | 历史记录 |

请求：主体、原文章或渠道稿、渠道、URL。

结果：`success/failed/unknown`，标题、匹配摘要、失败原因和检测时间。

## 24. 报告导出与分享 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/geo/reports/{id}/exports` | PDF/Word/Excel |
| GET | `/report-exports/{id}` | 导出任务和短期下载地址 |
| GET | `/subjects/{id}/white-label` | 默认白标配置 |
| PUT | `/subjects/{id}/white-label` | 保存默认配置 |
| POST | `/geo/reports/{id}/shares` | 创建完整报告分享 |
| GET | `/geo/reports/{id}/shares` | 用户自己的分享列表 |
| DELETE | `/report-shares/{id}` | 关闭分享 |

公开接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/public/report-shares/{token}` | 密码校验前摘要或报告 |
| POST | `/public/report-shares/{token}/unlock` | 输入密码建立短期访问会话 |
| GET | `/public/report-shares/{token}/pdf` | 下载 PDF |

分享令牌必须高熵，数据库只保存哈希。

## 25. 使用记录、通知、公告和反馈

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/usage-records` | 用户业务任务记录 |
| GET | `/notifications` | 站内消息 |
| POST | `/notifications/{id}/read` | 标记已读 |
| POST | `/notifications/read-all` | 全部已读 |
| GET | `/announcements` | 当前可见公告 |
| POST | `/feedback` | 提交反馈 |
| GET | `/feedback` | 用户自己的反馈 |
| GET | `/feedback/{id}` | 详情和回复 |

## 26. 管理后台 API 分组

后台统一前缀：`/api/v1/admin`。

### 26.1 用户和审核

- `/admin/users`
- `/admin/users/{id}`
- `/admin/users/{id}/review`
- `/admin/users/{id}/freeze`
- `/admin/users/{id}/sessions/revoke`
- `/admin/users/{id}/support-view-request`

### 26.2 套餐与额度

- `/admin/plans`
- `/admin/plan-versions`
- `/admin/subscriptions`
- `/admin/package-applications`
- `/admin/quota-adjustments`
- `/admin/quota-ledger`

### 26.3 客户记录

- `/admin/customers`
- `/admin/customer-statuses`
- `/admin/customer-tags`
- `/admin/customer-contact-logs`
- `/admin/followups`

### 26.4 主体和风险

- `/admin/subject-types`
- `/admin/subject-fields`
- `/admin/risk-types`
- `/admin/risk-rules`
- `/admin/subject-reviews`

### 26.5 模型和密钥

XW-0402 已实现：

- `GET /admin/ai-models`
- `GET /admin/ai-models/{id}`
- `POST /admin/ai-models/{id}/enable`
- `POST /admin/ai-models/{id}/disable`
- `POST /admin/ai-models/{id}/pause`
- `POST /admin/ai-models/{id}/unpause`
- `GET /admin/ai-model-runtime-configs`
- `GET/PATCH /admin/ai-model-runtime-configs/{id}`

读取要求 `models.list`，写入要求 `models.manage`；写入使用 CSRF 与 `expected_version`，
冲突返回稳定错误码。响应不返回 API key、token、secret 或 provider raw response。

以下密钥和真实调用相关端点仍由 XW-0403 及后续任务实现：

- `/admin/api-credentials`
- `/admin/api-credentials/{id}/rotate`
- `/admin/api-credentials/{id}/test`
- `/admin/system-test-quotas`

只有超级管理员可访问密钥相关端点。

### 26.6 提示词

- `/admin/prompt-templates`
- `/admin/prompt-versions`
- `/admin/prompt-test-cases`
- `/admin/prompt-test-runs`
- `/admin/prompt-versions/{id}/publish`
- `/admin/prompt-versions/{id}/rollback`

### 26.7 任务和审核

- `/admin/tasks`
- `/admin/tasks/{id}/retry`
- `/admin/tasks/{id}/cancel`
- `/admin/moderation/articles`
- `/admin/moderation/images`

### 26.8 模板和渠道

- `/admin/question-categories`
- `/admin/article-types`
- `/admin/article-template-versions`
- `/admin/publishing-channels`
- `/admin/channel-template-versions`
- `/admin/image-size-presets`
- `/admin/image-style-presets`

### 26.9 公告、反馈和统计

- `/admin/announcements`
- `/admin/feedback`
- `/admin/dashboard`
- `/admin/analytics/*`
- `/admin/exports`

### 26.10 安全和审计

- `/admin/roles`
- `/admin/permissions`
- `/admin/approval-workflows`
- `/admin/approval-requests`
- `/admin/audit-logs`
- `/admin/system-alerts`
- `/admin/backups`

## 27. 异步任务状态规范

所有任务响应包含：

```json
{
  "id": "uuid",
  "type": "geo_detection",
  "status": "queued",
  "progress": 0,
  "created_at": "...",
  "started_at": null,
  "finished_at": null,
  "result_id": null,
  "user_message": "任务正在排队",
  "quota": {
    "type": "detection_points",
    "frozen": 120,
    "deducted": 0,
    "refunded": 0
  }
}
```

状态：`draft/queued/running/reviewing/partial/succeeded/failed/cancelled/expired`。

## 28. 轮询建议

- 排队／执行：前 30 秒每 2 秒；之后每 5 秒。
- 页面后台或不可见时降低到 15–30 秒。
- 完成后停止。
- 服务端对状态接口做用户级限流和缓存。

## 29. API 安全

- 所有对象查询必须后端校验所有权，禁止仅通过前端隐藏。
- 管理后台端点同时校验角色权限和客户数据范围。
- 文件下载使用短期签名 URL。
- URL 抓取和发布检测必须防 SSRF：禁止内网、回环、元数据地址和非 HTTP(S) 协议。
- 对列表、搜索、导出和公开分享限流。
- 公开分享页面不得泄露用户账号信息。

## 30. OpenAPI

`openapi/openapi-v1.yaml` 提供启动骨架。Codex 每完成一组接口，必须同步更新 OpenAPI，不允许文档长期落后于实现。

## XW-0113 implemented quota API note

The OpenAPI 3.1 file is authoritative. XW-0113 implements user reads
`GET /quotas` and `GET /quota-ledger`, administrator scoped reads
`GET /admin/quota-accounts` and `GET /admin/quota-ledger`, plus fixed
two-person grant/compensate/manual-deduct adjustment endpoints below
`/admin/quota-accounts/{account_id}/adjust`. There is no public reset,
freeze, consume, or release endpoint in XW-0113.
