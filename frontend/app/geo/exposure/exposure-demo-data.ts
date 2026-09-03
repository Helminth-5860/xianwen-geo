import type {
  ExposureEvent,
  ExposureMapData,
  ExposureMapLevel,
  GeoPosition,
  RegionExposure,
} from "./types";

const GUANGZHOU: GeoPosition = [113.264385, 23.129112];

type RegionSeed = Readonly<{
  code: string;
  name: string;
  coordinates: GeoPosition;
  intensity: number;
}>;

const countryRegions: readonly RegionSeed[] = [
  { code: "110100", name: "北京", coordinates: [116.407526, 39.90403], intensity: 84 },
  { code: "310100", name: "上海", coordinates: [121.473701, 31.230416], intensity: 78 },
  { code: "440100", name: "广州", coordinates: GUANGZHOU, intensity: 100 },
  { code: "440300", name: "深圳", coordinates: [114.057868, 22.543099], intensity: 92 },
  { code: "510100", name: "成都", coordinates: [104.066541, 30.572269], intensity: 64 },
  { code: "420100", name: "武汉", coordinates: [114.305393, 30.593099], intensity: 71 },
];

const provinceRegions: readonly RegionSeed[] = [
  { code: "440100", name: "广州", coordinates: GUANGZHOU, intensity: 100 },
  { code: "440300", name: "深圳", coordinates: [114.057868, 22.543099], intensity: 92 },
  { code: "441900", name: "东莞", coordinates: [113.751765, 23.020536], intensity: 81 },
  { code: "440600", name: "佛山", coordinates: [113.121416, 23.021548], intensity: 77 },
  { code: "440400", name: "珠海", coordinates: [113.576726, 22.270715], intensity: 68 },
  { code: "441300", name: "惠州", coordinates: [114.416196, 23.111847], intensity: 63 },
  { code: "442000", name: "中山", coordinates: [113.392782, 22.517646], intensity: 59 },
  { code: "440700", name: "江门", coordinates: [113.081901, 22.578738], intensity: 54 },
  { code: "440800", name: "湛江", coordinates: [110.364977, 21.274898], intensity: 0 },
  { code: "440900", name: "茂名", coordinates: [110.925456, 21.662999], intensity: 0 },
  { code: "441700", name: "阳江", coordinates: [111.982232, 21.857958], intensity: 0 },
  { code: "441800", name: "清远", coordinates: [113.056031, 23.681763], intensity: 0 },
  { code: "440200", name: "韶关", coordinates: [113.597522, 24.810403], intensity: 0 },
  { code: "441600", name: "河源", coordinates: [114.700447, 23.743538], intensity: 0 },
  { code: "441400", name: "梅州", coordinates: [116.122238, 24.288615], intensity: 0 },
  { code: "440500", name: "汕头", coordinates: [116.681972, 23.354091], intensity: 0 },
  { code: "445100", name: "潮州", coordinates: [116.622603, 23.65695], intensity: 0 },
  { code: "445200", name: "揭阳", coordinates: [116.372831, 23.549993], intensity: 0 },
  { code: "441500", name: "汕尾", coordinates: [115.375278, 22.786211], intensity: 0 },
  { code: "445300", name: "云浮", coordinates: [112.044491, 22.915094], intensity: 0 },
  { code: "441200", name: "肇庆", coordinates: [112.465091, 23.047191], intensity: 0 },
];

const cityRegions: readonly RegionSeed[] = [
  { code: "440106", name: "天河区", coordinates: [113.3612, 23.1247], intensity: 100 },
  { code: "440104", name: "越秀区", coordinates: [113.2668, 23.1285], intensity: 0 },
  { code: "440105", name: "海珠区", coordinates: [113.262, 23.1031], intensity: 0 },
  { code: "440111", name: "白云区", coordinates: [113.2732, 23.1579], intensity: 0 },
  { code: "440103", name: "荔湾区", coordinates: [113.243, 23.1249], intensity: 0 },
  { code: "440113", name: "番禺区", coordinates: [113.3842, 22.9377], intensity: 0 },
  { code: "440112", name: "黄埔区", coordinates: [113.4508, 23.1032], intensity: 0 },
  { code: "440115", name: "南沙区", coordinates: [113.5252, 22.8016], intensity: 0 },
  { code: "440114", name: "花都区", coordinates: [113.2202, 23.4042], intensity: 0 },
  { code: "440118", name: "增城区", coordinates: [113.8296, 23.2905], intensity: 0 },
  { code: "440117", name: "从化区", coordinates: [113.5874, 23.5453], intensity: 0 },
];

