# XW-0205 私有文件上传与对象存储抽象

## 边界

本任务实现私有对象存储协议、受大小约束的预签名 POST、异步安全验证 Saga、存储容量核算，以及主体动态 `image/file` 字段对不可变 `DocumentVersion` 的引用。开发与验收使用 S3 兼容 MinIO；腾讯 COS 生产适配、解析/OCR、文件替换/删除、网页导入和 AI 处理均未实现。

PostgreSQL 是上传状态、幂等、长期存储占用和额度结算的唯一事实源。Redis/Celery task ID 只负责投递，不承担 exactly-once。

## 上传状态与 Saga

`pending_upload -> verifying -> completed|rejected`，或未完成直传的 `pending_upload -> expired`。`complete` 只 HEAD 确认对象、写入 `verifying` 并返回 HTTP 202；流式摘要、结构校验、恶意文件扫描和 staging 到 final 的复制在 worker 中执行。

对象网络 IO 不置于长数据库事务。最终短事务按 User、Subscription、QuotaAccount、Intent/Hold 顺序锁定，在同一提交中创建 `UserDocument`、不可变 `DocumentVersion`、不可变 `FileStorageAllocation`，并结算 Hold。复制成功而数据库失败时重试同一 opaque final key；匹配才续跑，不匹配则失败关闭。

## 配置与生产安全

- `FILE_STORAGE_PROVIDER=s3|mock|unavailable`
- `FILE_SCANNER_PROVIDER=mock|unavailable`（真实生产 scanner adapter 留待部署集成）
- `FILE_IDEMPOTENCY_HMAC_KEY` 必须独立、足够强，且不得复用 Django、短信、额度、数据库、Redis 或 S3 密钥。
- production 禁止 mock provider/scanner；未配置真实能力时应用可启动，但上传接口通用 503 失败关闭。
- bucket 必须 private，CORS 仅允许配置的应用 origin。credential 短期且响应 `no-store`。

对象 key 为高熵无业务语义标识，不包含手机号、姓名、原文件名或 Subject 信息。API 不返回 canonical bucket/key、摘要、scanner 原始输出、ETag 或密钥。

## 存储容量

`storage_bytes` 是 absolute capacity，不参与累加、保留、carryover、transfer 或月度 reset。长期占用只由 `FileStorageAllocation` 聚合。新订阅账户初始化后以追加式 `storage_capacity_reconcile` 流水收敛为 `max(entitlement - usage, 0)`；占用超过新套餐上限不阻断套餐生效，但禁止新增上传。

上线前按顺序运行：

```text
python manage.py reconcile_storage_capacity --dry-run
python manage.py reconcile_storage_capacity --apply
python manage.py reconcile_file_objects --dry-run
```

命令不删除历史 Ledger，不伪造历史 Allocation，不输出文件名或对象 key。对象清理仅处理数据库明确标记的 opaque staging key，且有界、幂等。

## 主体文件字段

草稿值固定为 `{ "document_version_id": "<uuid>" }`。引用必须属于同一用户、同一 Subject 且上传状态为 completed/clean；image 只接受 JPEG/PNG/WEBP。正式提交同步创建不可变 `SubjectVersionDocumentReference`，历史版本不依赖 mutable document 或 URL。

## 回滚

文件证据和额度流水为不可变审计事实。生产回滚优先前向修复或备份恢复；不得通过逆向迁移删除 `DocumentVersion`、`FileStorageAllocation`、关系引用或 Ledger。停用上传时配置 provider/scanner 为 unavailable 即可失败关闭，既有 completed 文件仍保持私有可读。
