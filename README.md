# 显问 GEO 智能体系统 V1 完整开发需求包

版本：V1.0  
状态：产品功能冻结，可进入分阶段开发  
目标实施工具：Codex  
产品语言：简体中文  

## 1. 使用说明

本需求包是显问 GEO 智能体系统 V1 的开发源文件。开发、测试、验收应以本目录中的文档为准，不应直接依据聊天记录或口头描述实现。

优先阅读顺序：

1. `docs/00-DECISION-REGISTER.md`
2. `docs/01-PRD.md`
3. `docs/02-USER-FLOWS.md`
4. `docs/03-ADMIN-FUNCTIONS.md`
5. `docs/04-GEO-SCORING-RULES.md`
6. `docs/05-QUOTA-BILLING-RULES.md`
7. `docs/06-DATABASE-SCHEMA.md`
8. `docs/07-API-SPECIFICATION.md`
9. `docs/08-AI-MODEL-ADAPTERS.md`
10. `docs/09-SECURITY-PERMISSIONS.md`
11. `docs/10-DEPLOYMENT.md`
12. `docs/11-ACCEPTANCE-TESTS.md`
13. `docs/12-CODEX-TASKS.md`
14. `docs/13-IMPLEMENTATION-INPUTS.md`
15. `codex/CODEX-START-HERE.md`

## 2. 目录结构

```text
xianwen_geo_v1_dev_package/
├── README.md
├── docs/
│   ├── 00-DECISION-REGISTER.md
│   ├── 01-PRD.md
│   ├── 02-USER-FLOWS.md
│   ├── 03-ADMIN-FUNCTIONS.md
│   ├── 04-GEO-SCORING-RULES.md
│   ├── 05-QUOTA-BILLING-RULES.md
│   ├── 06-DATABASE-SCHEMA.md
│   ├── 07-API-SPECIFICATION.md
│   ├── 08-AI-MODEL-ADAPTERS.md
│   ├── 09-SECURITY-PERMISSIONS.md
│   ├── 10-DEPLOYMENT.md
│   ├── 11-ACCEPTANCE-TESTS.md
│   ├── 12-CODEX-TASKS.md
│   └── 13-IMPLEMENTATION-INPUTS.md
├── openapi/
│   └── openapi-v1.yaml
├── sql/
│   └── schema-outline.sql
├── config/
│   ├── env.example
│   └── plan-limit-keys.json
└── codex/
    ├── CODEX-START-HERE.md
    └── TASK-PROMPT-TEMPLATE.md
```

## 3. V1 核心目标

建立一个通过网站使用的商业化 GEO 智能体系统，形成以下闭环：

```text
注册与审核
→ 创建主体
→ 完善主体资料
→ 生成关键词
→ 关键词蒸馏
→ 生成并确认问题库
→ 8 模型 GEO 检测
→ GEO 评分报告
→ GEO 改善策略
→ 文章与图片内容建设
→ 渠道适配与发布检测
→ 持续复测
```

## 4. 已冻结的关键产品决策

- 第一版不做视频生成。
- 第一版不做在线支付，不记录线下收款或成交金额。
- 第一版不做网页端自动化检测，只调用官方 API。
- 第一版固定接入 8 个检测模型：DeepSeek、豆包、通义千问、腾讯混元、百度文心、Kimi、智谱 GLM、讯飞星火。
- 每个模型独立评分；综合分按成功的正式模型等权平均。
- 至少 6 个正式模型得分，才产生正式综合分。
- 单个模型的问题调用成功率达到 80%，才产生正式模型得分。
- 所有用户端和后台界面均使用简体中文。
- 单账号使用，不支持团队成员、子账号或多人协作。
- 套餐、额度、模型权限和限制均由后台动态配置。
- 同一账号同一时间仅允许一个生效套餐。
- 关键词支持可选的短关键词、长尾关键词、地区关键词；三者不是互斥分类，也不是必选项。
- 文章只保留当前稿；优化时临时对比原稿和优化稿，用户二选一后只保留选中稿。
- 报告分享默认展示完整报告，并允许下载 PDF。
- 显问 AI 助手固定使用 DeepSeek，不保存聊天记录，不直接执行扣费操作。

## 5. 明确不在 V1 范围内

