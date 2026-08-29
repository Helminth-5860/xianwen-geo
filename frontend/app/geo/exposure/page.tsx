"use client";

import {
  AimOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  BarChartOutlined,
  ClockCircleOutlined,
  FundOutlined,
  GlobalOutlined,
  RadarChartOutlined,
  RobotOutlined,
  TrophyOutlined,
  UsergroupAddOutlined,
} from "@ant-design/icons";
import { Alert, Button, Empty, Select, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import { getReportHistory, type GeoReport, type ReportModel } from "@/lib/geo-report-client";

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

function toNumber(value: string | number | null | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, value));
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
  if (normalized.includes("wenxin") || normalized.includes("ernie") || normalized.includes("baidu")) {
    return "文心一言";
  }
  if (normalized.includes("hunyuan") || normalized.includes("yuanbao")) return "腾讯元宝";
  if (normalized.includes("glm") || normalized.includes("zhipu")) return "智谱";
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

function AnimatedNumber({ value, decimals = 1, suffix = "", duration = 900 }: AnimatedNumberProps) {
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
      if (elapsed < 1) {
        frame = requestAnimationFrame(tick);
      } else {
        valueRef.current = to;
      }
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
  icon: React.ReactNode;
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

export default function GeoExposurePage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [exposureState, setExposureState] = useState<ExposureState>();
  const [focusedModel, setFocusedModel] = useState<string>("");
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
        setExposureState({
          subjectId,
          reports,
          selectedReportId: reports[0]?.id ?? "",
          error: "",
        });
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
    if (!report) return;
    setFocusedModel((current) =>
      current && report.summary.models.some((model) => model.model_key === current) ? current : "",
    );
  }, [report]);

  const selectedIndex = state && report ? state.reports.findIndex((item) => item.id === report.id) : -1;
  const previousReport = selectedIndex >= 0 ? state?.reports[selectedIndex + 1] : undefined;
  const exposureValue = toNumber(report?.summary.exposure.exposure_index);
  const previousExposure = toNumber(previousReport?.summary.exposure.exposure_index);
  const exposureDelta = previousReport ? exposureValue - previousExposure : null;

  const modelNodes = useMemo<ModelNode[]>(() => {
    const models = report?.summary.models.slice(0, 7) ?? [];
    if (!models.length) return [];
    return models.map((model, index) => {
      const angle = -Math.PI / 2 + (index * Math.PI * 2) / models.length;
      const metric = modelMetric(model);
      return {
        model,
        x: 50 + Math.cos(angle) * 36,
        y: 50 + Math.sin(angle) * 31,
        score: metric.score,
        metricLabel: metric.label,
      };
    });
  }, [report]);

  const rankedModels = useMemo(() => {
    return [...(report?.summary.models ?? [])]
      .map((model) => ({ model, ...modelMetric(model) }))
      .sort((left, right) => right.score - left.score)
      .slice(0, 6);
  }, [report]);

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

  const trendPoints = useMemo(() => {
    if (!trendReports.length) return "";
    const values = trendReports.map((item) => toNumber(item.summary.exposure.exposure_index));
    const count = Math.max(1, values.length - 1);
    return values
      .map((value, index) => `${8 + (index / count) * 84},${88 - clampScore(value) * 0.72}`)
      .join(" ");
  }, [trendReports]);

  if (subjectLoading || (subject && !state)) {
    return <Spin fullscreen description="正在加载曝光作战中心" />;
  }

  return (
    <main className={styles.page}>
      <div className={styles.ambientGlow} aria-hidden="true" />

      <header className={styles.hero}>
        <div>
          <div className={styles.eyebrow}>
            <RadarChartOutlined /> EXPOSURE INTELLIGENCE
          </div>
          <Title level={2} className={styles.pageTitle}>
            曝光作战中心
          </Title>
          <Text className={styles.pageDescription}>
            一屏查看当前主体在 AI 检测中的曝光、提及、推荐、模型覆盖与历史变化。
          </Text>
        </div>
        <div className={styles.heroActions}>
          <Button href="/geo/reports">查看检测报告</Button>
          <Button type="primary" href="/geo/reports/history">
            历史报告对比
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
          <section className={styles.controlBar}>
            <div className={styles.subjectIdentity}>
              <span className={styles.subjectIcon}>
                <GlobalOutlined />
              </span>
              <div>
                <span className={styles.controlLabel}>当前主体</span>
                <strong>{subject.official_name || subject.subject_type.name}</strong>
              </div>
            </div>

            <div className={styles.reportControl}>
              <span className={styles.controlLabel}>检测报告</span>
              <Select
                aria-label="曝光指数报告"
                value={report?.id}
                placeholder="选择报告"
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
            </div>

            <div className={styles.controlMeta}>
              <span className={styles.controlLabel}>报告状态</span>
              <div className={styles.metaLine}>
                <span className={styles.statusDot} />
                {report?.summary.exposure.status === "formal" ? "正式结果" : "参考结果"}
              </div>
            </div>

            <div className={styles.controlMeta}>
              <span className={styles.controlLabel}>数据时间</span>
              <div className={styles.metaLine}>
                <ClockCircleOutlined />
                {report
                  ? new Date(report.generated_at).toLocaleString("zh-CN", {
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "--"}
              </div>
            </div>
          </section>

          {state?.error && <Alert type="error" showIcon message={state.error} className={styles.alert} />}

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
                  <div className={styles.panel}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>CORE METRICS</span>
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
                          className={`${styles.delta} ${
                            exposureDelta >= 0 ? styles.deltaUp : styles.deltaDown
                          }`}
                        >
                          {exposureDelta >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                          较上次 {Math.abs(exposureDelta).toFixed(1)}
                        </div>
                      )}
                    </div>

                    <div className={styles.metricGrid}>
                      <MiniMetric
                        icon={<GlobalOutlined />}
                        label="提及率"
                        value={toNumber(report.summary.exposure.mention_rate_score)}
                        suffix="%"
                      />
                      <MiniMetric
                        icon={<TrophyOutlined />}
                        label="推荐率"
                        value={toNumber(report.summary.exposure.recommendation_rate_score)}
                        suffix="%"
                      />
                      <MiniMetric
                        icon={<BarChartOutlined />}
                        label="排名表现"
                        value={toNumber(report.summary.exposure.ranking_performance_score)}
                      />
                      <MiniMetric
                        icon={<RobotOutlined />}
                        label="模型覆盖"
                        value={toNumber(report.summary.exposure.model_coverage_score)}
                        suffix="%"
                      />
                    </div>
                  </div>

                  <div className={`${styles.panel} ${styles.trendPanel}`}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>TREND</span>
                        <h3>曝光趋势</h3>
                      </div>
                      <FundOutlined />
                    </div>
                    {trendReports.length > 1 ? (
                      <>
                        <svg className={styles.trendChart} viewBox="0 0 100 100" preserveAspectRatio="none">
                          <defs>
                            <linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1">
                              <stop offset="0%" stopColor="rgba(83, 108, 255, .32)" />
                              <stop offset="100%" stopColor="rgba(83, 108, 255, 0)" />
                            </linearGradient>
                          </defs>
                          <line x1="8" x2="92" y1="88" y2="88" className={styles.chartAxis} />
                          <polyline points={trendPoints} className={styles.trendLineGlow} />
                          <polyline points={trendPoints} className={styles.trendLine} />
                          {trendReports.map((item, index) => {
                            const count = Math.max(1, trendReports.length - 1);
                            const x = 8 + (index / count) * 84;
                            const y = 88 - clampScore(toNumber(item.summary.exposure.exposure_index)) * 0.72;
                            return <circle key={item.id} cx={x} cy={y} r="1.8" className={styles.trendPoint} />;
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

                <section className={`${styles.panel} ${styles.commandMap}`}>
                  <div className={styles.commandMapHeader}>
                    <div>
                      <span className={styles.panelEyebrow}>AI MODEL CONSTELLATION</span>
                      <h3>AI 模型曝光星图</h3>
                      <p>中央为主体综合曝光指数，周围节点来自本次实际检测模型。</p>
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

                  <div className={styles.starMap}>
                    <div className={styles.gridField} aria-hidden="true" />
                    <div className={`${styles.orbit} ${styles.orbitOuter}`} aria-hidden="true" />
                    <div className={`${styles.orbit} ${styles.orbitInner}`} aria-hidden="true" />

                    <svg className={styles.connectionLayer} viewBox="0 0 100 100" preserveAspectRatio="none">
                      {modelNodes.map((node) => (
                        <line
                          key={node.model.model_id}
                          x1="50"
                          y1="50"
                          x2={node.x}
                          y2={node.y}
                          className={
                            !focusedModel || focusedModel === node.model.model_key
                              ? styles.connectionActive
                              : styles.connectionMuted
                          }
                        />
                      ))}
                    </svg>

                    <div className={styles.subjectCore}>
                      <div className={styles.corePulse} aria-hidden="true" />
                      <span className={styles.coreLabel}>综合曝光</span>
                      <strong>
                        <AnimatedNumber value={exposureValue} decimals={1} />
                      </strong>
                      <small>{subject.official_name || subject.subject_type.name}</small>
                    </div>

                    {modelNodes.map((node) => {
                      const active = !focusedModel || focusedModel === node.model.model_key;
                      return (
                        <button
                          type="button"
                          key={node.model.model_id}
                          className={`${styles.modelNode} ${active ? styles.modelNodeActive : styles.modelNodeMuted}`}
                          style={{ left: `${node.x}%`, top: `${node.y}%` }}
                          onClick={() =>
                            setFocusedModel((current) =>
                              current === node.model.model_key ? "" : node.model.model_key,
                            )
                          }
                        >
                          <span className={styles.modelNodeIcon}>
                            <RobotOutlined />
                          </span>
                          <strong>{modelDisplayName(node.model.model_key)}</strong>
                          <span>
                            {node.metricLabel} {node.score.toFixed(1)}
                          </span>
                        </button>
                      );
                    })}

                    {!modelNodes.length && <div className={styles.mapEmpty}>本报告没有模型明细</div>}
                  </div>

                  <div className={styles.commandMapFooter}>
                    <div>
                      <span className={styles.legendDotPrimary} /> 主体曝光
                    </div>
                    <div>
                      <span className={styles.legendDotModel} /> AI 模型节点
                    </div>
                    <div>
                      <span className={styles.legendLine} /> 检测关联
                    </div>
                  </div>
                </section>

                <aside className={styles.rightRail}>
                  <div className={styles.panel}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>MODEL RANKING</span>
                        <h3>模型检测表现</h3>
                      </div>
                      <TrophyOutlined />
                    </div>
                    <div className={styles.rankingList}>
                      {rankedModels.length ? (
                        rankedModels.map(({ model, score, label }, index) => (
                          <button
                            key={model.model_id}
                            type="button"
                            className={`${styles.rankingRow} ${
                              focusedModel === model.model_key ? styles.rankingRowActive : ""
                            }`}
                            onClick={() => setFocusedModel(model.model_key)}
                          >
                            <span className={styles.rankNo}>{index + 1}</span>
                            <span className={styles.rankName}>{modelDisplayName(model.model_key)}</span>
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

                  <div className={styles.panel}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>COMPETITOR SIGNAL</span>
                        <h3>竞品提及态势</h3>
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

                  <div className={styles.panel}>
                    <div className={styles.panelHeading}>
                      <div>
                        <span className={styles.panelEyebrow}>QUESTION SAMPLE</span>
                        <h3>检测问题样本</h3>
                      </div>
                      <AimOutlined />
                    </div>
                    <div className={styles.questionList}>
                      {report.provenance.questions.slice(0, 5).map((question, index) => (
                        <div className={styles.questionRow} key={question.source_question_id}>
                          <span>{String(index + 1).padStart(2, "0")}</span>
                          <p>{question.text}</p>
                        </div>
                      ))}
                      {!report.provenance.questions.length && (
                        <div className={styles.miniEmpty}>暂无问题快照</div>
                      )}
                    </div>
                  </div>
                </aside>
              </section>

              <section className={`${styles.panel} ${styles.timelinePanel}`}>
                <div className={styles.timelineHeader}>
                  <div>
                    <span className={styles.panelEyebrow}>REPORT TIMELINE</span>
                    <h3>历史曝光时间轴</h3>
                  </div>
                  <span>最近 {Math.min(state?.reports.length ?? 0, 7)} 份报告</span>
                </div>
                <div className={styles.timelineTrack}>
                  {(state?.reports ?? []).slice(0, 7).reverse().map((item) => {
                    const selected = item.id === report.id;
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
                        <strong>{toNumber(item.summary.exposure.exposure_index).toFixed(1)}</strong>
                        <small>
                          {new Date(item.generated_at).toLocaleDateString("zh-CN", {
                            month: "2-digit",
                            day: "2-digit",
                          })}
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
