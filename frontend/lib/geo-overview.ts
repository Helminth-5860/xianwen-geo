import type { GeoDetectionJob } from "./geo-detection-client";
import type { GeoReport, ReportModel, ReportTrend } from "./geo-report-client";
import type { Strategy } from "./strategy-assistant-client";

const ONE_DECIMAL_FORMATTER = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 0,
});

const PROVIDER_NAMES: Readonly<Record<string, string>> = Object.freeze({
  deepseek: "深度求索",
  doubao: "豆包",
  qwen: "通义千问",
  tongyi_qianwen: "通义千问",
  hunyuan: "腾讯混元",
  wenxin: "百度文心",
  ernie: "百度文心",
  kimi: "月之暗面",
  glm: "智谱",
  spark: "讯飞星火",
});

const INTERNAL_COPY_PATTERN =
  /\b(?:[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+|Provider|Runtime|Binding|Batch|Candidate|Distilled|Asset|HTTP|JSON|SDK|SQL)\b/i;

export type ScoreStateTone = "excellent" | "good" | "improve" | "risk" | "empty";

export type ScoreState = Readonly<{
  label: "优秀" | "良好" | "待提升" | "风险" | "暂无评分";
  tone: ScoreStateTone;
}>;

export type ChangeDirection = "up" | "down" | "flat";

export type ChangeViewModel = Readonly<{
  value: number;
  direction: ChangeDirection;
  text: string;
}>;

export type OverviewMetricChanges = Readonly<{
  exposure: number | null;
  mention: number | null;
  recommendation: number | null;
}>;

export type GeoTrendPoint = Readonly<{
  reportId: string;
  generatedAt: string;
  timestamp: number;
  dateLabel: string;
  score: number;
}>;

export type ProviderSignalTone = "positive" | "attention" | "danger" | "active" | "neutral";

export type ProviderSignalViewModel = Readonly<{
  modelId: string;
  name: string;
  score: number | null;
  scoreText: string;
  plannedCalls: number;
  completedCalls: number;
  successfulCalls: number;
  failedCalls: number;
  statusLabel: string;
  statusTone: ProviderSignalTone;
  callSummary: string;
}>;

export type StrategyInsightViewModel = Readonly<{
  strategyId: string;
  title: string;
  summary: string;
  overview: string;
  actions: readonly string[];
  successMetric: string;
  generatedAt: string | null;
}>;

/** 只接受有限数字或完整的数字字符串，避免把空值、布尔值和混杂文本当成数据。 */
export function parseFiniteNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || value.trim() === "") return null;

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** 将评分限制在零至一百之间；无效输入保持为空。 */
export function toScore(value: unknown): number | null {
  const parsed = parseFiniteNumber(value);
  if (parsed === null) return null;
  return Math.min(100, Math.max(0, parsed));
}

export function formatDecimal(value: unknown, emptyText = "—"): string {
  const parsed = parseFiniteNumber(value);
  return parsed === null ? emptyText : ONE_DECIMAL_FORMATTER.format(parsed);
}

export function formatScore(value: unknown, emptyText = "—"): string {
  const score = toScore(value);
  return score === null ? emptyText : ONE_DECIMAL_FORMATTER.format(score);
}

export function formatPercent(value: unknown, emptyText = "—"): string {
  const score = toScore(value);
  return score === null ? emptyText : `${ONE_DECIMAL_FORMATTER.format(score)}%`;
}

export function getChangeView(value: unknown): ChangeViewModel | null {
  const parsed = parseFiniteNumber(value);
  if (parsed === null) return null;

  const rounded = Math.round(parsed * 10) / 10;
  if (rounded > 0) {
    return {
      value: rounded,
      direction: "up",
      text: `上升 ${ONE_DECIMAL_FORMATTER.format(rounded)}`,
    };
  }
  if (rounded < 0) {
    return {
      value: rounded,
      direction: "down",
      text: `下降 ${ONE_DECIMAL_FORMATTER.format(Math.abs(rounded))}`,
    };
  }
  return { value: 0, direction: "flat", text: "无变化" };
}

export function formatChange(value: unknown, emptyText = "—"): string {
  return getChangeView(value)?.text ?? emptyText;
}

export function getScoreState(value: unknown): ScoreState {
  const score = toScore(value);
  if (score === null) return { label: "暂无评分", tone: "empty" };
  if (score >= 80) return { label: "优秀", tone: "excellent" };
  if (score >= 60) return { label: "良好", tone: "good" };
  if (score >= 40) return { label: "待提升", tone: "improve" };
  return { label: "风险", tone: "risk" };
}

function findComparableBaseline(
  current: GeoReport | null | undefined,
  reportsOrBaseline: readonly GeoReport[] | GeoReport | null | undefined,
): GeoReport | null {
  const comparison = current?.comparison;
  if (!current || !comparison || comparison.status !== "comparable") return null;
  if (
    !comparison.same_subject ||
    !comparison.same_questions ||
    !comparison.same_models ||
    !comparison.same_scoring_rule
  ) {
    return null;
  }

  const baseline = Array.isArray(reportsOrBaseline)
    ? reportsOrBaseline.find((report) => report.id === comparison.baseline_report_id)
    : reportsOrBaseline;

  return baseline?.id === comparison.baseline_report_id ? baseline : null;
}

