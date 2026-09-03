import type { GeoReport, ReportModel } from "@/lib/geo-report-client";

import { createNeutralMaps } from "./exposure-demo-data";
import type {
  CompetitorIndexItem,
  ExposureAdapterInput,
  ExposureCockpitData,
  ModelScoreItem,
  TrendingQuestionItem,
} from "./types";

const MODEL_METADATA: Readonly<Record<string, { name: string; logo: string }>> = {
  deepseek: { name: "DeepSeek", logo: "/model-logos/deepseek.png" },
  doubao: { name: "豆包", logo: "/model-logos/doubao.png" },
  qwen: { name: "通义千问", logo: "/model-logos/qwen.png" },
  tongyi: { name: "通义千问", logo: "/model-logos/qwen.png" },
  kimi: { name: "Kimi", logo: "/model-logos/kimi.png" },
  wenxin: { name: "文心一言", logo: "/model-logos/wenxin.png" },
  ernie: { name: "文心一言", logo: "/model-logos/wenxin.png" },
  hunyuan: { name: "腾讯元宝", logo: "/model-logos/hunyuan.png" },
  glm: { name: "智谱", logo: "/model-logos/glm.png" },
  spark: { name: "讯飞星火", logo: "/model-logos/spark.png" },
};

function numberValue(value: string | number | null | undefined) {
  const result = Number(value ?? 0);
  return Number.isFinite(result) ? result : 0;
}

function bounded(value: number) {
  return Math.max(0, Math.min(100, value));
}

function modelIdentity(modelKey: string) {
  const normalized = modelKey.toLowerCase();
  const match = Object.entries(MODEL_METADATA).find(([key]) => normalized.includes(key));
  return match?.[1] ?? { name: modelKey, logo: "" };
}

function modelScore(model: ReportModel) {
  const direct = numberValue(model.geo?.score);
  if (direct > 0) return bounded(direct);
  if (model.planned_calls <= 0) return 0;
  return bounded((model.successful_calls / model.planned_calls) * 100);
}

function findPreviousModel(report: GeoReport | undefined, modelKey: string) {
  return report?.summary.models.find((item) => item.model_key === modelKey);
}

function buildModels(report: GeoReport, previous: GeoReport | undefined): ModelScoreItem[] {
  return report.summary.models
    .map((model) => {
      const identity = modelIdentity(model.model_key);
      const score = modelScore(model);
      const previousModel = findPreviousModel(previous, model.model_key);
      return {
        id: model.model_id,
        key: model.model_key,
        name: identity.name,
        logo: identity.logo || null,
        score,
        trend: previousModel ? score - modelScore(previousModel) : null,
      };
    })
    .sort((left, right) => right.score - left.score);
}

function buildCompetitors(report: GeoReport, subjectName: string): CompetitorIndexItem[] {
  const competitors = [...report.summary.competitors].sort(
    (left, right) => right.mention_count - left.mention_count,
  );
  const peak = Math.max(1, ...competitors.map((item) => item.mention_count));
  return [
    { id: "current-subject", name: subjectName, score: 100, current: true },
    ...competitors.slice(0, 5).map((item) => ({
      id: item.id,
      name: item.canonical_name,
      score: bounded((item.mention_count / peak) * 82),
      current: false,
    })),
  ];
}

function buildQuestions(input: ExposureAdapterInput): TrendingQuestionItem[] {
  const generatedAt = new Date(input.report.generated_at).getTime();
  const items =
    input.questions?.results.flatMap((question) =>
      question.results.map((result, index) => ({
        id: result.call_id,
        question: question.text,
        model: modelIdentity(result.model_key).name,
        timestamp: new Date(generatedAt - index * 60_000).toISOString(),
      })),
    ) ?? [];
  if (items.length) return items.slice(0, 8);
  return input.report.provenance.questions.slice(0, 8).map((question, index) => ({
    id: question.source_question_id,
    question: question.text,
    model: "已检测模型",
    timestamp: new Date(generatedAt - index * 60_000).toISOString(),
  }));
}

function buildTrend(reports: readonly GeoReport[]) {
  return [...reports]
    .slice(0, 7)
    .reverse()
    .map((item) => numberValue(item.summary.exposure.exposure_index));
}

export function adaptExposureData(input: ExposureAdapterInput): ExposureCockpitData {
  const reportIndex = input.reports.findIndex((item) => item.id === input.report.id);
  const previous = reportIndex >= 0 ? input.reports[reportIndex + 1] : undefined;
  const successfulCalls = input.report.summary.models.reduce(
    (total, item) => total + item.successful_calls,
    0,
  );
  const plannedCalls = input.report.summary.models.reduce(
    (total, item) => total + item.planned_calls,
    0,
  );
  const previousIndex = previous ? numberValue(previous.summary.exposure.exposure_index) : null;
  const currentIndex = numberValue(input.report.summary.exposure.exposure_index);
  const questions = buildQuestions(input);

  return {
    report: input.report,
    modelScores: buildModels(input.report, previous),
    competitors: buildCompetitors(input.report, input.subjectName),
    summary: {
      keywordHits: successfulCalls,
      hitRate: plannedCalls > 0 ? bounded((successfulCalls / plannedCalls) * 100) : 0,
      estimatedExposure: Math.round(currentIndex * Math.max(successfulCalls, 1) * 100),
      changeRate:
        previousIndex === null || previousIndex === 0
          ? null
          : ((currentIndex - previousIndex) / previousIndex) * 100,
      trend: buildTrend(input.reports),
    },
    questions,
    maps: createNeutralMaps(input.report.generated_at),
  };
}
