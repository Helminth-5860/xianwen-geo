# XW-0301 关键词数据模型和编辑器

## 范围

XW-0301 建立人工维护关键词的独立领域。它不实现 AI 生成、Celery 任务、蒸馏、问题库或关键词额度结算。

## 数据模型

- `KeywordSet`：一对一绑定 Subject，保存草稿基础 SubjectVersion、当前正式关键词版本和乐观并发版本号。
- `KeywordDraftItem`：可增删改和排序的普通草稿数据。
- `KeywordSetVersion`：不可变正式版本头，绑定提交时的正式 SubjectVersion。
- `Keyword`：不可变正式关键词快照项。

关键词结构类型为 `short / long_tail / general`。地域属性与结构类型正交，V1 使用 `is_regional + region_level + region_text`；内部 `region_matching_key` 仅用于稳定匹配，不对 API 暴露。

## 规范化和重复语义

关键词与地域文本统一执行 NFKC、Unicode 空白折叠、首尾去空白、Cc 控制字符拒绝和 casefold 匹配。草稿和正式版本中的重复键为：

`(matching_text, region_matching_key)`

因此同一文本、同一地域不能靠不同结构类型重复；同一文本可以在不同地域中分别存在。

## 写入资格

人工关键词写操作要求：

- 用户审核通过；
- 账号 active；
- 有当前有效 Subscription；
- Subject 为 draft 或 active；
- Subject 已存在 current formal SubjectVersion。

archived Subject 只读。XW-0301 不读取或扣减关键词生成额度，也不调用 XW-0204 feature guard。

## 草稿和正式版本

`PATCH /subjects/{id}/keywords/draft` 使用 `expected_version + expected_subject_version_id` 原子替换完整有序草稿。相同 canonical 草稿且基础 SubjectVersion 未变化时返回 no-op，不增加 KeywordSet version。

`POST /subjects/{id}/keywords/commit` 只能从服务器草稿复制正式快照。第一版为 v1，后续严格连续，`current_version` 永远指向最大版本。相同 SubjectVersion + 相同 semantic digest 返回 `KEYWORD_VERSION_NO_CHANGES`。

若 SubjectVersion 已变化，旧页面不得静默 rebind；用户必须刷新并明确保存到新的 SubjectVersion 后才能提交新的关键词版本。

## XW-0302 / XW-0303 边界

XW-0302 未来只能通过 keywords 内部 replace-draft service 写草稿，并使用 expected KeywordSet version 和 expected SubjectVersion 防止覆盖人工编辑；不得直接创建正式 KeywordSetVersion。

XW-0303 可绑定不可变 KeywordSetVersion / Keyword UUID。XW-0301 不提前加入蒸馏字段、AI provider、prompt/model、Celery job 或 quota hold/ledger。

## 数据库保护

PostgreSQL guards 保护：

- KeywordSet ownership/binding；
- 正式 KeywordSetVersion/Keyword 的 UPDATE/DELETE；
- 严格连续版本号；
- current_version=max；
- finalized version 禁止追加 Keyword；
- 正式位置连续；
- 跨 Subject/User/SubjectVersion 绑定。

草稿仍是普通应用数据，不做 append-only event ledger 或 UPDATE/DELETE trigger。

## 验证

专属真实 PostgreSQL 验证：

```bash
bash scripts/test-keywords.sh
```

Windows：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test-keywords.ps1
```

完整统一门禁仍使用 `scripts/check.ps1 all` / `scripts/check.sh all`。
