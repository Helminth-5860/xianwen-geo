import { describe, expect, it } from "vitest";

import type { GeoDetectionJob } from "../lib/geo-detection-client";
import type { GeoReport, ReportModel, ReportTrend } from "../lib/geo-report-client";
import {
  formatChange,
  formatChineseDateTime,
  formatDecimal,
  formatPercent,
  formatScore,
  getChangeView,
  getComparableMetricChanges,
  getComparableScoreChange,
  getLatestCompletedDetectionTime,
  getLatestStrategyInsight,
  getProviderSignals,
  getScoreState,
  getTrendPoints,
  parseFiniteNumber,
  toScore,
} from "../lib/geo-overview";
import type { Strategy, StrategyBody } from "../lib/strategy-assistant-client";

function report(
  id: string,
  values: Readonly<{
    exposure: string;
    mention: string;
    recommendation: string;
    score?: string;
    comparison?: GeoReport["comparison"];
    models?: ReportModel[];
  }>,
): GeoReport {
  return {
    id,
    detection_id: `检测-${id}`,
    subject_id: "主体-1",
    subject_version_id: "主体版本-1",
    retest_mode: "",
    summary: {
      geo: { score: values.score ?? "68.8888", grade: "一般", status: "formal" },
      brand_reputation: { score: "62.0000", grade: "一般", status: "formal" },
      exposure: {
        exposure_index: values.exposure,
        grade: "中",
        status: "formal",
        disclaimer: "这是评估指数。",
        mention_rate_score: values.mention,
        recommendation_rate_score: values.recommendation,
        ranking_performance_score: "50.0000",
        model_coverage_score: "75.0000",
      },
      models: values.models ?? [],
      dimensions: {},
      competitors: [],
    },
    provenance: { scoring_rule_version: "规则-1", questions: [], models: [] },
    comparison: values.comparison ?? null,
    generated_at: "2026-08-27T08:00:00Z",
  };
}

function comparableTo(baselineId: string): NonNullable<GeoReport["comparison"]> {
  return {
    baseline_report_id: baselineId,
    status: "comparable",
    same_subject: true,
    same_questions: true,
    same_models: true,
    same_scoring_rule: true,
    subject_version_changed: false,
    scoring_version_changed: false,
    geo_score_delta: "99.0000",
    brand_reputation_score_delta: "99.0000",
    exposure_index_delta: "99.0000",
    dimension_deltas: { mention: "99.0000", recommendation: "99.0000" },
    model_deltas: [],
  };
}

function detection(
  id: string,
  status: GeoDetectionJob["status"],
  finishedAt: string | null,
): GeoDetectionJob {
  return {
    id,
    subject_id: "主体-1",
    status,
    version: 1,
    planned_question_count: 1,
    planned_model_count: 1,
    planned_detection_points: 1,
    completed_calls: 1,
    successful_calls: status === "succeeded" ? 1 : 0,
    failed_calls: status === "failed" ? 1 : 0,
    cancelled_calls: status === "cancelled" ? 1 : 0,
    progress_percent: 100,
    queue_priority: 0,
    queue_position: null,
    cancel_requested: false,
    quota: {
      quota_type: "geo_detection_runs" as const,
      status: "settled",
      held: 1,
      consumed: 1,
      released: 0,
    },
    queued_at: "2026-08-20T08:00:00Z",
    started_at: "2026-08-20T08:01:00Z",
    finished_at: finishedAt,
    cancelled_at: null,
    created_at: "2026-08-20T08:00:00Z",
    updated_at: finishedAt ?? "2026-08-20T08:00:00Z",
  };
}

function strategy(
  id: string,
  status: Strategy["status"],
  generatedAt: string | null,
  body: StrategyBody | null,
): Strategy {
  return {
    id,
    report_id: "报告-1",
    subject_id: "主体-1",
    subject_version_id: "主体版本-1",
    period: "30d",
    period_days: 30,
    status,
    billing: { mode: "free_initial", first_free: true, held: false, remaining: null },
    body,
    note: null,
    provenance: {
      provider_key: "服务方",
      model_key: "模型",
      provider_model_id: "模型版本",
      adapter_version: "接入版本",
      prompt_version: "内容版本",
      schema_version: "结构版本",
      report_scoring_rule_version: "评分版本",
    },
    safe_error_code: "",
    created_at: "2026-08-20T08:00:00Z",
    generated_at: generatedAt,
    finished_at: generatedAt,
  };
}

