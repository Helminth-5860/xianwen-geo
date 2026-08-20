# XW-0501 GEO 改善策略

## 1. 冻结业务语义

- 输入只来自目标 `GeoReport` 的不可变 summary/provenance 和该报告绑定的 `SubjectVersion` 中 `used_for_ai=true` 的字段、名称与产品。
- 不读取最新主体版本替换历史事实，不重新执行检测、模型回答、程序评分或语义评分。
- 周期支持 `7d`、`30d`、`90d`、`custom(1..365)`。
- “首次免费”指每份报告第一次成功的策略；失败不占用该成功名额。
- 报告已有成功策略后必须显式确认重生成。每次重生成创建新行，绝不覆盖历史 AI 正文。
- 内容是建议，不是任务管理；推荐文章主题只携带 topic intent 进入 Stage 2 边界页，不创建文章、不调用模型、不消费 `article_credits`。

## 2. 持久化与状态机

`strategy_reports` 绑定 report、subject、subject version、subscription、周期、结算模式、不可变输入事实、DeepSeek provenance、幂等摘要、状态和最小 usage。

合法状态跳转：

- `queued -> running -> succeeded|failed`
- 队列提交失败允许 `queued -> failed`

AI 正文只能在 `running -> succeeded` 时写入一次。终态和绑定不可更新，历史不可删除。Django 模型状态机提供数据库无关的保护；PostgreSQL `strategy_reports_guard` 进一步验证初始态、绑定、跳转、终态、删除和 quota settlement。

`strategy_notes` 与 AI 正文分离，一份策略至多一条，允许用户创建、更新、删除，使用递增 version 防丢失更新，不安装不可变 trigger。

## 3. 额度与幂等

- `free_initial` 不创建 quota hold。
- `regeneration` 复用现有 quota engine 的 `strategy_regenerations` subject-cycle account。
- 创建时冻结 1；合法结构结果落库前消费 1；provider、队列或结构失败释放 1。
- 用户行锁、活动策略条件唯一约束、业务 hold 唯一约束和命名空间 HMAC 幂等摘要共同防止并发双建、重复 provider 调用和双扣。

## 4. AI 与安全

策略固定使用现有 DeepSeek runtime、模型注册表和数据库凭据解析器；无新密钥、环境变量或网络拓扑。

系统指令把全部输入视为不可信数据，禁止泄露 prompt、credential、隐藏推理、provider payload，禁止伪造报告事实或描述成可执行任务。Provider 只返回 JSON，服务端按固定 Schema 严格归一化后才允许成功。

持久化和 API 只暴露安全 provenance（provider/model/adapter/prompt/schema/scoring version），不暴露 prompt、凭据、原始 provider JSON、完整模型回答或隐藏报告事实快照。

## 5. API 与 UI

- `GET/POST /geo/reports/{reportId}/strategies`
- `GET /strategy-jobs/{strategyId}`
- `GET /strategies/{strategyId}`
- `GET/PUT/PATCH/DELETE /strategies/{strategyId}/note`

UI 从报告页进入，展示周期、首次免费、剩余次数、生成/重生成、轮询、失败、不可编辑正文、可编辑备注、历史版本和文章主题导航。

## 6. 明确不包含

不包含文章草稿、文章生成、文章额度消费、图片、渠道、分享、任务分派或 Stage 2 业务模型。
