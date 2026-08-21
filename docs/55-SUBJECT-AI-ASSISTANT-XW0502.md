# XW-0502 当前主体 AI 助手

## 1. 冻结业务语义

- Provider 固定 DeepSeek，并复用已有 runtime、registry、credential resolver。
- 后端 `SubjectContext.current_subject` 是唯一授权主体；请求中的 subject ID 必须与它相等。
- 正文写入其他主体 ID/名称不会切换 scope。切换主体必须走现有主体上下文 API，随后新请求立即构建新上下文。
- 助手是问答与导航能力，不修改主体、不发起检测、不生成策略或文章、不执行管理员任务、不修改报告/评分/历史。
- 前端只在当前页面内保存临时 transcript；刷新不恢复。

## 2. 允许上下文

每次请求重新构建：

- 当前主体版本中 `used_for_ai=true` 的字段、当前名称与产品；
- 同一用户、同一逻辑主体最近最多 5 份不可变报告摘要；
- 同一用户、同一逻辑主体最近最多 3 份成功策略正文。

不读取其他主体，不使用用户消息指定的对象扩大查询，不返回原始 provider payload、系统 prompt、credential 或隐藏推理。

## 3. 不保存聊天正文

数据库只新增 `assistant_usage_events`，字段限于 user/subject/version/subscription/quota hold、状态、DeepSeek provenance、上下文/请求/幂等摘要、safe error、token usage 和时间戳。

不存在 chat session/message/transcript 表，也不存在 user message、assistant answer 或 reply/content 正文列。安全拒绝在 provider 和 quota 之前完成，不需要保存敏感请求正文。

## 4. 安全拒绝

后端在构建 provider 请求前拒绝：其他主体/用户数据、系统或开发者提示词、API/provider credential、secret/key、加密键、原始 provider JSON，以及忽略既有指令等 prompt injection。

返回稳定的 scope/security refusal 错误，不把拒绝交给前端判断，也不把受保护文本传给 provider。

## 5. 额度与幂等

- 使用现有账号周期 `assistant_messages`。
- provider 前冻结 1；合法结构回复成功后消费 1；provider/网络/结构失败释放 1。
- 安全拒绝发生在冻结前，不消费。
- 用户行锁、quota business hold 和 HMAC 幂等摘要防止并发重复调用与双扣。
- 幂等重放返回稳定冲突而不再次调用 provider；因为契约禁止持久化回复正文，服务端不伪造可重放回答。
- 不修改 detection、article、strategy 或任何其他 quota。

## 6. API 与 UI

- `GET /assistant/context` 返回当前主体身份和剩余账号周期次数，不返回历史。
- `POST /assistant/respond` 接收当前主体 ID 与本页临时消息，最后一条必须是 user；最多 12 条、单条 2000 字、总计 8000 字。
- 成功返回本次 answer、服务端白名单导航、剩余次数、usage event ID 和 `history_persisted=false`。

UI 展示当前主体选择、临时会话、loading、回复、失败重试、安全拒绝、剩余额度和不保存聊天记录声明。切换主体立即清空页面 transcript 并重新读取服务端上下文。