function sourceRegion(): RegionExposure {
  return {
    code: "440100",
    name: "广州",
    coordinates: GUANGZHOU,
    exposureIndex: null,
    keywordHits: null,
    estimatedExposure: null,
    recommendationRate: null,
    modelCount: null,
    latestHitAt: null,
    cumulativeIntensity: 100,
  };
}

function buildRegions(seeds: readonly RegionSeed[]): RegionExposure[] {
  return seeds.map((item) => ({
    code: item.code,
    name: item.name,
    coordinates: item.coordinates,
    exposureIndex: null,
    keywordHits: null,
    estimatedExposure: null,
    recommendationRate: null,
    modelCount: null,
    latestHitAt: null,
    cumulativeIntensity: item.intensity,
  }));
}

function eventTime(baseTime: string, minutesBefore: number) {
  return new Date(new Date(baseTime).getTime() - minutesBefore * 60_000).toISOString();
}

function buildEvents(
  level: ExposureMapLevel,
  regions: readonly RegionSeed[],
  baseTime: string,
): ExposureEvent[] {
  const models = ["DeepSeek", "豆包", "通义千问", "Kimi", "文心一言"];
  return regions.map((region, index) => ({
    id: `${level}-${region.code}-${index}`,
    sourceRegionCode: "440100",
    sourceRegionName: "广州",
    sourceCoordinates: GUANGZHOU,
    targetRegionCode: region.code,
    targetRegionName: region.name,
    targetCoordinates: region.coordinates,
    model: models[index % models.length],
    keyword: `${region.name} GEO 优化`,
    question: `${region.name}企业如何提升人工智能搜索曝光？`,
    estimatedExposure: Math.round(1600 + region.intensity * 42),
    score: region.intensity,
    timestamp: eventTime(baseTime, (regions.length - index) * 3),
    origin: "sample",
  }));
}

function createMaps(
  baseTime: string,
  includeSampleEvents: boolean,
  sourceOverride?: RegionExposure,
  realEvents: readonly ExposureEvent[] = [],
): Record<ExposureMapLevel, ExposureMapData> {
  const source = sourceOverride ?? sourceRegion();
  return {
    country: {
      level: "country",
      parentCode: null,
      code: "100000",
      name: "全国",
      boundaryUrl: "/geo-boundaries/china.json",
      sourceCity: source,
      regions: buildRegions(countryRegions),
      events: includeSampleEvents
        ? buildEvents(
            "country",
            countryRegions.filter((item) => item.code !== "440100"),
            baseTime,
          )
        : realEvents,
      hasRegionalFacts: false,
      updatedAt: baseTime,
    },
    province: {
      level: "province",
      parentCode: "100000",
      code: "440000",
      name: "广东省",
      boundaryUrl: "/geo-boundaries/guangdong.json",
      sourceCity: source,
      regions: buildRegions(provinceRegions),
      events: includeSampleEvents
        ? buildEvents(
            "province",
            provinceRegions.filter((item) => item.intensity > 0 && item.code !== "440100"),
            baseTime,
          )
        : realEvents.filter((event) => event.targetRegionCode.startsWith("44")),
      hasRegionalFacts: false,
      updatedAt: baseTime,
    },
    city: {
      level: "city",
      parentCode: "440000",
      code: "440100",
      name: "广州市",
      boundaryUrl: "/geo-boundaries/guangzhou.json",
      sourceCity: source,
      regions: buildRegions(cityRegions),
      events: realEvents.filter((event) => event.targetRegionCode.startsWith("4401")),
      hasRegionalFacts: false,
      updatedAt: baseTime,
    },
  };
}

/** 生产页面使用：没有可核验地域事件时，所有城市保持中性状态。 */
export function createNeutralMaps(
  baseTime: string,
  source?: RegionExposure,
  events: readonly ExposureEvent[] = [],
) {
  return createMaps(baseTime, false, source, events);
}

/** 仅供交互测试和独立演示使用，不会进入真实报告页面。 */
export function createDemonstrationMaps(baseTime: string) {
  return createMaps(baseTime, true);
}