- 视频生成
- 自动登录第三方平台并自动发布文章
- 在线支付、退款、发票、财务结算
- 多语言系统
- 企业成员协作、代理商子账号
- 完整 CRM、合同、回款和销售业绩管理
- AI 产品网页端自动化、验证码处理和真实官网截图
- 逐条生成证据卡片或大量证据图片
- 文章多版本历史与恢复
- 用户自定义模型 API 接口
- 复杂低代码表单条件联动
- WebSocket 实时流式进度；V1 使用轮询

## 6. 分阶段交付

### 阶段一：GEO 核心闭环

账号、审核、套餐、主体、关键词、蒸馏、问题库、8 模型检测、评分、报告、复测、改善策略、AI 助手。

### 阶段二：内容建设闭环

文章、大纲、质量检测、优化对比、图片、渠道适配、发布链接即时检测、报告导出与分享。

### 阶段三：商用后台与上线

完整权限、客户记录、API 管理、审核、公告、反馈、统计、审计、安全、备份、告警、COS、短信、部署和压力测试。

## 7. 当前外部依赖状态

| 依赖 | 状态 |
|---|---|
| 应用服务器 | 已具备：4 vCPU / 8 GiB / 5 Mbps |
| PostgreSQL | 已具备：PostgreSQL 16.14，高可用，2 vCPU / 4 GiB / 100 GB |
| Redis | 已具备：Redis 7.0，1 GB，1 主 1 副 |
| 8 个检测模型 API | 已取得凭证；仍需逐一完成接口可用性验收 |
| DeepSeek 内容生成能力 | 尚未完成开通或验收 |
| 豆包图片生成能力 | 尚未完成开通或验收 |
| 腾讯云 COS | 尚未开通 |
| 短信服务 | 尚未开通 |

## 8. 文档优先级与冲突规则

发生冲突时按以下顺序执行：

1. `docs/04-GEO-SCORING-RULES.md`
2. `docs/05-QUOTA-BILLING-RULES.md`
3. `docs/09-SECURITY-PERMISSIONS.md`
4. `docs/01-PRD.md`
5. 其他文档

如实现过程中发现文档之间仍有矛盾，不允许 Codex 自行猜测。应创建变更记录，并由产品负责人确认后更新本需求包。

## 9. 开发纪律

- 每个功能必须先完成数据模型、权限、额度规则、异常回滚和自动化测试设计，再写页面。
- 禁止直接修改额度余额；所有额度变化必须通过不可删除的流水。
- 禁止同步阻塞式执行多模型检测、文章生成、图片生成和报告导出。
- 禁止将 API 密钥放入前端、代码仓库、日志或错误响应。
- 禁止使用一个超大 Codex 任务一次性生成整个系统。
- 数据库迁移必须可回滚，生产环境禁止手工改表。

## 10. 本地开发（XW-0001）
状态：XW-0001 and XW-0002 integration verified.


要求：

- Docker Desktop（含 Docker Compose）
- PowerShell 7，或兼容 POSIX shell

一条命令启动：PowerShell 运行 `.\scripts\dev.ps1`，Linux/macOS 运行 `./scripts/dev.sh`。

首次运行会从 `.env.example` 创建仅供本地开发的 `.env`，随后构建并启动
PostgreSQL、Redis、Django API、Celery Worker 和 Next.js 前端。

启动后访问：

- 前端：<http://localhost:3000>
- 前端健康检查：<http://localhost:3000/api/health>
- 后端健康检查：<http://localhost:8000/api/v1/health/>

停止服务：`docker compose down`。

质量检查：运行 `.\scripts\check.ps1`，或分别使用 `backend/` 与 `frontend/`
README 中列出的命令。
## 11. 配置、日志和错误框架（XW-0002）

状态：XW-0001 and XW-0002 integration verified.

XW-0002 提供后续业务模块统一复用的工程边界：

- local、test、production 分环境 Django 配置
- 规范 UUID `request_id` 请求上下文
- `/api/v1` JSON 成功与错误 Envelope
- DRF 全局异常映射和简体中文错误消息
- local 可读日志、test 降噪、production 单行 JSON 日志
- 递归敏感字段脱敏

local 允许 SQLite/LocMem 安全回退，test 使用隔离配置。production 必须显式提供
密钥、PostgreSQL、Redis、主机和来源配置，并拒绝 DEBUG、SQLite、LocMem、
通配符主机及弱密钥。前端公开环境变量由 `frontend/lib/env.ts` 集中校验。
