# 信源指数 V1

## 产品口径

信源指数用于分析当前主体在公开网络中的**可发现信源**。V1 通过百度 Search V2 Standard 获取搜索结果元数据，只处理：

- 标题
- 原文 URL
- 来源网站/域名
- 搜索摘要
- 发布时间（搜索服务提供时）
- 命中的查询主题
- 本次检索位置

V1 **不抓取目标网页全文**，不使用浏览器自动化、代理池、验证码绕过或登录态采集。

页面和接口应使用“本次扫描发现的公开信源”口径，不宣称穷尽整个互联网。

## 自适应扫描

扫描不是固定运行 5 分钟：

1. 从主体正式名称、品牌/别名、产品与关键词构建主体锚定 Query。
2. 单请求最多召回 50 条 Web 结果。
3. 实时 URL 规范化、去重。
4. 结果打满时按发布时间窗口继续下钻。
5. 根据边际新增独立 URL 比例判断是否继续；趋于饱和后立即结束。
6. 搜索预算到达后停止发起新请求，保留时间用于分类、评分与落库。
7. Celery 任务设置最终硬时限，防止异常请求永久占用 worker。

默认参数：

- `SOURCE_INDEX_SEARCH_BUDGET_SECONDS=260`
- `SOURCE_INDEX_TOTAL_TIMEOUT_SECONDS=300`
- `SOURCE_INDEX_MAX_REQUESTS=200`
- `SOURCE_INDEX_SEARCH_CONCURRENCY=3`
- `SOURCE_INDEX_MIN_REQUESTS=12`
- `SOURCE_INDEX_STOP_YIELD_RATIO=0.08`
- `SOURCE_INDEX_LOW_YIELD_BATCHES=3`
- `SOURCE_INDEX_MIN_RELEVANCE_SCORE=60`
- `SOURCE_INDEX_HIGH_WEIGHT_SCORE=75`

百度凭证配置：

- `BAIDU_SEARCH_API_KEY`
- `BAIDU_SEARCH_AUTH_HEADER`，默认 `Authorization`

密钥只能由后端配置读取，不返回浏览器、不写入日志。

## 单信源权重

V1 为确定性评分，不让 LLM 直接打总分：

- 来源权威度：35%
- 主体相关度：30%
- 搜索可见度：20%
- 新鲜度：15%

没有抓取正文，因此产品中使用“信源权重”，不要使用“文章质量评分”。

## 总信源指数

- 曝光规模：25%
- 独立来源多样性：25%
- 来源权威：25%
- 搜索可见度：15%
- 新鲜度：10%

曝光规模和来源多样性采用对数饱和，避免单个平台大量转载直接把指数刷满。

## 状态

- `queued`：已创建任务
- `running`：扫描处理中
- `succeeded`：正常完成
- `partial`：部分 Provider 请求失败，但已有可用结果
- `limit_reached`：达到时间/请求边界后基于当前结果完成，不等同失败
- `failed`：未形成可用结果或发生不可恢复错误

## 前端

工作页面：`/geo/data-center/source-index`

页面展示：

- 信源指数
- 公开信源数
- 独立来源数
- 新闻/媒体信源数
- 高权重信源数
- 近 30 天信源
- 指数构成
- 来源类型分布
- Query 覆盖
- TOP 来源
- 分页信源明细与原文链接
- 扫描实时阶段与已发现数量

正式部署前，必须将该页面接入服务器真实最新 Glass UI / 响应式导航基线；不要用 GitHub 旧导航覆盖服务器较新的 UI。