function scoreDifference(current: unknown, baseline: unknown): number | null {
  const currentScore = toScore(current);
  const baselineScore = toScore(baseline);
  if (currentScore === null || baselineScore === null) return null;
  return Math.round((currentScore - baselineScore) * 10) / 10;
}

/** 仅在后端确认比较口径完全一致且找到对应基准报告时，计算综合评分变化。 */
export function getComparableScoreChange(
  current: GeoReport | null | undefined,
  reportsOrBaseline: readonly GeoReport[] | GeoReport | null | undefined,
): number | null {
  const baseline = findComparableBaseline(current, reportsOrBaseline);
  if (!current || !baseline) return null;
  return scoreDifference(current.summary.geo.score, baseline.summary.geo.score);
}

/** 仅在后端确认可比较且找到对应基准报告时，计算三个真实指标的变化。 */
export function getComparableMetricChanges(
  current: GeoReport | null | undefined,
  reportsOrBaseline: readonly GeoReport[] | GeoReport | null | undefined,
): OverviewMetricChanges {
  const baseline = findComparableBaseline(current, reportsOrBaseline);
  if (!current || !baseline) {
    return { exposure: null, mention: null, recommendation: null };
  }

  return {
    exposure: scoreDifference(
      current.summary.exposure.exposure_index,
      baseline.summary.exposure.exposure_index,
    ),
    mention: scoreDifference(
      current.summary.exposure.mention_rate_score,
      baseline.summary.exposure.mention_rate_score,
    ),
    recommendation: scoreDifference(
      current.summary.exposure.recommendation_rate_score,
      baseline.summary.exposure.recommendation_rate_score,
    ),
  };
}

function validTimestamp(value: unknown): number | null {
  if (typeof value !== "string" || value.trim() === "") return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function dateParts(timestamp: number) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  })
    .formatToParts(timestamp)
    .reduce<Record<string, string>>((parts, part) => {
      if (part.type !== "literal") parts[part.type] = part.value;
      return parts;
    }, {});
}

export function formatChineseDateTime(value: unknown, emptyText = "尚未完成检测"): string {
  const timestamp = validTimestamp(value);
  if (timestamp === null) return emptyText;
  const parts = dateParts(timestamp);
  return `${parts.year}年${parts.month}月${parts.day}日 ${parts.hour}:${parts.minute}`;
}

/** 过滤无日期或无评分记录，按时间升序返回；可选数量只保留最近的数据。 */
export function getTrendPoints(trends: readonly ReportTrend[], limit?: number): GeoTrendPoint[] {
  const points = trends
    .flatMap<GeoTrendPoint>((trend) => {
      const timestamp = validTimestamp(trend.generated_at);
      const score = toScore(trend.geo_score);
      if (timestamp === null || score === null) return [];
      const parts = dateParts(timestamp);
      return [
        {
          reportId: trend.report_id,
          generatedAt: trend.generated_at,
          timestamp,
          dateLabel: `${parts.month}月${parts.day}日`,
          score,
        },
      ];
    })
    .sort((left, right) => left.timestamp - right.timestamp);

  if (limit === undefined) return points;
  const safeLimit = Math.max(0, Math.floor(limit));
  return safeLimit === 0 ? [] : points.slice(-safeLimit);
}

/** “已完成”包含完整完成和部分完成，不把失败或取消当成一次完成检测。 */
export function getLatestCompletedDetectionTime(jobs: readonly GeoDetectionJob[]): string | null {
  let latest: { value: string; timestamp: number } | null = null;

  for (const job of jobs) {
    if (job.status !== "succeeded" && job.status !== "partial") continue;
    const timestamp = validTimestamp(job.finished_at);
    if (timestamp === null || (latest && latest.timestamp >= timestamp)) continue;
    latest = { value: job.finished_at as string, timestamp };
  }

  return latest?.value ?? null;
}

function nonNegativeCount(value: unknown): number {
  const parsed = parseFiniteNumber(value);
  return parsed === null ? 0 : Math.max(0, Math.floor(parsed));
}

function providerName(modelKey: string, index: number): string {
  return PROVIDER_NAMES[modelKey.trim().toLowerCase()] ?? `其他检测平台 ${index + 1}`;
}

function providerStatus(model: ReportModel): {
  label: string;
  tone: ProviderSignalTone;
} {
  if (model.status === "running") return { label: "检测中", tone: "active" };
  if (model.status === "queued") return { label: "等待检测", tone: "neutral" };
  if (model.status === "partial") return { label: "部分完成", tone: "attention" };
  if (model.status === "failed") return { label: "未完成", tone: "danger" };
  if (model.status === "cancelled") return { label: "已取消", tone: "neutral" };

  if (model.status === "succeeded") {
    if (model.geo?.status === "formal") return { label: "结果有效", tone: "positive" };
    if (model.geo?.status === "reference") {
      return { label: "结果仅供参考", tone: "attention" };
    }
    if (model.geo?.status === "failed") return { label: "未完成", tone: "danger" };
    return { label: "暂无评分", tone: "neutral" };
  }

  return { label: "结果待更新", tone: "neutral" };
}

