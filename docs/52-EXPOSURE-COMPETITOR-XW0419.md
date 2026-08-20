# XW-0419 曝光潜力指数与竞品曝光参考

## 1. 曝光潜力指数

固定免责声明：**曝光潜力指数是系统评估指数，不是实际曝光人数。**

该指数只消费 XW-0418 已冻结的 `ScoreResult` 与 `ModelScoreResult`，不重新解析模型原文。所有规则计算使用 `Decimal` 并保留四位小数：

```text
exposure_index =
    mention_rate_score * 0.40
    + recommendation_rate_score * 0.25
    + ranking_performance_score * 0.20
    + model_coverage_score * 0.15
```

- 提及率：自然探索型成功调用中，冻结 `mention_score=100` 的比例。
- 推荐率：已提及的自然探索型成功调用中，冻结推荐分恰为 75 或 100 的比例。
- 排名表现：所有自然探索型成功调用的平均排名曝光分；未提及调用按 0 计入分母。
- 模型覆盖率：本次成功模型中，至少一次自然探索型成功结果提及主体的模型比例。
- 任一分母为零时，对应子项保守返回 0，不制造 evidence。

至少六个正式 GEO `ModelScoreResult` 时状态为 `formal`，否则为 `reference`。失败模型不会被当作零分加入正式模型集合。

等级使用连续下界：90 及以上为“极高”，75 及以上为“高”，60 及以上为“中”，40 及以上为“较低”，其余为“低”。本任务只提供窄范围 deterministic domain result，不提前创建 XW-0421 `GeoReport` 系统。

## 2. Semantic competitor v2

semantic schema 从 `geo-semantic-score-schema-v1` 升级为 `geo-semantic-score-schema-v2`；prompt 和 DeepSeek semantic adapter 同步升级为 v2。原字段 `canonical_name`、`aliases`、`evidence_snippets` 保留，新增：

- `entity_type`：`brand`、`company`、`product`、`industry`、`platform`、`generic_product`、`other`。
- `competitor_eligible`：是否具有冻结的实际竞争关系。
- `exclusion_reason`：`industry_term`、`platform_name`、`generic_product_term`、`not_competitor`、`insufficient_evidence` 或 null。
- `classification_evidence`：解释分类的安全证据片段，不包含 prompt、密钥、provider 原始 JSON 或推理链。

只有 brand/company/product 可以 eligible，且 eligible 时 exclusion 必须为 null。行业词、平台名、通用产品词使用各自固定 exclusion；other 必须被排除。程序不维护品牌、行业、平台或产品词库，也不使用 fuzzy heuristic，只消费冻结的 structured semantic judgment。

历史 v1 evidence 不 backfill、不猜测且不进入 active competitor reference；原始 evidence 保持不变。该 fail-closed 行为不影响曝光指数计算。

## 3. 竞品实体、mention 与复核

竞品聚合限定在单次 detection job。canonical name 使用项目已有 NFKC/casefold normalization helper 作为精确 key，跨问题和模型合并，并稳定合并 aliases；不做 fuzzy entity resolution。

mention 保存问题、模型、出现序号、主体排名、推荐分、分类 evidence 与 semantic provenance。当前 semantic contract 没有可靠竞品名次，因此 `competitor_rank` 和 `rank_gap` 为 null，provenance 明确记录 `rank_status=unavailable`。系统不解析原文猜排名，也不进行额外 AI/provider/detection 调用或扣点，不计算完整竞品 GEO 分。

`competitor_entities`、`competitor_mentions` 是 immutable evidence。用户判断记录在 append-only `competitor_dispositions` 事件中；改变判断会新增事件，当前 active query 读取最新 decision，最新为 `not_competitor` 时过滤实体，历史 evidence 和 disposition 均不删除或覆盖。PostgreSQL 使用现有 `geo_reject_immutable_change()` 的 `BEFORE UPDATE OR DELETE` trigger 保护三张表。

## 4. 延后范围

XW-0420 检测进度、XW-0421 报告页面/导出和 XW-0422 历史趋势均未在本任务实现。
