"use client";

import {
  ArrowRightOutlined,
  ClockCircleOutlined,
  FileSearchOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { Alert, Button, ConfigProvider, Empty } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import {
  GeoScoreRing,
  GlassSurface,
  InsightCard,
  MetricStat,
  ProgressTimeline,
  ProviderSignal,
  XwDataStateView,
  type MetricStatChange,
  type ProgressTimelineStep,
  type ProviderSignalFact,
  type XwDataState,
  type XwTone,
} from "@/components/xw";
import { GeoTrendChart, type GeoTrendPoint } from "@/components/xw/geo-trend-chart";
import { getDetectionHistory, type GeoDetectionJob } from "@/lib/geo-detection-client";
import {
  formatChineseDateTime,
  formatScore,
  getComparableMetricChanges,
  getComparableScoreChange,
  getLatestCompletedDetectionTime,
  getLatestStrategyInsight,
  getProviderSignals,
  getScoreState,
  getTrendPoints,
  toScore,
  type ProviderSignalTone,
  type ScoreStateTone,
} from "@/lib/geo-overview";
import {
  getReportHistory,
  getReportTrends,
  type GeoReport,
  type ReportTrend,
} from "@/lib/geo-report-client";
import { getQuestionBankDraft, type QuestionBankDraft } from "@/lib/question-bank-client";
import { getStrategies, type Strategy } from "@/lib/strategy-assistant-client";

import styles from "./workspace-overview.module.css";

type OverviewData = Readonly<{
  reports: GeoReport[];
  trends: ReportTrend[];
  detections: GeoDetectionJob[];
  questionBank: QuestionBankDraft | null;
  strategies: Strategy[];
}>;

type OverviewErrors = Readonly<{
  reports: boolean;
  trends: boolean;
  detections: boolean;
  questionBank: boolean;
  strategies: boolean;
}>;

type OverviewState = Readonly<{
  scopeKey: string;
  data: OverviewData;
  errors: OverviewErrors;
  strategyLoading: boolean;
}>;

const EMPTY_DATA: OverviewData = {
  reports: [],
  trends: [],
  detections: [],
  questionBank: null,
  strategies: [],
};

const EMPTY_ERRORS: OverviewErrors = {
  reports: false,
  trends: false,
  detections: false,
  questionBank: false,
  strategies: false,
};

const EMPTY_STATE: OverviewState = {
  scopeKey: "",
  data: EMPTY_DATA,
  errors: EMPTY_ERRORS,
  strategyLoading: false,
};

const SCORE_TONES: Record<ScoreStateTone, XwTone> = {
  excellent: "positive",
  good: "primary",
  improve: "warning",
  risk: "danger",
  empty: "neutral",
};

const PROVIDER_TONES: Record<ProviderSignalTone, XwTone> = {
  positive: "positive",
  attention: "warning",
  danger: "danger",
  active: "primary",
  neutral: "neutral",
};

function metricChange(value: number | null, unit: string): MetricStatChange | null {
  if (value === null) return null;
  return { value, unit, label: "较上次" };
}

function metricState(hasReport: boolean, failed: boolean): XwDataState {
  if (failed) return "error";
  return hasReport ? "ready" : "empty";
}

function withOverviewDeadline<T>(request: Promise<T>, waitMilliseconds = 10_000): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(
      () => reject(new Error("overview request ended")),
      waitMilliseconds,
    );
    request.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (reason) => {
        window.clearTimeout(timer);
        reject(reason);
      },
    );
  });
}

function OverviewLoading() {
  return (
    <main className={styles.overview} aria-label="正在加载 GEO 总览" aria-busy="true">
      <div className={styles.loadingShell}>
        <span className={styles.loadingBlock} />
        <span className={`${styles.loadingBlock} ${styles.loadingBlockWide}`} />
        <span className={styles.loadingBlock} />
        <span className={styles.loadingBlock} />
        <span className={styles.loadingBlock} />
      </div>
    </main>
  );
}

