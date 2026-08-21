# Stage 2 Image Macro Wave（XW-0710～XW-0717）

本波使用独立 Volcengine Ark / Doubao 图片适配器调用 `POST https://ark.cn-beijing.volces.com/api/v3/images/generations`，API 合同参考版本为 `2024-01-01`。图片调用不复用 GEO detection `/responses` 路径，也不提供占位图或 fake success。

生产调用的 `provider_model_id` 来自 `ai_capability_runtime_configs` 中 `doubao + image_generation` 的显式批准配置。适配器凭据只允许通过加密 `APICredential` 和 `api_credential_capability_bindings` 解析；图片能力不能自动继承 detection binding。任务创建时冻结 runtime、binding 与 credential 版本，执行前再次核对，配置漂移时 fail closed。

应用流程为：验证主体、文章、预设和参考图 → 冻结每张图 1 个 `image_credits` → Celery `image_generation` 队列 → 同步 Ark ImageGenerations 调用 → 安全下载供应商临时 URL 或解码 `b64_json` → Pillow 验证 MIME、尺寸、像素、动画和大小 → 写入 S3-compatible private storage 并 HEAD 校验 → 建立归一化资产/审核证据 → 仅此时消费额度。网络、超时、结构、审核、下载、媒体或存储失败均终态释放；429/供应商额度只按冻结 runtime 的有限次数重试。

用户 API 覆盖配图推荐、单图/批量子任务、任务轮询、主体图库、文章选择、回收站、一次复核、普通衍生图和私有 ZIP。普通压缩、裁切、格式和渠道图由 Pillow 完成，`ai_used=false` 且不扣图片额度；需要 AI 产生新图时走新的图片任务并扣额度。

安全边界包括 owner/subject/article 绑定、参考图互斥、外部 URL DNS pinning 与 SSRF 拒绝、私有对象 UUID key、短期签名下载、不可变 provenance/evidence、HMAC 幂等键、终态任务和证据 PostgreSQL trigger，以及前端不接收提示词、密钥、供应商原始 JSON 或供应商临时 URL。

Development/CI 使用现有 mock/S3-compatible storage abstraction 和 contract adapter tests。真实 Stage/Production Ark credential provisioning、Tencent COS private bucket/endpoint/region/lifecycle 与真实 HTTPS smoke 是 Stage 3 deployment/UAT release gate；生产缺少私有 storage、runtime 或 capability credential binding 时服务 fail closed。
