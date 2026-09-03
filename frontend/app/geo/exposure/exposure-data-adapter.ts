import type { GeoReport, ReportModel } from "@/lib/geo-report-client";

import { createNeutralMaps } from "./exposure-demo-data";
import type {
  CompetitorIndexItem,
  ExposureEvent,
  ExposureAdapterInput,
  ExposureCockpitData,
  GeoPosition,
  ModelScoreItem,
  RegionExposure,
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

const REGION_CENTERS: readonly Readonly<{
  code: string;
  name: string;
  aliases: readonly string[];
  coordinates: GeoPosition;
}>[] = [
  { code: "110100", name: "北京", aliases: ["北京"], coordinates: [116.4075, 39.904] },
  { code: "120100", name: "天津", aliases: ["天津"], coordinates: [117.2009, 39.0842] },
  { code: "310100", name: "上海", aliases: ["上海"], coordinates: [121.4737, 31.2304] },
  { code: "500100", name: "重庆", aliases: ["重庆"], coordinates: [106.5516, 29.563] },
  { code: "440100", name: "广州", aliases: ["广州", "广州市"], coordinates: [113.2644, 23.1291] },
  { code: "440300", name: "深圳", aliases: ["深圳", "深圳市"], coordinates: [114.0579, 22.5431] },
  { code: "510100", name: "成都", aliases: ["成都", "成都市"], coordinates: [104.0665, 30.5723] },
  { code: "420100", name: "武汉", aliases: ["武汉", "武汉市"], coordinates: [114.3054, 30.5931] },
  { code: "330100", name: "杭州", aliases: ["杭州", "杭州市"], coordinates: [120.1551, 30.2741] },
  { code: "320100", name: "南京", aliases: ["南京", "南京市"], coordinates: [118.7969, 32.0603] },
  { code: "610100", name: "西安", aliases: ["西安", "西安市"], coordinates: [108.9398, 34.3416] },
  { code: "410100", name: "郑州", aliases: ["郑州", "郑州市"], coordinates: [113.6254, 34.7466] },
  { code: "370100", name: "济南", aliases: ["济南", "济南市"], coordinates: [117.1201, 36.6512] },
  { code: "430100", name: "长沙", aliases: ["长沙", "长沙市"], coordinates: [112.9388, 28.2282] },
  { code: "350100", name: "福州", aliases: ["福州", "福州市"], coordinates: [119.2965, 26.0745] },
  { code: "530100", name: "昆明", aliases: ["昆明", "昆明市"], coordinates: [102.8329, 24.8801] },
  { code: "450100", name: "南宁", aliases: ["南宁", "南宁市"], coordinates: [108.3669, 22.817] },
  { code: "130100", name: "石家庄", aliases: ["石家庄"], coordinates: [114.5149, 38.0428] },
  { code: "210100", name: "沈阳", aliases: ["沈阳", "沈阳市"], coordinates: [123.4315, 41.8057] },
  { code: "220100", name: "长春", aliases: ["长春", "长春市"], coordinates: [125.3235, 43.8171] },
  { code: "230100", name: "哈尔滨", aliases: ["哈尔滨"], coordinates: [126.5349, 45.8038] },
];

function sourceRegion(regionText = ""): RegionExposure {
  const match = REGION_CENTERS.find((item) =>
    item.aliases.some((alias) => regionText.includes(alias)),
  );
  const source = match ?? {
    code: "100000",
    name: "主体所在地",
    coordinates: [104.1954, 35.8617] as GeoPosition,
  };
  return {
    code: source.code,
    name: source.name,
    coordinates: source.coordinates,
    exposureIndex: null,
    keywordHits: null,
    estimatedExposure: null,
    recommendationRate: null,
    modelCount: null,
    latestHitAt: null,
    cumulativeIntensity: 100,
  };
}

function questionTarget(question: string, fallback: RegionExposure): RegionExposure {
  const match = REGION_CENTERS.find((item) =>
    item.aliases.some((alias) => question.includes(alias)),
  );
  if (!match) return fallback;
  return {
    ...fallback,
    code: match.code,
    name: match.name,
    coordinates: match.coordinates,
  };
}

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

function buildRealEvents(input: ExposureAdapterInput, source: RegionExposure): ExposureEvent[] {
  const generatedAt = Date.parse(input.report.generated_at);
  const successfulResults =
    input.questions?.results.flatMap((question) =>
      question.results
        .filter((result) => result.answer_available && result.status.toLowerCase() !== "failed")
        .map((result) => ({ question: question.text, result })),
    ) ?? [];

  return successfulResults.slice(0, 20).map(({ question, result }, index) => {
    const target = questionTarget(question, source);
    return {
      id: `report-${result.call_id}`,
      sourceRegionCode: source.code,
      sourceRegionName: source.name,
      sourceCoordinates: source.coordinates,
      targetRegionCode: target.code,
      targetRegionName: target.name,
      targetCoordinates: target.coordinates,
      model: modelIdentity(result.model_key).name,
      keyword: question,
      question,
      estimatedExposure: 0,
      score: numberValue(result.score?.overall_score ?? result.score?.score),
      timestamp: new Date(generatedAt - (successfulResults.length - index) * 15_000).toISOString(),
      origin: "real" as const,
    };
  });
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
  const source = sourceRegion(input.subjectRegionText);
  const events = buildRealEvents(input, source);

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
    maps: createNeutralMaps(input.report.generated_at, source, events),
  };
}
