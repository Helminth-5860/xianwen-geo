"use client";

import {
  AimOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  BarChartOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  DeploymentUnitOutlined,
  FundOutlined,
  GlobalOutlined,
  RadarChartOutlined,
  RobotOutlined,
  ThunderboltOutlined,
  TrophyOutlined,
  UsergroupAddOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from "@ant-design/icons";
import { Alert, Button, Empty, Select, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getReportHistory,
  getReportQuestions,
  type GeoReport,
  type ReportModel,
  type ReportQuestionPage,
} from "@/lib/geo-report-client";

import styles from "./exposure-command-center.module.css";

const { Text, Title } = Typography;

type ExposureState = Readonly<{
  subjectId: string;
  reports: GeoReport[];
  selectedReportId: string;
  error: string;
}>;

type AnimatedNumberProps = Readonly<{
  value: number;
  decimals?: number;
  suffix?: string;
  duration?: number;
}>;

type ModelNode = Readonly<{
  model: ReportModel;
  x: number;
  y: number;
  score: number;
  metricLabel: string;
}>;

type ActivityItem = Readonly<{
  callId: string;
  modelKey: string;
  question: string;
  status: string;
  answerAvailable: boolean;
  snippet: string;
}>;

function toNumber(value: string | number | null | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, value));
}

function normalizeRankingScore(value: number) {
  return clampScore(value <= 10 ? value * 10 : value);
}

