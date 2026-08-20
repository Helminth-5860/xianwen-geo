# XW-0421 / XW-0422 GEO 报告、复测与可比趋势

## 1. 交付边界

本波次把 XW-0418/XW-0419 的冻结评分事实接入正式报告读模型，并复用 XW-0420 的检测进度流。范围包括报告首页、按问题明细、原文懒加载、PDF/Word/Excel 后台导出、快速/调整后复测、历史与事实可比趋势。分享、白标配置 UI 和改善策略仍属于后续任务。

## 2. 报告固化时机与不可变性

检测任务进入终态后并不立即代表评分完成。`prepare_report` 只有在所有成功且参与评分的回答都已有不可变 `ScoreResult`，并且每个模型的预期 track 已形成 `ModelScoreResult` 后才创建 `GeoReport`。因此进度页可能短暂显示“正在完成评分与报告固化”，不会把半成品分数冻结进历史。

每个 detection 最多一个报告。报告冻结：

- logical subject 与本次 subject version；
- baseline/retest 关系和复测模式；
- 问题来源 ID、文本、类型、计分参与状态和排序的签名；
- 逻辑模型 ID/key 集合签名；
- prompt、评分规则与语义评分来源；
- GEO、口碑、曝光、模型、六维、竞品摘要；
- detection job 与生成时间。

Django 模型禁止更新/删除，PostgreSQL trigger 同时拒绝绕过 ORM 的 `UPDATE/DELETE`。`DetectionRetest` 同样不可变。`ReportExport` 只允许 queued → running → succeeded/failed 生命周期更新，历史记录禁止删除。

## 3. 报告读取

- `GET /geo/detections/{id}/report`：评分完成后幂等生成/恢复报告；未就绪返回状态冲突。
- `GET /geo/reports/{id}`：首页冻结摘要和基线比较。
- `GET /geo/reports/{id}/questions?page=N`：每页十个问题；返回模型状态、安全错误摘要、关键片段、单题评分和已验证引用，不返回完整大文本。
- `GET /geo/model-calls/{id}/response`：仅在用户展开时返回自己报告内的完整原始回答和安全引用。
- `GET /subjects/{id}/geo/reports`：不可变历史。
- `GET /subjects/{id}/geo/trends`：按事实签名形成可比序列。
- `GET /geo/reports/{id}/comparison/{other_id}`：同主体两份报告的事实比较。

所有读取都按报告/主体 owner 约束，其他用户和越权 call ID 统一不可见。响应设置 `Cache-Control: no-store`。

## 4. Quick Retest 最终语义

快速复测的确定性顺序是：

1. 校验 baseline report ownership 与同一 logical subject；
2. 读取 baseline detection 的不可变问题快照和精确逻辑模型集合；
3. 解析提交时当前 active subject version；
4. 对精确模型集合重新检查当前套餐 entitlement、模型 permission、enabled、paused、runtime、credential 和 adapter；
5. 在 job/quota hold 之前完成上述 preflight；
6. 创建独立 detection，复制 baseline 问题快照事实，建立精确模型 runs/calls；
7. 使用当前评分规则，进入已有 `/geo/detections/{new_id}` 进度页。

当前 question-bank version 或 membership 变化不会阻止 Quick Retest。新 detection 的问题快照继续引用 baseline 历史 question identity/text；keyword、distillation 和 question-bank 字段保留 baseline derivation provenance，而 subject version 使用当前值。

任何 baseline 模型当前不可合法执行时 fail closed，并返回 blocking `model_key`、reason 和建议动作。不会替换、删减或增加模型，也不会创建 job、run、quota hold 或 consumed point。用户可稍后重试、恢复权限/runtime，或显式使用 Adjusted Retest。

## 5. Adjusted Retest

Adjusted Retest 从当前正式题库和当前合法模型中重新选择，调用正常 detection 创建服务，并生成独立 detection/report。动作名称不决定可比性；最终选择如果恰好保持相同冻结事实，仍可正式比较。

## 6. 可比性与趋势

正式可比要求同时满足：

- 相同 logical subject；
- 问题不可变身份/内容签名完全相同；
- 逻辑模型集合签名完全相同；
- scoring rule version 相同。

subject version 可以变化，仍可正式比较，但返回并展示 `subject_version_changed=true`。评分规则变化时保留两份绝对报告并标记 `scoring_version_changed=true`，不重算 baseline，不返回总分、模型、六维或曝光正式 delta。问题或模型不同也只允许并排查看，不连接正式趋势。

## 7. 导出

`POST /geo/reports/{id}/exports` 创建后台任务，支持 `pdf/word/excel`。导出只读取报告冻结 summary/provenance，保存品牌快照，写入 `system/report-exports/{report}/{export}.{pdf|docx|xlsx}`。`GET /report-exports/{id}` 返回状态和成功后短期下载地址；过期后不再签发 URL。存储错误只持久化安全错误码。

## 8. 验证证据

自动化覆盖：题库变化/历史题脱离 current membership、当前 subject version、主体版本变化仍可比、entitlement/paused/disabled 原子失败、无模型替换、评分版本变化禁用 delta、Adjusted 不同/相同选择的事实判定、权限、问题分页/原文懒加载、三种导出和 PostgreSQL 原始 SQL 防篡改。前端覆盖报告模块、懒加载、主体版本 marker、Quick Retest 路由与阻断原因。
