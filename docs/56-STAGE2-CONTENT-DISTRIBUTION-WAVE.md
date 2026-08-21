# Stage 2 内容生成、分发与分享 Macro Wave

## 1. 冻结范围与拆分结论

本波实现 `XW-0601`—`XW-0609`、`XW-0701`—`XW-0703`、`XW-0802`—`XW-0803`，并复用已交付的 `XW-0801` 报告导出。它们共享主体版本、已确认来源、文章额度、私有存储和报告快照边界，能够在一个可审计的 migration/topology wave 内完成。

本文件记录 PR #43 时的非图片交付边界。后续总指挥已冻结 Ark ImageGenerations、capability credential binding 与 S3-compatible private storage 开发合同，`XW-0710`—`XW-0717` 的实现与验证见 `docs/57-STAGE2-IMAGE-WAVE.md`；真实生产凭据/COS smoke 仍不属于本波。

## 2. 来源与文章证据

- 文章类型、文章模板版本、发布渠道和渠道模板版本由数据迁移建立稳定目录；模板版本不可修改或删除。
- 资料包只接受当前正式主体版本、本人同主体的用户确认文件解析版本和网页确认版本。开放网络内容不会直接进入资料包。
- 资料项以 digest、来源类型和确认状态保存；`fact:/事实:` 关键事实冲突必须由用户选择有效候选值后才能确认。
- 确认会冻结完整来源快照和 digest。PostgreSQL trigger 阻止确认后的资料包或资料项被修改、回退或删除。
- 文章只保留一个可编辑当前稿。首次 AI 正文、引用和 normalized generation result 独立保存并不可覆盖；provider 原始 JSON、prompt、credential 和隐藏推理不入库也不出 API。

## 3. 生成、审核、质量与优化

- 支持直接正文或先大纲。首次大纲免费，后续成功使用主体周期 `outline_regenerations`。
- 正文生成绑定 subject/version、article type/template、source-pack snapshot/digest、DeepSeek runtime、adapter/prompt/schema 和请求 digest。
- 自动审核结果为 `passed` 或 `manual_review`；未通过期间阻止导出和渠道适配。人工记录追加保存，每篇最多一次申诉。
- 首次正文质量检测包含在正文生成内。复检成功使用 `quality_rechecks`。固定权重为主体一致性 25、事实可靠性 25、主题相关性 15、结构完整性 15、可读性 10、关键词自然度 10；结果只提供建议，不因低分阻止导出或分发。
- 局部优化成功使用 `local_ai_edits`，整篇优化成功使用 1 `article_credits`。原稿/优化稿只作短期比较；用户选择后只保留所选当前稿并清空两份临时正文。
- 导出支持 Word、PDF、TXT、Markdown 和经过 HTML escaping 的 HTML，使用既有私有 storage abstraction 和安全对象键。

## 4. 额度、幂等与并发

- 正文、整篇优化和每个独立渠道稿在调用 provider 前冻结 1 个 `article_credits`；合法成功后消费，provider/网络/schema/引用失败后释放。
- 首次大纲没有 hold；大纲重生成、局部优化和质量复检分别使用既有主体周期额度。
- HMAC 幂等摘要使用独立 `ARTICLE_IDEMPOTENCY_HMAC_KEY`。相同用户、命名空间、幂等键和请求快照只产生一个任务/hold；同键不同请求返回冲突。
- 请求公开 system/developer prompt、provider 原始载荷、credential、API/encryption/private key 或 access token 的主动生成/优化指令会在 runtime 与额度冻结之前以 `ARTICLE_SECURITY_REFUSED` 拒绝；冻结资料内容仍按不可信 data 隔离，不作为指令执行。
- PostgreSQL 行锁、唯一摘要约束和 quota hold ledger 共同防止并发双调用与双扣。Strategy 的 topic-intent 路由只预填文章主题，不创建任务或扣额度。

## 5. 渠道与发布链接

- 稳定渠道为企业官网、微信公众号、知乎和小红书。系统只返回官方入口、当前模板规则、独立适配稿和质量分。
- 每个渠道是独立任务与额度结算；批量创建在初始冻结失败时整体回滚，执行失败则按渠道分别释放。
- `actual_publishing_supported=false` 是固定 API 事实。系统不代登录、不持有第三方发布 credential、不调用真实发布 API，也不把适配稿标为已发布。
- 发布链接只执行一次既有 SSRF-safe HTTP(S) fetch 与正文匹配，返回 `success`、`failed` 或 `unknown`；不创建定时复检。

## 6. 白标与完整报告分享

- 白标受冻结套餐 `white_label_enabled` 控制；无权益或无配置时必须使用“显问 GEO”默认品牌。Logo/cover 只能引用本人同主体的已验证私有图片版本。
- 分享受 `report_share_enabled` 控制。创建时冻结完整报告、全部问题与回答以及当时品牌快照。
- 原始 32-byte+ 随机 token 仅在创建 URL 中返回一次；数据库只保存独立 `REPORT_SHARE_HMAC_KEY` 的 digest。可选密码只保存 Django password hash。
- 支持有效期、不可逆 close、访问计数、最近访问时间和追加式访问日志。日志仅保存 HMAC IP digest、截断 User-Agent、结果和时间。
- 匿名密码解锁使用失败限速及 HttpOnly、SameSite=Lax、生产 Secure 的短期签名 Cookie。公共响应不含 token digest、password hash、内部对象键或私有报告关系。
- 应用请求、异常和 CSRF 日志会把公开分享路径中的 token 替换为 `[REDACTED]`；生产 Nginx/边缘访问日志也必须使用不记录该路径参数的过滤格式。
- 公共 PDF 使用冻结品牌和不可变报告事实，通过既有私有导出/storage 返回短期下载地址。

## 7. API、部署与验证

- 所有 owner API 使用 Session、CSRF、active-user permission、对象 ownership 和 `Cache-Control: no-store`；公共分享端点显式匿名并保持独立密码/有效期/revoke 边界。
- 新列表提供稳定数据库排序和分页；目录端点仅返回固定小目录。
- 新增生产 secret：`ARTICLE_IDEMPOTENCY_HMAC_KEY`、`REPORT_SHARE_HMAC_KEY`。两者必须至少 50 字符、相互独立，且不得复用 Django、quota、provider、database、Redis 或 storage credential。
- 文章生成复用现有 `ai_content` worker、DeepSeek registry/runtime 和 S3-compatible storage abstraction；无新 Python/npm/provider 依赖。
- SQLite targeted：`pytest tests/test_stage2_content_distribution.py`。
- PostgreSQL 专属：`scripts/test-stage2-content.ps1` 或 `scripts/test-stage2-content.sh`，安装真实迁移后验证 trigger 原始 SQL 篡改拒绝及并发幂等。
- 前端 targeted：`vitest run tests/stage2-content-distribution-interactions.test.tsx`。
- 全量门禁：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 all`。

## 8. 回滚边界

回滚应用版本前先停止新文章/分享写入并保留数据库备份。新表含不可变证据和 quota hold 外键，不允许通过业务 DELETE 清理。若必须回滚 schema，应使用经过单独审计的数据保留迁移；不得删除历史 generation、quality、moderation、export、publication check、share snapshot 或 access log 证据。