describe("总览数值规则", () => {
  it("只解析可靠数字并把评分限制在零至一百", () => {
    expect(parseFiniteNumber(" 53.1667 ")).toBe(53.1667);
    expect(parseFiniteNumber(false)).toBeNull();
    expect(parseFiniteNumber("")).toBeNull();
    expect(parseFiniteNumber("53 分")).toBeNull();
    expect(parseFiniteNumber(Number.POSITIVE_INFINITY)).toBeNull();
    expect(toScore(-4)).toBe(0);
    expect(toScore("108.5")).toBe(100);
    expect(toScore("无法计算")).toBeNull();
  });

  it("最多保留一位小数，百分比和变化值使用面向用户的表达", () => {
    expect(formatDecimal("53.1667")).toBe("53.2");
    expect(formatScore(108)).toBe("100");
    expect(formatPercent("75.0500")).toBe("75.1%");
    expect(formatPercent(null)).toBe("—");
    expect(formatChange(3.14)).toBe("上升 3.1");
    expect(formatChange(-2.06)).toBe("下降 2.1");
    expect(formatChange(0.04)).toBe("无变化");
    expect(formatChange("无效")).toBe("—");
    expect(getChangeView(-2.06)).toEqual({ value: -2.1, direction: "down", text: "下降 2.1" });
  });

  it("按统一阈值给出中文评分状态", () => {
    expect(getScoreState(null)).toEqual({ label: "暂无评分", tone: "empty" });
    expect(getScoreState(39.9).label).toBe("风险");
    expect(getScoreState(40).label).toBe("待提升");
    expect(getScoreState(60).label).toBe("良好");
    expect(getScoreState(80).label).toBe("优秀");
  });
});

describe("总览真实历史数据", () => {
  it("仅按对应的可比基准报告计算三个指标变化", () => {
    const baseline = report("报告-1", {
      exposure: "56.5000",
      mention: "87.5000",
      recommendation: "20.0000",
    });
    const current = report("报告-2", {
      exposure: "59.6400",
      mention: "80.0000",
      recommendation: "20.0400",
      comparison: comparableTo(baseline.id),
    });

    expect(getComparableMetricChanges(current, [current, baseline])).toEqual({
      exposure: 3.1,
      mention: -7.5,
      recommendation: 0,
    });
  });

  it("综合评分变化也只使用口径一致的对应基准报告", () => {
    const baseline = report("报告-1", {
      score: "50.0",
      exposure: "56.5",
      mention: "87.5",
      recommendation: "20.0",
    });
    const current = report("报告-2", {
      score: "68.8888",
      exposure: "59.6",
      mention: "80.0",
      recommendation: "20.0",
      comparison: comparableTo(baseline.id),
    });

    expect(getComparableScoreChange(current, [current, baseline])).toBe(18.9);
    expect(
      getComparableScoreChange(
        { ...current, comparison: { ...comparableTo(baseline.id), same_models: false } },
        [current, baseline],
      ),
    ).toBeNull();
    expect(getComparableScoreChange(current, [])).toBeNull();
  });

  it("不可比较、基准不匹配或字段缺失时不展示变化", () => {
    const baseline = report("报告-1", {
      exposure: "56.5000",
      mention: "87.5000",
      recommendation: "20.0000",
    });
    const current = report("报告-2", {
      exposure: "59.6400",
      mention: "80.0000",
      recommendation: "20.0400",
      comparison: { ...comparableTo(baseline.id), status: "not_comparable" },
    });
    const noChanges = { exposure: null, mention: null, recommendation: null };

    expect(getComparableMetricChanges(current, baseline)).toEqual(noChanges);
    expect(
      getComparableMetricChanges({ ...current, comparison: comparableTo("另一份报告") }, baseline),
    ).toEqual(noChanges);
    expect(getComparableMetricChanges(null, baseline)).toEqual(noChanges);
  });

  it("过滤无效趋势，按时间排序并只保留最近指定数量", () => {
    const trends: ReportTrend[] = [
      {
        report_id: "报告-3",
        generated_at: "2026-08-27T08:00:00+08:00",
        subject_version_id: "版本-1",
        geo_score: "105",
        comparison: null,
      },
      {
        report_id: "报告-1",
        generated_at: "2026-08-20T08:00:00+08:00",
        subject_version_id: "版本-1",
        geo_score: "51.249",
        comparison: null,
      },
      {
        report_id: "无日期",
        generated_at: "无法识别的日期",
        subject_version_id: "版本-1",
        geo_score: "60",
        comparison: null,
      },
      {
        report_id: "无评分",
        generated_at: "2026-08-22T08:00:00+08:00",
        subject_version_id: "版本-1",
        geo_score: null,
        comparison: null,
      },
      {
        report_id: "报告-2",
        generated_at: "2026-08-25T08:00:00+08:00",
        subject_version_id: "版本-1",
        geo_score: "62.5",
        comparison: null,
      },
    ];

    expect(getTrendPoints(trends).map((point) => point.reportId)).toEqual([
      "报告-1",
      "报告-2",
      "报告-3",
    ]);
    expect(getTrendPoints(trends, 2).map(({ dateLabel, score }) => ({ dateLabel, score }))).toEqual(
      [
        { dateLabel: "8月25日", score: 62.5 },
        { dateLabel: "8月27日", score: 100 },
      ],
    );
    expect(getTrendPoints(trends, 0)).toEqual([]);
  });

  it("只使用完整完成或部分完成检测的真实结束时间", () => {
    const jobs = [
      detection("检测-1", "succeeded", "2026-08-20T08:00:00Z"),
      detection("检测-2", "failed", "2026-08-27T08:00:00Z"),
      detection("检测-3", "partial", "2026-08-25T08:00:00Z"),
      detection("检测-4", "succeeded", "无效日期"),
    ];

    expect(getLatestCompletedDetectionTime(jobs)).toBe("2026-08-25T08:00:00Z");
    expect(formatChineseDateTime(getLatestCompletedDetectionTime(jobs))).toBe(
      "2026年8月25日 16:00",
    );
    expect(getLatestCompletedDetectionTime([jobs[1]])).toBeNull();
    expect(formatChineseDateTime(null)).toBe("尚未完成检测");
  });
});