function reportOptionLabel(report: GeoReport) {
  const time = new Date(report.generated_at).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${time} · 曝光 ${toNumber(report.summary.exposure.exposure_index).toFixed(1)}`;
}

function modelDisplayName(modelKey: string) {
  const normalized = modelKey.toLowerCase();
  if (normalized.includes("deepseek")) return "DeepSeek";
  if (normalized.includes("doubao")) return "豆包";
  if (normalized.includes("kimi")) return "Kimi";
  if (normalized.includes("qwen") || normalized.includes("tongyi")) return "通义千问";
  if (
    normalized.includes("wenxin") ||
    normalized.includes("ernie") ||
    normalized.includes("baidu")
  ) {
    return "文心一言";
  }
  if (normalized.includes("hunyuan") || normalized.includes("yuanbao")) return "腾讯元宝";
  if (normalized.includes("glm") || normalized.includes("zhipu")) return "智谱";
  if (normalized.includes("spark")) return "讯飞星火";
  return modelKey;
}

function modelMetric(model: ReportModel) {
  const geoScore = toNumber(model.geo?.score);
  if (geoScore > 0) return { score: clampScore(geoScore), label: "GEO" };
  if (model.planned_calls <= 0) return { score: 0, label: "成功率" };
  return {
    score: clampScore((model.successful_calls / model.planned_calls) * 100),
    label: "成功率",
  };
}

function activityStatus(status: string, answerAvailable: boolean) {
  const normalized = status.toLowerCase();
  if (answerAvailable || ["succeeded", "success", "completed"].includes(normalized)) {
    return { label: "已返回", tone: "success" as const };
  }
  if (["failed", "error", "cancelled", "canceled"].includes(normalized)) {
    return { label: "异常", tone: "danger" as const };
  }
  return { label: "处理中", tone: "pending" as const };
}

function AnimatedNumber({ value, decimals = 1, suffix = "", duration = 980 }: AnimatedNumberProps) {
  const [display, setDisplay] = useState(0);
  const valueRef = useRef(0);

  useEffect(() => {
    const from = valueRef.current;
    const to = value;
    const startedAt = performance.now();
    let frame = 0;

    const tick = (now: number) => {
      const elapsed = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - elapsed, 3);
      const next = from + (to - from) * eased;
      setDisplay(next);
      if (elapsed < 1) frame = requestAnimationFrame(tick);
      else valueRef.current = to;
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [duration, value]);

  return (
    <span className={styles.animatedNumber}>
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}

function MiniMetric({
  icon,
  label,
  value,
  suffix,
  decimals = 1,
}: Readonly<{
  icon: ReactNode;
  label: string;
  value: number;
  suffix?: string;
  decimals?: number;
}>) {
  return (
    <div className={styles.metricCard}>
      <div className={styles.metricIcon}>{icon}</div>
      <div>
        <span className={styles.metricLabel}>{label}</span>
        <div className={styles.metricValue}>
          <AnimatedNumber value={value} suffix={suffix} decimals={decimals} />
        </div>
      </div>
    </div>
  );
}

function buildTrendPoints(reports: GeoReport[], getter: (report: GeoReport) => number) {
  if (!reports.length) return "";
  const count = Math.max(1, reports.length - 1);
  return reports
    .map((item, index) => {
      const x = 8 + (index / count) * 84;
      const y = 88 - clampScore(getter(item)) * 0.72;
      return `${x},${y}`;
    })
    .join(" ");
}

function radarPoint(value: number, index: number, total: number) {
  const angle = -Math.PI / 2 + (index * Math.PI * 2) / total;
  const radius = 34 * (clampScore(value) / 100);
  return `${50 + Math.cos(angle) * radius},${50 + Math.sin(angle) * radius}`;
}

export default function GeoExposurePage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [exposureState, setExposureState] = useState<ExposureState>();
  const [questionPage, setQuestionPage] = useState<ReportQuestionPage | null>(null);
  const [focusedModel, setFocusedModel] = useState("");
  const [sceneScale, setSceneScale] = useState(1);
  const subjectId = subject?.id ?? "";

  useEffect(() => {
    if (subjectLoading || !subjectId) return;
    let current = true;

    void getReportHistory(subjectId)
      .then((result) => {
        if (!current) return;
        const reports = [...result.items].sort(
          (left, right) =>
            new Date(right.generated_at).getTime() - new Date(left.generated_at).getTime(),
        );
        setExposureState({ subjectId, reports, selectedReportId: reports[0]?.id ?? "", error: "" });
      })
      .catch((reason) => {
        if (current) {
          setExposureState({
            subjectId,
            reports: [],
            selectedReportId: "",
            error: userMessage(reason),
          });
        }
      });

    return () => {
      current = false;
    };
  }, [subjectId, subjectLoading]);

  const state = exposureState?.subjectId === subjectId ? exposureState : undefined;
  const report = state?.reports.find((item) => item.id === state.selectedReportId);

  useEffect(() => {
    if (!report) {
      setQuestionPage(null);
      return;
    }
    let current = true;
    setQuestionPage(null);
    void getReportQuestions(report.id, 1)
      .then((result) => {
        if (current) setQuestionPage(result);
      })
      .catch(() => {
        if (current) setQuestionPage(null);
      });
    return () => {
      current = false;
    };
  }, [report]);

  useEffect(() => {
    if (!report) return;
    setFocusedModel((current) =>
      current && report.summary.models.some((model) => model.model_key === current) ? current : "",
    );
  }, [report]);

  const selectedIndex =
    state && report ? state.reports.findIndex((item) => item.id === report.id) : -1;
  const previousReport = selectedIndex >= 0 ? state?.reports[selectedIndex + 1] : undefined;
  const exposureValue = toNumber(report?.summary.exposure.exposure_index);
  const previousExposure = toNumber(previousReport?.summary.exposure.exposure_index);
  const exposureDelta = previousReport ? exposureValue - previousExposure : null;
  const mentionRate = toNumber(report?.summary.exposure.mention_rate_score);
  const recommendationRate = toNumber(report?.summary.exposure.recommendation_rate_score);
  const rankingPerformance = toNumber(report?.summary.exposure.ranking_performance_score);
  const modelCoverage = toNumber(report?.summary.exposure.model_coverage_score);

  const modelNodes = useMemo<ModelNode[]>(() => {
    const models = report?.summary.models.slice(0, 8) ?? [];
    if (!models.length) return [];
    return models.map((model, index) => {
      const angle = -Math.PI / 2 + (index * Math.PI * 2) / models.length;
      const metric = modelMetric(model);
      const radiusX = index % 2 === 0 ? 38 : 34;
      const radiusY = index % 2 === 0 ? 30 : 34;
      return {
        model,
        x: 50 + Math.cos(angle) * radiusX,
        y: 53 + Math.sin(angle) * radiusY,
        score: metric.score,
        metricLabel: metric.label,
      };
    });
  }, [report]);

  const rankedModels = useMemo(
    () =>
      [...(report?.summary.models ?? [])]
        .map((model) => ({ model, ...modelMetric(model) }))
        .sort((left, right) => right.score - left.score)
        .slice(0, 6),
    [report],
  );

  const competitors = useMemo(
    () =>
      [...(report?.summary.competitors ?? [])]
        .sort((left, right) => right.mention_count - left.mention_count)
        .slice(0, 5),
    [report],
  );

  const trendReports = useMemo(
    () => [...(state?.reports ?? [])].slice(0, 7).reverse(),
    [state?.reports],
  );
  const exposureTrendPoints = useMemo(
    () => buildTrendPoints(trendReports, (item) => toNumber(item.summary.exposure.exposure_index)),
    [trendReports],
  );
  const coverageTrendPoints = useMemo(
    () =>
      buildTrendPoints(trendReports, (item) =>
        toNumber(item.summary.exposure.model_coverage_score),
      ),
    [trendReports],
  );

  const activityItems = useMemo<ActivityItem[]>(() => {
    const items =
      questionPage?.results.flatMap((question) =>
        question.results.map((result) => ({
          callId: result.call_id,
          modelKey: result.model_key,
          question: question.text,
          status: result.status,
          answerAvailable: result.answer_available,
          snippet: result.snippet,
        })),
      ) ?? [];
    return items.filter((item) => !focusedModel || item.modelKey === focusedModel).slice(0, 8);
  }, [focusedModel, questionPage]);

  const totalSuccessfulCalls = useMemo(
    () => (report?.summary.models ?? []).reduce((sum, model) => sum + model.successful_calls, 0),
    [report],
  );
  const totalPlannedCalls = useMemo(
    () => (report?.summary.models ?? []).reduce((sum, model) => sum + model.planned_calls, 0),
    [report],
  );

  const distributionGradient = useMemo(() => {
    const palette = ["#407cff", "#6b63ff", "#8b6cff", "#4fbacb", "#77a7ff"];
    const top = rankedModels.slice(0, 5);
    const total = Math.max(
      1,
      top.reduce((sum, item) => sum + Math.max(item.score, 1), 0),
    );
    let start = 0;
    const segments = top.map((item, index) => {
      const width = (Math.max(item.score, 1) / total) * 100;
      const end = start + width;
      const segment = `${palette[index % palette.length]} ${start}% ${end}%`;
      start = end;
      return segment;
    });
    return `conic-gradient(${segments.join(", ") || "#e7eef8 0% 100%"})`;
  }, [rankedModels]);

  const radarValues = [
    clampScore(mentionRate),
    clampScore(recommendationRate),
    normalizeRankingScore(rankingPerformance),
    clampScore(modelCoverage),
  ];
  const radarPolygon = radarValues
    .map((value, index) => radarPoint(value, index, radarValues.length))
    .join(" ");
  const donutColorClasses = [
    styles.donutColor1,
    styles.donutColor2,
    styles.donutColor3,
    styles.donutColor4,
  ];

  if (subjectLoading || (subject && !state)) {
    return <Spin fullscreen description="正在加载曝光数字孪生态势" />;
  }

  return (
    <main className={styles.page}>
      <div className={styles.ambientGlow} aria-hidden="true" />

      <header className={styles.commandHeader}>
        <div className={styles.headerStatus}>
          <span className={styles.liveDot} />
          <div>
            <strong>报告态势已同步</strong>
            <small>
              数据更新：
              {report
                ? new Date(report.generated_at).toLocaleString("zh-CN", {
                    year: "numeric",
                    month: "2-digit",
                    day: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : "--"}
            </small>
          </div>
        </div>

        <div className={styles.headerTitleBlock}>
          <span className={styles.headerWingLeft} aria-hidden="true" />
          <span className={styles.headerWingRight} aria-hidden="true" />
          <div className={styles.eyebrow}>
            <RadarChartOutlined /> 显问智能曝光数字孪生
          </div>
          <Title level={2} className={styles.pageTitle}>
            显问AI GEO 曝光数字孪生态势中心
          </Title>
          <Text className={styles.pageDescription}>AI 模型可见度监测 / 推荐辐射分析</Text>
        </div>

        <div className={styles.heroActions}>
          <Button href="/geo/reports">数据报告</Button>
          <Button type="primary" href="/geo/reports/history">
            历史对比
          </Button>
        </div>
      </header>

      {!subject ? (
        <section className={styles.emptyPanel}>
          <Empty description="请先创建并选择当前主体">
            <Button type="primary" href="/subjects">
              进入主体档案
            </Button>
          </Empty>
        </section>
      ) : (
        <>
          {state?.error && (
            <Alert type="error" showIcon message={state.error} className={styles.alert} />
          )}

          {!state?.error && !report ? (
            <section className={styles.emptyPanel}>
              <Empty description="当前主体还没有可展示的曝光指数">
                <Button type="primary" href="/geo/detections">
                  开始首次检测
                </Button>
              </Empty>
            </section>
          ) : report ? (
            <>
              <section className={styles.cockpitGrid}>
                <aside className={styles.leftRail}>
                  <div className={`${styles.panel} ${styles.platformPanel}`}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>模型监测平台</span>
                        <h3>监测平台</h3>
                      </div>
                      <RobotOutlined />
                    </div>
                    <div className={styles.platformGrid}>
                      {report.summary.models.slice(0, 8).map((model) => {
                        const metric = modelMetric(model);
                        const active = !focusedModel || focusedModel === model.model_key;
                        return (
                          <button
                            type="button"
                            key={model.model_id}
                            className={`${styles.platformChip} ${active ? styles.platformChipActive : ""}`}
                            onClick={() =>
                              setFocusedModel((current) =>
                                current === model.model_key ? "" : model.model_key,
                              )
                            }
                          >
                            <span className={styles.platformIcon}>
                              <RobotOutlined />
                            </span>
                            <span>
                              <strong>{modelDisplayName(model.model_key)}</strong>
                              <small>{metric.score.toFixed(0)}</small>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className={`${styles.panel} ${styles.reportPanel}`}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>检测报告时段</span>
                        <h3>报告时段</h3>
                      </div>
                      <ClockCircleOutlined />
                    </div>
                    <div className={styles.reportBody}>
                      <Select
                        aria-label="曝光指数报告"
                        value={report.id}
                        options={state?.reports.map((item) => ({
                          label: reportOptionLabel(item),
                          value: item.id,
                        }))}
                        onChange={(selectedReportId) =>
                          setExposureState((current) =>
                            current && current.subjectId === subjectId
                              ? { ...current, selectedReportId }
                              : current,
                          )
                        }
                      />
                      <div className={styles.reportDate}>
                        <div>
                          <span>当前主体</span>
                          <strong>{subject.official_name || subject.subject_type.name}</strong>
                        </div>
                        <Tag className={styles.formalTag}>
                          {report.summary.exposure.status === "formal" ? "正式结果" : "参考结果"}
                        </Tag>
                      </div>
                    </div>
                  </div>

                  <div className={`${styles.panel} ${styles.metricsPanel}`}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>本次核心指标</span>
                        <h3>核心指标</h3>
                      </div>
                      <AimOutlined />
                    </div>
                    <div className={styles.exposureScoreCard}>
                      <div>
                        <span>综合曝光指数</span>
                        <strong>
                          <AnimatedNumber value={exposureValue} decimals={1} />
                        </strong>
                      </div>
                      <Tag className={styles.gradeTag}>{report.summary.exposure.grade}</Tag>
                      {exposureDelta !== null && (
                        <div
                          className={`${styles.delta} ${exposureDelta >= 0 ? styles.deltaUp : styles.deltaDown}`}
                        >
                          {exposureDelta >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}较上次{" "}
                          {Math.abs(exposureDelta).toFixed(1)}
                        </div>
                      )}
                    </div>
                    <div className={styles.metricGrid}>
                      <MiniMetric
                        icon={<GlobalOutlined />}
                        label="提及率"
                        value={mentionRate}
                        suffix="%"
                      />
                      <MiniMetric
                        icon={<TrophyOutlined />}
                        label="推荐率"
                        value={recommendationRate}
                        suffix="%"
                      />
                      <MiniMetric
                        icon={<BarChartOutlined />}
                        label="排名表现"
                        value={rankingPerformance}
                      />
                      <MiniMetric
                        icon={<DeploymentUnitOutlined />}
                        label="模型覆盖"
                        value={modelCoverage}
                        suffix="%"
                      />
                    </div>
                  </div>

                  <div className={`${styles.panel} ${styles.trendPanel}`}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>近期曝光趋势</span>
                        <h3>曝光趋势</h3>
                      </div>
                      <FundOutlined />
                    </div>
                    <div className={styles.trendLegend}>
                      <span>
                        <i className={styles.legendExposure} /> 曝光指数
                      </span>
                      <span>
                        <i className={styles.legendCoverage} /> 模型覆盖
                      </span>
                    </div>
                    {trendReports.length > 1 ? (
                      <>
                        <svg
                          className={styles.trendChart}
                          viewBox="0 0 100 100"
                          preserveAspectRatio="none"
                        >
                          <line x1="8" x2="92" y1="88" y2="88" className={styles.chartAxis} />
                          <line x1="8" x2="92" y1="52" y2="52" className={styles.chartGridLine} />
                          <line x1="8" x2="92" y1="16" y2="16" className={styles.chartGridLine} />
                          <polyline points={exposureTrendPoints} className={styles.trendLineGlow} />
                          <polyline points={exposureTrendPoints} className={styles.trendLine} />
                          <polyline
                            points={coverageTrendPoints}
                            className={styles.coverageTrendLine}
                          />
                          {trendReports.map((item, index) => {
                            const count = Math.max(1, trendReports.length - 1);
                            const x = 8 + (index / count) * 84;
                            const y =
                              88 -
                              clampScore(toNumber(item.summary.exposure.exposure_index)) * 0.72;
                            return (
                              <circle
                                key={item.id}
                                cx={x}
                                cy={y}
                                r="1.7"
                                className={styles.trendPoint}
                              />
                            );
                          })}
                        </svg>
                        <div className={styles.trendLabels}>
                          {trendReports.map((item) => (
                            <span key={item.id}>
                              {new Date(item.generated_at).toLocaleDateString("zh-CN", {
                                month: "2-digit",
                                day: "2-digit",
                              })}
                            </span>
                          ))}
                        </div>
                      </>
                    ) : (
                      <div className={styles.miniEmpty}>积累至少 2 份报告后显示趋势</div>
                    )}
                  </div>
                </aside>

                <section className={styles.centerStage}>
                  <div className={`${styles.panel} ${styles.digitalTwinPanel}`}>
                    <div className={styles.twinHeader}>
                      <div>
                        <span className={styles.panelEyebrow}>智能曝光数字孪生</span>
                        <h3>AI 曝光数字孪生场</h3>
                        <p>主体为核心映射，AI 模型节点、检测链路与曝光强度均来自当前报告。</p>
                      </div>
                      <div className={styles.modelFocus}>
                        <span>聚焦模型</span>
                        <Select
                          value={focusedModel || "all"}
                          onChange={(value) => setFocusedModel(value === "all" ? "" : value)}
                          options={[
                            { value: "all", label: "全部模型" },
                            ...report.summary.models.map((model) => ({
                              value: model.model_key,
                              label: modelDisplayName(model.model_key),
                            })),
                          ]}
                        />
                      </div>
                    </div>

                    <div className={styles.twinStage}>
                      <div className={styles.twinLegend}>
                        <strong>图例说明</strong>
                        <span>
                          <i className={styles.legendCore} /> 主体曝光核心
                        </span>
                        <span>
                          <i className={styles.legendNode} /> AI 模型节点
                        </span>
                        <span>
                          <i className={styles.legendSignal} /> 检测信号链
                        </span>
                      </div>

                      <div className={styles.stageControls}>
                        <button
                          type="button"
                          aria-label="放大数字孪生场景"
                          onClick={() => setSceneScale((current) => Math.min(1.12, current + 0.04))}
                        >
                          <ZoomInOutlined />
                        </button>
                        <button
                          type="button"
                          aria-label="缩小数字孪生场景"
                          onClick={() => setSceneScale((current) => Math.max(0.9, current - 0.04))}
                        >
                          <ZoomOutOutlined />
                        </button>
                        <button
                          type="button"
                          aria-label="重置数字孪生场景"
                          onClick={() => setSceneScale(1)}
                        >
                          <AimOutlined />
                        </button>
                      </div>

                      <div className={styles.sceneViewport}>
                        <div
                          className={styles.sceneScale}
                          style={{ transform: `scale(${sceneScale})` }}
                        >
                          <div className={styles.floorGlow} aria-hidden="true" />
                          <div className={styles.floorPlane} aria-hidden="true" />
                          <div className={styles.signalSweep} aria-hidden="true" />
                          <div
                            className={`${styles.orbit} ${styles.orbitOuter}`}
                            aria-hidden="true"
                          />
                          <div
                            className={`${styles.orbit} ${styles.orbitMiddle}`}
                            aria-hidden="true"
                          />
                          <div
                            className={`${styles.orbit} ${styles.orbitInner}`}
                            aria-hidden="true"
                          />

                          <div className={styles.metricTowers} aria-hidden="true">
                            {[
                              mentionRate,
                              recommendationRate,
                              normalizeRankingScore(rankingPerformance),
                              modelCoverage,
                            ].map((value, index) => (
                              <span
                                key={index}
                                style={{ height: `${24 + clampScore(value) * 0.62}px` }}
                              />
                            ))}
                          </div>

                          <svg
                            className={styles.connectionLayer}
                            viewBox="0 0 100 100"
                            preserveAspectRatio="none"
                            aria-hidden="true"
                          >
                            <defs>
                              <linearGradient id="signalGradient" x1="0" y1="0" x2="1" y2="1">
                                <stop offset="0%" stopColor="#4e85ff" stopOpacity="0.12" />
                                <stop offset="45%" stopColor="#665dff" stopOpacity="0.78" />
                                <stop offset="100%" stopColor="#a367ff" stopOpacity="0.12" />
                              </linearGradient>
                            </defs>
                            {modelNodes.map((node, index) => {
                              const active = !focusedModel || focusedModel === node.model.model_key;
                              const controlX =
                                50 + (node.x - 50) * 0.45 + (index % 2 === 0 ? 5 : -5);
                              const controlY = 50 + (node.y - 50) * 0.25 - 8;
                              return (
                                <path
                                  key={node.model.model_id}
                                  d={`M 50 54 Q ${controlX} ${controlY} ${node.x} ${node.y}`}
                                  className={
                                    active ? styles.connectionActive : styles.connectionMuted
                                  }
                                />
                              );
                            })}
                          </svg>

                          <div className={styles.subjectPlatform} aria-hidden="true">
                            <span className={styles.platformRingOne} />
                            <span className={styles.platformRingTwo} />
                            <span className={styles.platformRingThree} />
                          </div>
                          <div className={styles.subjectCore}>
                            <div className={styles.corePulse} aria-hidden="true" />
                            <div className={styles.corePulseSecondary} aria-hidden="true" />
                            <span className={styles.coreLabel}>综合曝光指数</span>
                            <strong>
                              <AnimatedNumber value={exposureValue} decimals={1} />
                            </strong>
                            <small>{subject.official_name || subject.subject_type.name}</small>
                            <Tag className={styles.coreGrade}>{report.summary.exposure.grade}</Tag>
                          </div>

                          {modelNodes.map((node, index) => {
                            const active = !focusedModel || focusedModel === node.model.model_key;
                            const levelClass =
                              node.score >= 70
                                ? styles.nodeHigh
                                : node.score >= 45
                                  ? styles.nodeMid
                                  : styles.nodeLow;
                            const beaconSize = 34 + Math.round(clampScore(node.score) * 0.1);
                            return (
                              <button
                                type="button"
                                key={node.model.model_id}
                                className={`${styles.twinNode} ${levelClass} ${active ? styles.twinNodeActive : styles.twinNodeMuted}`}
                                style={{ left: `${node.x}%`, top: `${node.y}%` }}
                                onClick={() =>
                                  setFocusedModel((current) =>
                                    current === node.model.model_key ? "" : node.model.model_key,
                                  )
                                }
                              >
                                <span className={styles.nodeLabel}>
                                  <strong>{modelDisplayName(node.model.model_key)}</strong>
                                  <small>
                                    {node.metricLabel} {node.score.toFixed(1)}
                                  </small>
                                </span>
                                <span
                                  className={styles.nodeBeacon}
                                  style={{ width: beaconSize, height: beaconSize }}
                                >
                                  <span className={styles.nodePulse} />
                                  <RobotOutlined />
                                </span>
                                <span className={styles.nodeBase} aria-hidden="true" />
                                <span className={styles.nodeIndex}>
                                  {String(index + 1).padStart(2, "0")}
                                </span>
                              </button>
                            );
                          })}
                          {!modelNodes.length && (
                            <div className={styles.mapEmpty}>本报告没有模型明细</div>
                          )}
                        </div>
                      </div>

                      <div className={styles.stageFooter}>
                        <span>
                          <i /> 当前模型 {report.summary.models.length}
                        </span>
                        <span>
                          <i /> 检测问题 {report.provenance.questions.length}
                        </span>
                        <span>
                          <i /> 成功调用 {totalSuccessfulCalls}/{totalPlannedCalls}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.centerBottomGrid}>
                    <div className={`${styles.panel} ${styles.miniDataPanel}`}>
                      <div className={styles.compactHeading}>
                        <div>
                          <span className={styles.panelEyebrow}>模型曝光分布</span>
                          <h3>模型曝光分布</h3>
                        </div>
                        <DeploymentUnitOutlined />
                      </div>
                      <div className={styles.donutBody}>
                        <div
                          className={styles.donutChart}
                          style={{ background: distributionGradient }}
                        >
                          <div>
                            <strong>{report.summary.models.length}</strong>
                            <span>模型</span>
                          </div>
                        </div>
                        <div className={styles.donutLegend}>
                          {rankedModels.slice(0, 4).map(({ model, score }, index) => (
                            <div key={model.model_id}>
                              <i className={donutColorClasses[index]} />
                              <span>{modelDisplayName(model.model_key)}</span>
                              <strong>{score.toFixed(0)}</strong>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className={`${styles.panel} ${styles.miniDataPanel}`}>
                      <div className={styles.compactHeading}>
                        <div>
                          <span className={styles.panelEyebrow}>曝光能力雷达</span>
                          <h3>曝光四维雷达</h3>
                        </div>
                        <RadarChartOutlined />
                      </div>
                      <div className={styles.radarBody}>
                        <svg className={styles.radarChart} viewBox="0 0 100 100">
                          <polygon points="50,14 86,50 50,86 14,50" className={styles.radarGrid} />
                          <polygon points="50,26 74,50 50,74 26,50" className={styles.radarGrid} />
                          <line x1="50" y1="14" x2="50" y2="86" className={styles.radarAxis} />
                          <line x1="14" y1="50" x2="86" y2="50" className={styles.radarAxis} />
                          <polygon points={radarPolygon} className={styles.radarValue} />
                          {radarValues.map((value, index) => {
                            const [x, y] = radarPoint(value, index, radarValues.length).split(",");
                            return (
                              <circle
                                key={index}
                                cx={x}
                                cy={y}
                                r="2"
                                className={styles.radarPoint}
                              />
                            );
                          })}
                        </svg>
                        <div className={styles.radarLabels}>
                          <span>提及</span>
                          <span>推荐</span>
                          <span>排名</span>
                          <span>覆盖</span>
                        </div>
                      </div>
                    </div>

                    <div className={`${styles.panel} ${styles.miniDataPanel}`}>
                      <div className={styles.compactHeading}>
                        <div>
                          <span className={styles.panelEyebrow}>检测覆盖情况</span>
                          <h3>检测覆盖</h3>
                        </div>
                        <ThunderboltOutlined />
                      </div>
                      <div className={styles.coverageSummary}>
                        <div className={styles.coverageRing}>
                          <strong>
                            <AnimatedNumber value={modelCoverage} decimals={0} suffix="%" />
                          </strong>
                          <span>模型覆盖</span>
                        </div>
                        <div className={styles.coverageStats}>
                          <div>
                            <span>检测模型</span>
                            <strong>{report.summary.models.length}</strong>
                          </div>
                          <div>
                            <span>检测问题</span>
                            <strong>{report.provenance.questions.length}</strong>
                          </div>
                          <div>
                            <span>成功调用</span>
                            <strong>{totalSuccessfulCalls}</strong>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </section>

                <aside className={styles.rightRail}>
                  <div className={`${styles.panel} ${styles.activityPanel}`}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>智能检测实时动态</span>
                        <h3>AI 检测实时态势</h3>
                      </div>
                      <ThunderboltOutlined />
                    </div>
                    <div className={styles.activityTableHeader}>
                      <span>序号</span>
                      <span>检测问题</span>
                      <span>模型</span>
                      <span>状态</span>
                    </div>
                    <div className={styles.activityList}>
                      {activityItems.length ? (
                        activityItems.map((item, index) => {
                          const status = activityStatus(item.status, item.answerAvailable);
                          return (
                            <div className={styles.activityRow} key={item.callId}>
                              <span className={styles.activityIndex}>{index + 1}</span>
                              <div className={styles.activityQuestion}>
                                <strong>{item.question}</strong>
                                {item.snippet && <small>{item.snippet}</small>}
                              </div>
                              <span className={styles.activityModel}>
                                {modelDisplayName(item.modelKey)}
                              </span>
                              <span
                                className={`${styles.activityBadge} ${status.tone === "success" ? styles.activitySuccess : status.tone === "danger" ? styles.activityDanger : styles.activityPending}`}
                              >
                                {status.label}
                              </span>
                            </div>
                          );
                        })
                      ) : (
                        <div className={styles.miniEmpty}>当前报告暂无可展示的检测调用明细</div>
                      )}
                    </div>
                  </div>

                  <div className={`${styles.panel} ${styles.rankingPanel}`}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>模型曝光排行</span>
                        <h3>模型曝光排行</h3>
                      </div>
                      <TrophyOutlined />
                    </div>
                    <div className={styles.rankingList}>
                      {rankedModels.length ? (
                        rankedModels.map(({ model, score, label }, index) => (
                          <button
                            key={model.model_id}
                            type="button"
                            className={`${styles.rankingRow} ${focusedModel === model.model_key ? styles.rankingRowActive : ""}`}
                            onClick={() => setFocusedModel(model.model_key)}
                          >
                            <span className={styles.rankMedal}>{index + 1}</span>
                            <span className={styles.rankName}>
                              {modelDisplayName(model.model_key)}
                            </span>
                            <span className={styles.rankBar}>
                              <span style={{ width: `${clampScore(score)}%` }} />
                            </span>
                            <strong>{score.toFixed(1)}</strong>
                            <small>{label}</small>
                          </button>
                        ))
                      ) : (
                        <div className={styles.miniEmpty}>暂无模型明细</div>
                      )}
                    </div>
                  </div>

                  <div className={`${styles.panel} ${styles.competitorPanel}`}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>竞品信号前五名</span>
                        <h3>竞品提及热度</h3>
                      </div>
                      <UsergroupAddOutlined />
                    </div>
                    <div className={styles.competitorList}>
                      {competitors.length ? (
                        competitors.map((competitor, index) => {
                          const maxMentions = Math.max(1, competitors[0]?.mention_count ?? 1);
                          return (
                            <div className={styles.competitorRow} key={competitor.id}>
                              <span>{index + 1}</span>
                              <div>
                                <strong>{competitor.canonical_name}</strong>
                                <span className={styles.competitorBar}>
                                  <span
                                    style={{
                                      width: `${Math.max(8, (competitor.mention_count / maxMentions) * 100)}%`,
                                    }}
                                  />
                                </span>
                              </div>
                              <b>{competitor.mention_count}</b>
                            </div>
                          );
                        })
                      ) : (
                        <div className={styles.miniEmpty}>本次报告未记录竞品提及</div>
                      )}
                    </div>
                  </div>

                  <div className={`${styles.panel} ${styles.summaryPanel}`}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>本次检测总结</span>
                        <h3>本次总结</h3>
                      </div>
                      <CheckCircleFilled />
                    </div>
                    <div className={styles.summaryBody}>
                      <div className={styles.summaryRadar}>
                        <span className={styles.summaryOrbitOne} />
                        <span className={styles.summaryOrbitTwo} />
                        <span className={styles.summaryCrossX} />
                        <span className={styles.summaryCrossY} />
                        <strong>{exposureValue.toFixed(1)}</strong>
                      </div>
                      <div className={styles.summaryStats}>
                        <div>
                          <span>模型节点</span>
                          <strong>{report.summary.models.length}</strong>
                          <small>个</small>
                        </div>
                        <div>
                          <span>检测问题</span>
                          <strong>{report.provenance.questions.length}</strong>
                          <small>条</small>
                        </div>
                        <div>
                          <span>推荐率</span>
                          <strong>{recommendationRate.toFixed(1)}</strong>
                          <small>%</small>
                        </div>
                      </div>
                    </div>
                  </div>
                </aside>
              </section>

              <section className={`${styles.panel} ${styles.timelinePanel}`}>
                <div className={styles.timelineHeader}>
                  <div>
                    <span className={styles.panelEyebrow}>报告动态时间轴</span>
                    <h3>曝光报告动态时间轴</h3>
                  </div>
                  <span>最近 {Math.min(state?.reports.length ?? 0, 7)} 份报告 · 点击节点切换</span>
                </div>
                <div className={styles.timelineTrack}>
                  {(state?.reports ?? [])
                    .slice(0, 7)
                    .reverse()
                    .map((item) => {
                      const selected = item.id === report.id;
                      const delta =
                        item.comparison?.status === "comparable"
                          ? toNumber(item.comparison.exposure_index_delta)
                          : null;
                      return (
                        <button
                          type="button"
                          key={item.id}
                          className={`${styles.timelineItem} ${selected ? styles.timelineItemActive : ""}`}
                          onClick={() =>
                            setExposureState((current) =>
                              current && current.subjectId === subjectId
                                ? { ...current, selectedReportId: item.id }
                                : current,
                            )
                          }
                        >
                          <span className={styles.timelineDot} />
                          <span className={styles.timelineTime}>
                            {new Date(item.generated_at).toLocaleTimeString("zh-CN", {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                          <strong>
                            {toNumber(item.summary.exposure.exposure_index).toFixed(1)}
                          </strong>
                          <small>
                            {new Date(item.generated_at).toLocaleDateString("zh-CN", {
                              month: "2-digit",
                              day: "2-digit",
                            })}
                            {delta !== null ? ` · ${delta >= 0 ? "+" : ""}${delta.toFixed(1)}` : ""}
                          </small>
                        </button>
                      );
                    })}
                </div>
              </section>

              <div className={styles.disclaimer}>
                <span className={styles.disclaimerIcon}>i</span>
                <span>{report.summary.exposure.disclaimer}</span>
              </div>
            </>
          ) : null}
        </>
      )}
    </main>
  );
}
