import type { GeoReport, ReportQuestionPage } from "@/lib/geo-report-client";

export type ExposureMapLevel = "country" | "province" | "city";

export type ExposureRegionStatus = "neutral" | "historical" | "active";

export type GeoPosition = readonly [longitude: number, latitude: number];

export type RegionExposure = Readonly<{
  code: string;
  name: string;
  coordinates: GeoPosition;
  exposureIndex: number | null;
  keywordHits: number | null;
  estimatedExposure: number | null;
  recommendationRate: number | null;
  modelCount: number | null;
  latestHitAt: string | null;
  cumulativeIntensity: number;
}>;

export type ExposureEvent = Readonly<{
  id: string;
  sourceRegionCode: string;
  sourceRegionName: string;
  sourceCoordinates: GeoPosition;
  targetRegionCode: string;
  targetRegionName: string;
  targetCoordinates: GeoPosition;
  model: string;
  keyword: string;
  question: string;
  estimatedExposure: number;
  score: number;
  timestamp: string;
  origin: "real" | "sample";
}>;

export type ExposureMapData = Readonly<{
  level: ExposureMapLevel;
  parentCode: string | null;
  code: string;
  name: string;
  boundaryUrl: string;
  sourceCity: RegionExposure;
  regions: readonly RegionExposure[];
  events: readonly ExposureEvent[];
  hasRegionalFacts: boolean;
  updatedAt: string;
}>;

export type ModelScoreItem = Readonly<{
  id: string;
  key: string;
  name: string;
  logo: string | null;
  score: number;
  trend: number | null;
}>;

export type CompetitorIndexItem = Readonly<{
  id: string;
  name: string;
  score: number;
  current: boolean;
}>;

export type TrendingQuestionItem = Readonly<{
  id: string;
  question: string;
  model: string;
  timestamp: string;
}>;

export type ExposureSummary = Readonly<{
  keywordHits: number;
  hitRate: number;
  estimatedExposure: number;
  changeRate: number | null;
  trend: readonly number[];
}>;

export type ExposureCockpitData = Readonly<{
  report: GeoReport;
  modelScores: readonly ModelScoreItem[];
  competitors: readonly CompetitorIndexItem[];
  summary: ExposureSummary;
  questions: readonly TrendingQuestionItem[];
  maps: Readonly<Record<ExposureMapLevel, ExposureMapData>>;
}>;

export type ExposureAdapterInput = Readonly<{
  report: GeoReport;
  reports: readonly GeoReport[];
  questions: ReportQuestionPage | null;
  subjectName: string;
}>;

export type GeoJsonGeometry = Readonly<{
  type: "Polygon" | "MultiPolygon";
  coordinates: number[][][] | number[][][][];
}>;

export type GeoJsonFeature = Readonly<{
  type: "Feature";
  properties: Readonly<{
    adcode?: number;
    name?: string;
    center?: number[];
    centroid?: number[];
    level?: string;
  }>;
  geometry: GeoJsonGeometry;
}>;

export type GeoJsonCollection = Readonly<{
  type: "FeatureCollection";
  features: readonly GeoJsonFeature[];
}>;