describe("平台信号与洞察", () => {
  it("平台信号只呈现真实模型评分、调用次数和中文状态", () => {
    const models: ReportModel[] = [
      {
        model_id: "模型-1",
        model_key: "deepseek",
        status: "succeeded",
        planned_calls: 3,
        completed_calls: 3,
        successful_calls: 2,
        failed_calls: 1,
        cancelled_calls: 0,
        geo: { score: "81.2500", status: "formal" },
        brand_reputation: null,
      },
      {
        model_id: "模型-2",
        model_key: "qwen",
        status: "succeeded",
        planned_calls: 2,
        completed_calls: 2,
        successful_calls: 2,
        failed_calls: 0,
        cancelled_calls: 0,
        geo: { score: null, status: "reference" },
        brand_reputation: null,
      },
      {
        model_id: "模型-3",
        model_key: "unknown-model-key",
        status: "running",
        planned_calls: 1,
        completed_calls: -2,
        successful_calls: -1,
        failed_calls: 0,
        cancelled_calls: 0,
        geo: null,
        brand_reputation: null,
      },
    ];

    const signals = getProviderSignals(models);
    expect(signals[0]).toEqual({
      modelId: "模型-1",
      name: "深度求索",
      score: 81.25,
      scoreText: "81.3",
      plannedCalls: 3,
      completedCalls: 3,
      successfulCalls: 2,
      failedCalls: 1,
      statusLabel: "结果有效",
      statusTone: "positive",
      callSummary: "获得 2 次有效结果，共完成 3 次检测",
    });
    expect(signals[1]).toMatchObject({
      name: "通义千问",
      score: null,
      scoreText: "暂无评分",
      statusLabel: "结果仅供参考",
    });
    expect(signals[2]).toMatchObject({
      name: "其他检测平台 3",
      completedCalls: 0,
      successfulCalls: 0,
      statusLabel: "检测中",
    });
    expect(signals[0]).not.toHaveProperty("mention");
    expect(signals[0]).not.toHaveProperty("recommendation");
    expect(signals[0]).not.toHaveProperty("ranking");
  });

  it("从最新成功且有内容的策略中读取真实洞察", () => {
    const older = strategy("策略-1", "succeeded", "2026-08-20T08:00:00Z", {
      overview: "旧的总体判断",
      priorities: [],
      schedule: [],
      article_topics: [],
    });
    const latest = strategy("策略-2", "succeeded", "2026-08-26T08:00:00Z", {
      overview: "  当前需要先提升推荐表现。  ",
      priorities: [
        {
          title: " 增强可信内容 ",
          rationale: " 补足第三方权威来源。 ",
          actions: [" 发布行业案例 ", " ", "完善媒体资料"],
          success_metric: "推荐表现稳定提升",
        },
      ],
      schedule: [],
      article_topics: [],
    });
    const newerButRunning = strategy("策略-3", "running", "2026-08-27T08:00:00Z", {
      overview: "尚未生成完成",
      priorities: [],
      schedule: [],
      article_topics: [],
    });

    expect(getLatestStrategyInsight([older, newerButRunning, latest])).toEqual({
      strategyId: "策略-2",
      title: "增强可信内容",
      summary: "补足第三方权威来源。",
      overview: "当前需要先提升推荐表现。",
      actions: ["发布行业案例", "完善媒体资料"],
      successMetric: "推荐表现稳定提升",
      generatedAt: "2026-08-26T08:00:00Z",
    });
  });

  it("成功任务没有真实内容时返回空，不编造建议", () => {
    const empty = strategy("策略-1", "succeeded", "2026-08-27T08:00:00Z", {
      overview: " ",
      priorities: [],
      schedule: [],
      article_topics: [],
    });
    expect(getLatestStrategyInsight([empty])).toBeNull();
    expect(getLatestStrategyInsight([])).toBeNull();
  });

  it("洞察中出现内部错误码或开发术语时不直接展示", () => {
    const unsafe = strategy("策略-1", "succeeded", "2026-08-27T08:00:00Z", {
      overview: "PROVIDER_RUNTIME_ERROR",
      priorities: [
        {
          title: "Provider Binding",
          rationale: "Candidate Batch failed",
          actions: ["ASSET_PIPELINE_ERROR"],
          success_metric: "Runtime ready",
        },
      ],
      schedule: [],
      article_topics: [],
    });

    expect(getLatestStrategyInsight([unsafe])).toBeNull();
  });

  it("洞察中的常见英文缩写会转成普通用户可理解的中文", () => {
    const mixedCopy = strategy("策略-1", "succeeded", "2026-08-27T08:00:00Z", {
      overview: "完善 AI 品牌表现，并补充官网 URL。",
      priorities: [
        {
          title: "改善 AI 推荐表现",
          rationale: "通过现有 API 服务补齐资料。",
          actions: ["核对官网 URL"],
          success_metric: "AI 推荐持续提升",
        },
      ],
      schedule: [],
      article_topics: [],
    });

    expect(getLatestStrategyInsight([mixedCopy])).toMatchObject({
      title: "改善人工智能推荐表现",
      summary: "通过现有相关服务补齐资料。",
      overview: "完善人工智能品牌表现，并补充官网链接。",
      actions: ["核对官网链接"],
      successMetric: "人工智能推荐持续提升",
    });
  });

  it("洞察中的已知平台名转为中文，其他英文内容不进入普通用户页面", () => {
    const knownNames = strategy("策略-1", "succeeded", "2026-08-27T08:00:00Z", {
      overview: "比较 DeepSeek、Kimi 和 Gemini 的 GEO 表现。",
      priorities: [],
      schedule: [],
      article_topics: [],
    });
    const unknownEnglish = strategy("策略-2", "succeeded", "2026-08-28T08:00:00Z", {
      overview: "growth hacking plan",
      priorities: [],
      schedule: [],
      article_topics: [],
    });

    expect(getLatestStrategyInsight([knownNames])).toMatchObject({
      overview: "比较深度求索、月之暗面和谷歌双子座的 GEO 表现。",
    });
    expect(getLatestStrategyInsight([unknownEnglish])).toBeNull();
  });
});
