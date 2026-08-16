# XW-0305 问题库生成和编辑

## 1. 范围

XW-0305 从当前已确认的 DistillationSet 和其绑定的 SubjectVersion 生成问题建议，
允许用户在草稿中修改问题文本、一个主分类、多个辅助标签、优先级、
自然探索／品牌指向类型以及是否参与检测。用户明确确认后，系统创建连续且不可变的
QuestionBankVersion。本任务不创建 GEO 检测、检测快照、评分、报告或策略。

## 2. 四层边界

1. QuestionGenerationJob/Event 保存 durable lifecycle 和安全事件。
2. QuestionGenerationResult 保存经过结构校验的原始 AI provenance，不保存 raw response。
3. QuestionBankWorkspace/QuestionDraftItem 是用户可修改工作区。
4. QuestionBankVersion/Question/QuestionTagLink/QuestionKeywordLink 是不可变正式历史。

生成成功只会原子替换工作区，不会直接创建正式版本，也不会修改
KeywordSetVersion、Keyword、DistillationSet 或 DistillationItem。

## 3. 上游和目录

- 只接受主体 owner 的当前、已确认蒸馏版本。
- 蒸馏版本必须绑定主体当前正式版本；输入变化时任务 fail closed。
- 有效生成关键词由 keep 和去重后的 merge canonical keyword 组成；
  delete 与 low_value 不进入生成输入。
- 分类和标签只使用 XW-0304 中启用且适用于主体类型的目录项。
- 正式问题保存 category/tag 的稳定 key、名称和目录版本快照，目录后续合法修改不改写历史。

## 4. Provider 和安全

Provider 接收结构化冻结输入，并返回结构化问题数组。主体字段和关键词文本是“不可信数据”，
不是 system/developer 指令。响应必须通过 NFKC、空白折叠、控制字符拒绝、casefold 去重、
目录/关键词 ID 白名单、枚举和套餐上限校验。

Job 保存 provider、model、adapter、prompt version、input/output digest 和白名单 metrics；
日志、Event 和 API 不返回完整 prompt、主体输入、API key 或 provider raw response。
local/test 支持 Mock；Production 禁止 Mock，真实 provider 未实现时仅允许 unavailable。

## 5. 异步和结算

任务复用 ai_content 队列，状态为
queued/running/retry_wait/succeeded/failed/conflict/superseded。
lease generation、stale recovery 和 late-worker token 防止旧 worker 应用结果。

每主体第一次成功写入问题草稿免费。已有成功历史时，客户端必须显式提交
regenerate=true；服务端冻结既有 question_bank_regenerations 1 次。
只有结构化结果和完整草稿原子写入成功才 consume。永久失败、重试耗尽、输入变化、
workspace 冲突和 superseded 都对原 hold exactly-once release。人工编辑和确认不扣额度。

## 6. 并发、版本和 PostgreSQL

- 创建任务要求 Idempotency-Key；只保存派生 HMAC digest。
- 同主体最多一个 active job。
- workspace 写入要求 expected_version。
- 正式 version_no 从 1 严格连续，current 必须指向最大版本。
- PostgreSQL guards 保护 job 冻结事实、终态/hold 结算、result/history append-only、
  workspace 单步版本和 formal version 绑定。

## 7. API

- POST /api/v1/subjects/{id}/question-banks/generate
- GET /api/v1/question-bank-jobs/{job_id}
- GET|PATCH /api/v1/subjects/{id}/question-banks/draft
- POST /api/v1/subjects/{id}/question-banks/confirm
- GET /api/v1/subjects/{id}/question-banks/current
- GET /api/v1/subjects/{id}/question-banks/versions
- GET /api/v1/subjects/{id}/question-banks/versions/{version_id}

## 8. 部署影响

新增 QUESTION_GENERATION_PROVIDER、独立 HMAC、timeout/retry/lease/internal retry 和
Mock scenario 环境变量。新增 questions migrations、questions.execute_generation 和
questions.dispatch_generation_jobs；任务仍使用现有 ai_content/Redis broker，
不新增端口。部署顺序为配置环境变量、执行 migration、更新 worker/web、最后更新 beat。
