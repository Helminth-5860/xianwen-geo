# XW-0208 主体 AI 补充 Mock 和流程

## 边界

- 这是正式 SubjectVersion 提交前的草稿辅助，不绕过 XW-0203/XW-0204。
- 仅使用用户明确选择的当前已确认文件/网页版本。
- 仅实现 `mock` 与 `unavailable` Provider；生产禁止 Mock，真实 AI Provider 不在本任务实现。
- AI 建议是不可变历史事实；只有用户批量确认后的 accepted suggestion 才写入 `Subject.draft_values`。
- 不新增或挪用任何 quota，不保存 Provider raw response，不把来源正文写日志。

## 异步语义

`queued -> running -> succeeded | retry_wait | failed`，`retry_wait -> running`。PostgreSQL 保存任务、generation、重试、Suggestion 与 Confirmation；Celery/Redis task id 不是 exactly-once 真相。外部 Provider 调用只能准确表述为 at-least-once。

## 输入边界

默认最多 8 个来源、单来源 20,000 字符、总来源 80,000 字符、20 个目标字段、30 秒 Provider timeout。主体正式名称作为冻结上下文输入，但不是 AI 建议目标。

## 安全

来源正文是 untrusted data block，不是 system instruction。Provider 无工具、浏览器、文件系统或任意网络能力。输出必须匹配 target manifest、confirmed source ids 与 frozen field validators。API/Event/日志不暴露 prompt、正文、digest、raw Provider response 或 secret。