function reportModels(
  reportOrModels: GeoReport | readonly ReportModel[] | null | undefined,
): readonly ReportModel[] {
  if (!reportOrModels) return [];
  return Array.isArray(reportOrModels)
    ? reportOrModels
    : (reportOrModels as GeoReport).summary.models;
}

/** 平台信号只暴露报告实际拥有的模型评分、调用次数和状态。 */
export function getProviderSignals(
  reportOrModels: GeoReport | readonly ReportModel[] | null | undefined,
): ProviderSignalViewModel[] {
  return reportModels(reportOrModels).map((model, index) => {
    const plannedCalls = nonNegativeCount(model.planned_calls);
    const completedCalls = nonNegativeCount(model.completed_calls);
    const successfulCalls = nonNegativeCount(model.successful_calls);
    const failedCalls = nonNegativeCount(model.failed_calls);
    const score = toScore(model.geo?.score);
    const status = providerStatus(model);
    const callSummary =
      plannedCalls === 0
        ? "暂无检测记录"
        : `获得 ${successfulCalls} 次有效结果，共完成 ${completedCalls} 次检测`;

    return {
      modelId: model.model_id,
      name: providerName(model.model_key, index),
      score,
      scoreText: score === null ? "暂无评分" : formatScore(score),
      plannedCalls,
      completedCalls,
      successfulCalls,
      failedCalls,
      statusLabel: status.label,
      statusTone: status.tone,
      callSummary,
    };
  });
}

function strategyTimestamp(strategy: Strategy): number {
  return (
    validTimestamp(strategy.generated_at) ??
    validTimestamp(strategy.finished_at) ??
    validTimestamp(strategy.created_at) ??
    Number.NEGATIVE_INFINITY
  );
}

function trimmed(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function displayableInsightText(value: unknown): string {
  const text = trimmed(value)
    .replace(/\s*\bDeepSeek\b\s*/gi, "深度求索")
    .replace(/\s*\bKimi\b\s*/gi, "月之暗面")
    .replace(/\s*\bQwen\b\s*/gi, "通义千问")
    .replace(/\s*\bGLM\b\s*/gi, "智谱")
    .replace(/\s*\bDoubao\b\s*/gi, "豆包")
    .replace(/\s*\bHunyuan\b\s*/gi, "腾讯混元")
    .replace(/\s*\b(?:Wenxin|ERNIE)\b\s*/gi, "百度文心")
    .replace(/\s*\bSpark\b\s*/gi, "讯飞星火")
    .replace(/\s*\bGemini\b\s*/gi, "谷歌双子座")
    .replace(/\s*\bClaude\b\s*/gi, "克劳德")
    .replace(/\s*\b(?:ChatGPT|OpenAI)\b\s*/gi, "开放人工智能平台")
    .replace(/\s*\bAIGC\b\s*/gi, "智能内容生成")
    .replace(/\s*\bLLM\b\s*/gi, "大语言模型")
    .replace(/\s*\bSEO\b\s*/gi, "搜索优化")
    .replace(/\s*\bAI\b\s*/gi, "人工智能")
    .replace(/\s*\bAPI\b(?:\s*(?:服务|接口))?\s*/gi, "相关服务")
    .replace(/\s*\bURL\b(?:\s*链接)?\s*/gi, "链接");
  const textWithoutProductTerm = text.replace(/\bGEO\b/gi, "");
  return INTERNAL_COPY_PATTERN.test(text) || /[A-Za-z]/.test(textWithoutProductTerm) ? "" : text;
}

/** 返回最新一份已成功生成且含真实内容的策略摘要，不在前端补写洞察。 */
export function getLatestStrategyInsight(
  strategies: readonly Strategy[],
): StrategyInsightViewModel | null {
  const candidates = strategies
    .filter((strategy) => strategy.status === "succeeded" && strategy.body !== null)
    .map((strategy, index) => ({ strategy, index, timestamp: strategyTimestamp(strategy) }))
    .sort((left, right) => right.timestamp - left.timestamp || left.index - right.index);

  for (const { strategy } of candidates) {
    const body = strategy.body;
    if (!body) continue;
    const overview = displayableInsightText(body.overview);
    const priority = body.priorities.find(
      (item) =>
        displayableInsightText(item.title) ||
        displayableInsightText(item.rationale) ||
        item.actions.some(displayableInsightText),
    );
    if (!overview && !priority) continue;

    const title = displayableInsightText(priority?.title) || "最新优化洞察";
    const summary = displayableInsightText(priority?.rationale) || overview;
    const actions = (priority?.actions ?? []).map(displayableInsightText).filter(Boolean);
    return {
      strategyId: strategy.id,
      title,
      summary,
      overview,
      actions,
      successMetric: displayableInsightText(priority?.success_metric),
      generatedAt: strategy.generated_at ?? strategy.finished_at,
    };
  }

  return null;
}