export default function WorkspacePage() {
  const { replace } = useRouter();
  const { currentSubject, loading: subjectLoading, subjects, user } = useSubjectWorkspace();
  const [overviewState, setOverviewState] = useState<OverviewState>(EMPTY_STATE);

  const subjectId = currentSubject?.id ?? "";
  const userId = user?.id ?? "";
  const userRole = user?.commercial_identity;
  const userHomeRoute = user?.home_route;
  const scopeKey = userId && subjectId ? `${userId}:${subjectId}` : "";
  const data = overviewState.scopeKey === scopeKey ? overviewState.data : EMPTY_DATA;
  const errors = overviewState.scopeKey === scopeKey ? overviewState.errors : EMPTY_ERRORS;
  const strategyLoading =
    overviewState.scopeKey === scopeKey ? overviewState.strategyLoading : false;
  const loading = Boolean(scopeKey && overviewState.scopeKey !== scopeKey);

  useEffect(() => {
    let active = true;

    if (subjectLoading) return () => undefined;
    if (!userId) {
      replace("/login");
      return () => undefined;
    }
    if (userRole !== "USER") {
      if (userHomeRoute) replace(userHomeRoute);
      return () => undefined;
    }
    if (!subjectId) {
      return () => undefined;
    }

    void (async () => {
      const [reportResult, trendResult, detectionResult, questionResult] = await Promise.allSettled(
        [
          withOverviewDeadline(getReportHistory(subjectId)),
          withOverviewDeadline(getReportTrends(subjectId)),
          withOverviewDeadline(getDetectionHistory(subjectId)),
          withOverviewDeadline(getQuestionBankDraft(subjectId)),
        ],
      );

      if (!active) return;

      const reports =
        reportResult.status === "fulfilled"
          ? [...reportResult.value.items].sort(
              (left, right) =>
                new Date(right.generated_at).getTime() - new Date(left.generated_at).getTime(),
            )
          : [];
      setOverviewState({
        scopeKey,
        data: {
          reports,
          trends: trendResult.status === "fulfilled" ? trendResult.value.items : [],
          detections: detectionResult.status === "fulfilled" ? detectionResult.value.items : [],
          questionBank: questionResult.status === "fulfilled" ? questionResult.value : null,
          strategies: [],
        },
        errors: {
          reports: reportResult.status === "rejected",
          trends: trendResult.status === "rejected",
          detections: detectionResult.status === "rejected",
          questionBank: questionResult.status === "rejected",
          strategies: false,
        },
        strategyLoading: Boolean(reports[0]),
      });

      if (!reports[0]) return;

      try {
        const strategies = (await withOverviewDeadline(getStrategies(reports[0].id))).items;
        if (!active) return;
        setOverviewState((current) =>
          current.scopeKey === scopeKey
            ? {
                ...current,
                data: { ...current.data, strategies },
                strategyLoading: false,
              }
            : current,
        );
      } catch {
        if (!active) return;
        setOverviewState((current) =>
          current.scopeKey === scopeKey
            ? {
                ...current,
                errors: { ...current.errors, strategies: true },
                strategyLoading: false,
              }
            : current,
        );
      }
    })();

    return () => {
      active = false;
    };
  }, [replace, scopeKey, subjectId, subjectLoading, userHomeRoute, userId, userRole]);

  const latestReport = data.reports[0] ?? null;
  const score = toScore(latestReport?.summary.geo.score);
  const scoreState = getScoreState(score);
  const comparableChanges = useMemo(
    () => getComparableMetricChanges(latestReport, data.reports),
    [data.reports, latestReport],
  );
  const scoreChange = getComparableScoreChange(latestReport, data.reports);
  const latestDetectionTime = getLatestCompletedDetectionTime(data.detections);
  const providerSignals = useMemo(() => getProviderSignals(latestReport), [latestReport]);
  const strategyInsight = useMemo(
    () => getLatestStrategyInsight(data.strategies),
    [data.strategies],
  );
  const trendPoints = useMemo<GeoTrendPoint[]>(
    () =>
      getTrendPoints(data.trends, 12).map((point) => ({
        id: point.reportId,
        label: point.dateLabel,
        score: point.score,
        detail: `${formatChineseDateTime(point.generatedAt, point.dateLabel)}，综合评分 ${formatScore(
          point.score,
        )}`,
      })),
    [data.trends],
  );

  const subjectReady = Boolean(currentSubject && currentSubject.current_version_no !== null);
  const questionReady = Boolean(data.questionBank?.current_question_bank_version_no);
  const subjectName =
    currentSubject?.official_name || currentSubject?.subject_type.name || "当前主体";
  const hasReport = latestReport !== null;
  const anyError = Object.values(errors).some(Boolean);

  const progressSteps = useMemo<ProgressTimelineStep[]>(() => {
    if (!currentSubject) return [];

    let currentKey = "profile";
    if (subjectReady) currentKey = "questions";
    if (questionReady || hasReport) currentKey = "detection";
    if (hasReport) currentKey = "strategy";
    if (strategyInsight) currentKey = "content";
    if (currentSubject.retest_required && hasReport) currentKey = "retest";

    const completedKeys = new Set<string>();
    if (subjectReady) completedKeys.add("profile");
    if (questionReady || hasReport) completedKeys.add("questions");
    if (hasReport) {
      completedKeys.add("detection");
      completedKeys.add("report");
    }
    if (strategyInsight) completedKeys.add("strategy");

    const statusFor = (key: string) => {
      if (key === currentKey) return "current" as const;
      return completedKeys.has(key) ? ("completed" as const) : ("upcoming" as const);
    };

    return [
      {
        key: "profile",
        title: "完善主体档案",
        description: "补全品牌、业务、产品与公开资料，建立可信的企业画像。",
        meta: subjectReady ? "主体资料已保存" : "等待完善主体资料",
        status: statusFor("profile"),
        href: `/subjects/${currentSubject.id}`,
        actionLabel: subjectReady ? "查看主体资料" : "完善主体资料",
      },
      {
        key: "questions",
        title: "建立关键词与问题库",
        description: "整理用户常见搜索需求，为检测提供明确的问题范围。",
        meta: errors.questionBank
          ? hasReport
            ? "已有检测报告，问题准备已完成"
            : "问题库状态暂时无法确认"
          : questionReady
            ? "问题库已就绪"
            : "等待建立问题库",
        status: statusFor("questions"),
        href: `/subjects/${currentSubject.id}/keywords`,
        actionLabel: questionReady ? "查看关键词资产" : "开始建立关键词",
      },
      {
        key: "detection",
        title: "完成人工智能可见度检测",
        description: "使用已确认的问题库，查看品牌在各主流平台回答中的表现。",
        meta: hasReport ? "已有检测结果" : questionReady ? "可以开始检测" : "等待问题库",
        status: statusFor("detection"),
        href: "/geo/detections",
        actionLabel: hasReport ? "查看检测记录" : "开始检测",
      },
      {
        key: "report",
        title: "查看 GEO 报告",
        description: "理解综合评分、曝光、提及、推荐和不同平台的表现差异。",
        meta: hasReport ? "最新报告可查看" : "等待检测结果",
        status: statusFor("report"),
        href: latestReport ? `/geo/reports/${latestReport.id}` : "/geo/reports",
        actionLabel: "查看检测报告",
      },
      {
        key: "strategy",
        title: "形成优化方案",
        description: "把报告结论转化为有优先级的优化方向和具体行动。",
        meta: strategyInsight ? "已有优化方向" : hasReport ? "可以生成方案" : "等待检测报告",
        status: statusFor("strategy"),
        href: latestReport ? `/geo/strategy/${latestReport.id}` : "/geo/strategy",
        actionLabel: strategyInsight ? "查看优化方案" : "生成优化方案",
      },
      {
        key: "content",
        title: "执行内容优化",
        description: "围绕优化方向生成并保存文章、图片和视频脚本。",
        meta: strategyInsight ? "可以开始内容优化" : "等待优化方案",
        status: statusFor("content"),
        href: `/subjects/${currentSubject.id}/articles/new`,
        actionLabel: "进入内容优化",
      },
      {
        key: "retest",
        title: "复测并验证变化",
        description: "优化完成后重新检测，通过前后结果对比验证优化效果。",
        meta: currentSubject.retest_required
          ? "主体资料有变化，建议复测"
          : hasReport
            ? "完成优化后可复测"
            : "等待首次检测",
        status: statusFor("retest"),
        href: "/geo/detections",
        actionLabel: "安排复测",
      },
    ];
  }, [
    currentSubject,
    errors.questionBank,
    hasReport,
    latestReport,
    questionReady,
    strategyInsight,
    subjectReady,
  ]);

  const primaryAction = useMemo(() => {
    if (!currentSubject) return { label: "创建主体", href: "/subjects" };
    if (!subjectReady) return { label: "完善主体资料", href: `/subjects/${currentSubject.id}` };
    if (!questionReady && !latestReport)
      return {
        label: errors.questionBank ? "查看关键词与问题库" : "建立关键词与问题库",
        href: `/subjects/${currentSubject.id}/keywords`,
      };
    if (!latestReport) return { label: "开始可见度检测", href: "/geo/detections" };
    return { label: "查看完整报告", href: `/geo/reports/${latestReport.id}` };
  }, [currentSubject, errors.questionBank, latestReport, questionReady, subjectReady]);

  if (subjectLoading || (subjectId && loading)) return <OverviewLoading />;
  if (!user) return null;

  const reportState = metricState(hasReport, errors.reports);
  const exposureValue = toScore(latestReport?.summary.exposure.exposure_index);
  const mentionValue = toScore(latestReport?.summary.exposure.mention_rate_score);
  const recommendationValue = toScore(latestReport?.summary.exposure.recommendation_rate_score);

  return (
    <ConfigProvider locale={zhCN}>
      <main className={styles.overview}>
        <header className={styles.header}>
          <div className={styles.headerCopy}>
            <p className={styles.eyebrow}>显问 GEO 情报中心</p>
            <h1 className={styles.title}>GEO 总览</h1>
            <p className={styles.subjectName}>{subjectName}</p>
            {currentSubject ? (
              <div className={styles.metaRow}>
                <span className={styles.metaItem}>
                  <ClockCircleOutlined aria-hidden="true" />
                  {errors.detections
                    ? "最近检测时间暂时无法显示"
                    : latestDetectionTime
                      ? `最近完成检测：${formatChineseDateTime(latestDetectionTime)}`
                      : "尚未完成首次检测"}
                </span>
                {currentSubject.retest_required ? (
                  <span className={styles.metaItem}>主体资料有更新，建议安排复测</span>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className={styles.headerActions}>
            <Button href="/subjects" icon={<SwapOutlined />}>
              切换主体
            </Button>
            <Button type="primary" href={primaryAction.href}>
              {primaryAction.label} <ArrowRightOutlined />
            </Button>
          </div>
        </header>

        {anyError ? (
          <Alert
            type="warning"
            showIcon
            message="部分内容暂时无法显示"
            description="其他功能仍可正常使用，你可以稍后刷新页面。"
          />
        ) : null}

        {!currentSubject ? (
          <section className={styles.emptySubject}>
            <Empty description="创建并选择主体后，即可查看检测、趋势和优化进度。">
              <Button type="primary" href="/subjects">
                创建并选择主体
              </Button>
            </Empty>
          </section>
        ) : (
          <>
            <section className={styles.heroGrid} aria-label="核心表现">
              <GlassSurface level="strong">
                <GeoScoreRing
                  value={score}
                  change={scoreChange}
                  label="GEO 综合评分"
                  description="衡量品牌在主流人工智能回答中的综合表现"
                  statusLabel={scoreState.label}
                  statusTone={SCORE_TONES[scoreState.tone]}
                  state={reportState}
                  messages={{
                    empty: "完成首次检测后，这里会显示综合评分。",
                    error: "综合评分暂时无法显示，请稍后再试。",
                  }}
                />
              </GlassSurface>

              <GlassSurface level="soft" className={styles.trendSurface}>
                <GeoTrendChart title="GEO 表现趋势" points={trendPoints} error={errors.trends} />
              </GlassSurface>

              <InsightCard
                title="智能洞察"
                headline={strategyInsight?.title}
                summary={strategyInsight?.summary || strategyInsight?.overview}
                items={(strategyInsight?.actions ?? []).slice(0, 3).map((text) => ({ text }))}
                priorityLabel={strategyInsight ? "当前优先事项" : undefined}
                action={
                  latestReport
                    ? {
                        label: strategyInsight ? "查看完整方案" : "生成优化方案",
                        href: `/geo/strategy/${latestReport.id}`,
                      }
                    : undefined
                }
                state={
                  strategyLoading
                    ? "loading"
                    : errors.strategies
                      ? "error"
                      : strategyInsight
                        ? "ready"
                        : "empty"
                }
                messages={{
                  empty: hasReport
                    ? "检测报告已生成，可以继续形成优化方向。"
                    : "完成检测后，这里会展示对应的优化洞察。",
                  error: "优化洞察暂时无法显示，请稍后再试。",
                }}
              />
            </section>

            <section className={styles.metricGrid} aria-label="关键指标">
              <MetricStat
                label="人工智能曝光指数"
                value={exposureValue}
                precision={1}
                status={
                  exposureValue === null
                    ? undefined
                    : {
                        label: getScoreState(exposureValue).label,
                        tone: SCORE_TONES[getScoreState(exposureValue).tone],
                      }
                }
                change={metricChange(comparableChanges.exposure, " 分")}
                description="综合衡量当前主体在各检测平台中的可见程度"
                state={reportState}
              />
              <MetricStat
                label="品牌提及率"
                value={mentionValue}
                suffix="%"
                precision={1}
                change={metricChange(comparableChanges.mention, " 个百分点")}
                description="在有效回答中，明确提及当前品牌的占比"
                state={reportState}
              />
              <MetricStat
                label="推荐表现"
                value={recommendationValue}
                suffix="%"
                precision={1}
                change={metricChange(comparableChanges.recommendation, " 个百分点")}
                description="在有效回答中，主动推荐当前品牌的占比"
                state={reportState}
              />
            </section>

            <section className={styles.sectionGrid}>
              <section className={styles.section} aria-labelledby="provider-heading">
                <div className={styles.sectionHeader}>
                  <div>
                    <h2 className={styles.sectionTitle} id="provider-heading">
                      各人工智能平台表现
                    </h2>
                    <p className={styles.sectionDescription}>
                      查看本次检测中各平台的综合评分与完成情况。
                    </p>
                  </div>
                  {latestReport ? (
                    <Button href={`/geo/reports/${latestReport.id}`} icon={<FileSearchOutlined />}>
                      查看详细结果
                    </Button>
                  ) : null}
                </div>
                <XwDataStateView
                  state={errors.reports ? "error" : providerSignals.length > 0 ? "ready" : "empty"}
                  loading="正在整理平台表现…"
                  empty="完成检测后，这里会展示本次检测中的平台表现。"
                  error="平台表现暂时无法显示，请稍后再试。"
                  skeletonLines={3}
                >
                  <div className={styles.providerList}>
                    {providerSignals.map((provider) => {
                      const facts: ProviderSignalFact[] = [
                        {
                          label: "检测状态",
                          value: provider.statusLabel,
                          tone: PROVIDER_TONES[provider.statusTone],
                        },
                        { label: "检测结果", value: provider.callSummary },
                      ];
                      return (
                        <ProviderSignal
                          key={provider.modelId}
                          name={provider.name}
                          value={provider.score}
                          valueLabel={
                            provider.score === null
                              ? provider.scoreText
                              : `${provider.scoreText} 分`
                          }
                          facts={facts}
                          tone={PROVIDER_TONES[provider.statusTone]}
                        />
                      );
                    })}
                  </div>
                </XwDataStateView>
              </section>

              <section className={styles.section}>
                <ProgressTimeline title="GEO 成长进度" steps={progressSteps} state="ready" />
              </section>
            </section>

            <section className={styles.reportSection} aria-labelledby="recent-reports-heading">
              <div className={styles.sectionHeader}>
                <div>
                  <h2 className={styles.sectionTitle} id="recent-reports-heading">
                    最近检测报告
                  </h2>
                  <p className={styles.sectionDescription}>
                    查看当前主体最近完成的检测结果与综合评分。
                  </p>
                </div>
                {data.reports.length > 0 ? <Button href="/geo/reports">查看全部报告</Button> : null}
              </div>
              <XwDataStateView
                state={errors.reports ? "error" : data.reports.length > 0 ? "ready" : "empty"}
                empty="完成首次检测后，这里会显示检测报告。"
                error="检测报告暂时无法显示，请稍后再试。"
              >
                <div className={styles.reportList}>
                  {data.reports.slice(0, 4).map((report) => (
                    <a
                      className={styles.reportItem}
                      href={`/geo/reports/${report.id}`}
                      key={report.id}
                    >
                      <span className={styles.reportScore}>
                        {formatScore(report.summary.geo.score)} 分
                      </span>
                      <span>GEO 综合评分</span>
                      <span className={styles.reportTime}>
                        {formatChineseDateTime(report.generated_at)}
                      </span>
                    </a>
                  ))}
                </div>
              </XwDataStateView>
            </section>

            {subjects.length > 1 ? (
              <p className={styles.emptyCopy}>
                当前账号共有 {subjects.length} 个主体，可在页面顶部切换主体。
              </p>
            ) : null}
          </>
        )}
      </main>
    </ConfigProvider>
  );
}
