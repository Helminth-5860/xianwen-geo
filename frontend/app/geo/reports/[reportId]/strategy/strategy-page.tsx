"use client";

import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Radio,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import {
  GeoScoreRing,
  GlassSurface,
  MetricStat,
  ProgressTimeline,
  type ProgressTimelineStep,
  type XwTone,
} from "@/components/xw";
import { userMessage } from "@/lib/auth-client";
import { formatChineseDateTime, getScoreState, toScore } from "@/lib/geo-overview";
import { getReport, type GeoReport } from "@/lib/geo-report-client";
import { getPaidMediaLogoFallback } from "@/lib/paid-media-catalog";
import {
  createStrategy,
  getStrategies,
  getStrategy,
  saveStrategyNote,
  type Strategy,
  type StrategyList,
  type StrategyPeriod,
} from "@/lib/strategy-assistant-client";
import {
  createExecutionPlan,
  getExecutionPreview,
  type ExecutionPackage,
  type ExecutionPreviewResponse,
  type ExecutionRecommendedMedia,
} from "@/lib/strategy-execution-client";

import styles from "./strategy-page.module.css";

export const STRATEGY_POLL_INTERVAL_MS = 1200;
const RECOMMENDED_TARGET = 70;

const priceFormatter = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const strategyStatusLabel = (status: Strategy["status"]) =>
  ({ queued: "等待分析", running: "分析中", succeeded: "已完成", failed: "未完成" })[status];

const priorityLabels = {
  urgent: { text: "立即处理", color: "red" },
  high: { text: "优先处理", color: "orange" },
  medium: { text: "建议处理", color: "blue" },
  low: { text: "持续改善", color: "default" },
} as const;

const kindLabels = {
  self_service: "可自行完成",
  platform_assisted: "平台辅助",
  manual_service: "人工服务",
  paid_media: "付费媒体",
} as const;

const scoreTone: Record<ReturnType<typeof getScoreState>["tone"], XwTone> = {
  excellent: "positive",
  good: "primary",
  improve: "warning",
  risk: "danger",
  empty: "neutral",
};

function formatPrice(priceCents: number) {
  return priceFormatter.format(Math.max(0, priceCents) / 100);
}

function formatRemaining(value: number | null | undefined) {
  if (value === null || value === undefined) return "以当前套餐为准";
  if (value >= 1_000_000) return "不限";
  return String(value);
}

function safePageMessage(reason: unknown) {
  const message = userMessage(reason);
  if (/deepseek|provider|runtime|binding|http|json|[A-Z][A-Z0-9]+_[A-Z0-9_]+/i.test(message)) {
    return "当前分析暂未完成，请稍后重新尝试。";
  }
  return message;
}

function metricSeverity(value: number | null) {
  if (value === null) return { label: "等待数据", tone: "neutral" as XwTone };
  if (value < 40) return { label: "明显短板", tone: "danger" as XwTone };
  if (value < 60) return { label: "需要提升", tone: "warning" as XwTone };
  return { label: "保持改善", tone: "positive" as XwTone };
}

function MediaLogo({ media }: Readonly<{ media: ExecutionRecommendedMedia }>) {
  const [failed, setFailed] = useState(false);
  if (!media.logo_path || failed) {
    return (
      <span className={styles.mediaLogoFallback} aria-hidden="true">
        {getPaidMediaLogoFallback(media.name)}
      </span>
    );
  }
  return (
    <Image
      className={styles.mediaLogo}
      src={media.logo_path}
      alt={`${media.name}标识`}
      width={42}
      height={42}
      onError={() => setFailed(true)}
    />
  );
}

type PainPoint = Readonly<{
  key: string;
  title: string;
  value: number | null;
  valueText: string;
  explanation: string;
  statusLabel?: string;
  tone?: XwTone;
}>;

function PainPointCard({ item }: Readonly<{ item: PainPoint }>) {
  const severity = item.statusLabel
    ? { label: item.statusLabel, tone: item.tone ?? ("neutral" as XwTone) }
    : metricSeverity(item.value);
  return (
    <article className={styles.painCard} data-tone={severity.tone}>
      <div className={styles.painCardHeader}>
        <strong>{item.title}</strong>
        <span>{severity.label}</span>
      </div>
      <p className={styles.painValue}>{item.valueText}</p>
      <p>{item.explanation}</p>
    </article>
  );
}

export default function ImprovementStrategyPage({ reportId }: Readonly<{ reportId: string }>) {
  const router = useRouter();
  const { currentSubject, loading: subjectLoading } = useSubjectWorkspace();
  const [data, setData] = useState<StrategyList>();
  const [report, setReport] = useState<GeoReport>();
  const [selected, setSelected] = useState<Strategy>();
  const [preview, setPreview] = useState<ExecutionPreviewResponse>();
  const [previewForStrategy, setPreviewForStrategy] = useState("");
  const [selectedPackageCode, setSelectedPackageCode] = useState("");
  const [selectedItemKeys, setSelectedItemKeys] = useState(() => new Set<string>());
  const [selectedMediaIds, setSelectedMediaIds] = useState(() => new Set<string>());
  const [period, setPeriod] = useState<StrategyPeriod>("30d");
  const [customDays, setCustomDays] = useState(14);
  const [note, setNote] = useState("");
  const [noteVersion, setNoteVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [creatingPlan, setCreatingPlan] = useState(false);
  const [confirmingPlan, setConfirmingPlan] = useState(false);
  const [error, setError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [notice, setNotice] = useState("");

  const currentSubjectId = currentSubject?.id ?? "";

  const load = useCallback(async () => {
    if (subjectLoading) return;
    try {
      const [nextStrategies, nextReport] = await Promise.all([
        getStrategies(reportId),
        getReport(reportId),
      ]);
      if (!currentSubjectId || nextReport.subject_id !== currentSubjectId) {
        router.replace("/geo/strategy");
        return;
      }
      setData(nextStrategies);
      setReport(nextReport);
      setSelected(
        (current) =>
          nextStrategies.items.find((item) => item.id === current?.id) ?? nextStrategies.items[0],
      );
      setError("");
    } catch (reason) {
      setError(safePageMessage(reason));
    }
  }, [currentSubjectId, reportId, router, subjectLoading]);

  useEffect(() => {
    if (subjectLoading) return;
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load, subjectLoading]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setNote(selected?.note?.text ?? "");
      setNoteVersion(selected?.note?.version ?? 0);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selected]);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      if (!selected || selected.status !== "succeeded") {
        setPreview(undefined);
        setPreviewForStrategy("");
        return;
      }
      setPreviewForStrategy("");
      setPreviewError("");
      void getExecutionPreview(selected.id)
        .then((next) => {
          if (!active) return;
          if (next.plan && next.plan.subject_id !== currentSubjectId) {
            router.replace("/geo/strategy");
            return;
          }
          const preferred =
            next.preview.packages.find((item) => item.code === next.plan?.package_code) ??
            next.preview.packages.find((item) => item.recommended) ??
            next.preview.packages[0];
          setPreview(next);
          setPreviewForStrategy(selected.id);
          setSelectedPackageCode(preferred?.code ?? "");
          setSelectedItemKeys(
            new Set(
              next.plan?.items
                .filter((item) => item.key !== "paid-media")
                .map((item) => item.key) ??
                preferred?.item_keys ??
                next.preview.items
                  .filter((item) => item.selected_by_default)
                  .map((item) => item.key),
            ),
          );
          setSelectedMediaIds(
            new Set(
              next.plan?.selected_media.map((item) => item.id) ??
                preferred?.media_ids ??
                next.preview.recommended_media
                  .filter((item) => item.selected_by_default)
                  .map((item) => item.id),
            ),
          );
        })
        .catch((reason) => {
          if (!active) return;
          setPreviewForStrategy(selected.id);
          setPreviewError(safePageMessage(reason));
        });
    }, 0);
    return () => {
      window.clearTimeout(timer);
      active = false;
    };
  }, [currentSubjectId, router, selected]);

  useEffect(() => {
    if (!selected || !["queued", "running"].includes(selected.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await getStrategy(selected.id);
        setSelected(next);
        if (["succeeded", "failed"].includes(next.status)) await load();
      } catch (reason) {
        setError(safePageMessage(reason));
      }
    }, STRATEGY_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [load, selected]);

  const generate = async () => {
    if (!data) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await createStrategy(
        reportId,
        {
          period,
          ...(period === "custom" ? { custom_days: customDays } : {}),
          regenerate: !data.first_free_available,
        },
        crypto.randomUUID(),
      );
      setSelected(next);
      setNotice("已开始分析检测结果，完成后会自动更新本页。未完成不会扣除次数。");
    } catch (reason) {
      setError(safePageMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const saveNote = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const saved = await saveStrategyNote(selected.id, note, noteVersion);
      setNoteVersion(saved.version);
      setSelected({ ...selected, note: saved });
      setNotice("个人备注已保存");
      setError("");
    } catch (reason) {
      setError(safePageMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const selectPackage = (item: ExecutionPackage) => {
    setSelectedPackageCode(item.code);
    setSelectedItemKeys(new Set(item.item_keys));
    setSelectedMediaIds(new Set(item.media_ids));
  };

  const createPlan = async () => {
    if (!selected || !selectedPackageCode || creatingPlan) return;
    setCreatingPlan(true);
    setPreviewError("");
    try {
      const plan = await createExecutionPlan(
        selected.id,
        {
          package_code: selectedPackageCode,
          item_keys: Array.from(selectedItemKeys),
          media_ids: Array.from(selectedMediaIds),
        },
        crypto.randomUUID(),
      );
      setConfirmingPlan(false);
      router.push(`/geo/execution/${plan.id}`);
    } catch (reason) {
      setConfirmingPlan(false);
      setPreviewError(safePageMessage(reason));
    } finally {
      setCreatingPlan(false);
    }
  };

  const previewReady = Boolean(selected && previewForStrategy === selected.id && preview);
  const previewLoading = Boolean(
    selected?.status === "succeeded" && previewForStrategy !== selected.id,
  );
  const generating = Boolean(selected && ["queued", "running"].includes(selected.status));
  const score = toScore(report?.summary.geo.score);
  const scoreState = getScoreState(score);
  const gap =
    score === null ? null : Math.max(0, Math.round((RECOMMENDED_TARGET - score) * 10) / 10);
  const exposure = toScore(report?.summary.exposure.exposure_index);
  const mention = toScore(report?.summary.exposure.mention_rate_score);
  const recommendation = toScore(report?.summary.exposure.recommendation_rate_score);
  const ranking = toScore(report?.summary.exposure.ranking_performance_score);
  const coverage = toScore(report?.summary.exposure.model_coverage_score);
  const competitorMentions =
    report?.summary.competitors.reduce((total, item) => total + item.mention_count, 0) ?? 0;

  const painPoints = useMemo<PainPoint[]>(
    () => [
      {
        key: "exposure",
        title: "整体曝光不足",
        value: exposure,
        valueText: exposure === null ? "暂无评分" : `${exposure.toFixed(1)} 分`,
        explanation: "品牌在主流智能平台回答中的整体出现机会仍有提升空间。",
      },
      {
        key: "mention",
        title: "品牌提及偏少",
        value: mention,
        valueText: mention === null ? "暂无评分" : `${mention.toFixed(1)} 分`,
        explanation: "用户询问相关服务时，品牌被明确提到的表现还不稳定。",
      },
      {
        key: "recommendation",
        title: "主动推荐偏弱",
        value: recommendation,
        valueText: recommendation === null ? "暂无评分" : `${recommendation.toFixed(1)} 分`,
        explanation: "品牌即使被识别，也未必会成为回答中的优先推荐对象。",
      },
      {
        key: "ranking",
        title: "出现位置靠后",
        value: ranking,
        valueText: ranking === null ? "暂无评分" : `${ranking.toFixed(1)} 分`,
        explanation: "较靠后的出现位置会降低用户继续了解和咨询的可能性。",
      },
      {
        key: "coverage",
        title: "平台覆盖不均",
        value: coverage,
        valueText: coverage === null ? "暂无评分" : `${coverage.toFixed(1)} 分`,
        explanation: "不同智能平台对主体的识别程度存在差异，需要补齐公开信息。",
      },
      {
        key: "competitors",
        title: "竞品信号需要关注",
        value: null,
        valueText: `${competitorMentions} 次竞品提及`,
        explanation:
          competitorMentions > 0
            ? "检测回答中已出现竞品信号，应结合具体问题查看品牌差距。"
            : "本次检测暂未发现竞品提及，后续仍可通过复测持续观察。",
        statusLabel: competitorMentions > 0 ? "需要关注" : "暂未发现",
        tone: competitorMentions > 0 ? "warning" : "positive",
      },
    ],
    [competitorMentions, coverage, exposure, mention, ranking, recommendation],
  );

  const selectedItems =
    preview?.preview.items.filter((item) => selectedItemKeys.has(item.key)) ?? [];
  const selectedMedia =
    preview?.preview.recommended_media.filter((item) => selectedMediaIds.has(item.id)) ?? [];
  const selectedPackage = preview?.preview.packages.find(
    (item) => item.code === selectedPackageCode,
  );
  const selectionMatchesPackage = Boolean(
    selectedPackage &&
    selectedPackage.item_keys.length === selectedItemKeys.size &&
    selectedPackage.media_ids.length === selectedMediaIds.size &&
    selectedPackage.item_keys.every((key) => selectedItemKeys.has(key)) &&
    selectedPackage.media_ids.every((id) => selectedMediaIds.has(id)),
  );
  const selectedPackageName = selectionMatchesPackage
    ? (selectedPackage?.name ?? "自定义方案")
    : "自定义方案";
  const selectedTotal =
    selectedItems.reduce((total, item) => total + item.estimated_price_cents, 0) +
    selectedMedia.reduce((total, item) => total + item.price_cents, 0);

  const timelineSteps = useMemo<ProgressTimelineStep[]>(
    () =>
      selected?.body?.schedule.map((item, index) => ({
        key: `${item.phase}-${index}`,
        title: item.phase,
        description: item.focus,
        meta: item.actions.join("；"),
        status: index === 0 ? "current" : "upcoming",
      })) ?? [],
    [selected],
  );

  if (subjectLoading || (!data && !error))
    return <Spin fullscreen description="正在整理优化方案" />;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <Typography.Text type="secondary">优化中心</Typography.Text>
          <Typography.Title level={2}>当前主体 GEO 优化方案</Typography.Title>
          <Typography.Paragraph type="secondary">
            根据真实检测结果梳理短板、行动优先级、预计周期和所需投入。
          </Typography.Paragraph>
        </div>
        <Space wrap>
          <Button href={`/geo/reports/${reportId}`}>查看检测报告</Button>
          <Button href="/geo/strategy">返回方案列表</Button>
        </Space>
      </header>

      {error ? <Alert type="error" showIcon message={error} /> : null}
      {notice ? <Alert type="success" showIcon message={notice} /> : null}

      {report ? (
        <>
          <section className={styles.subjectBar}>
            <div>
              <Typography.Text type="secondary">当前主体</Typography.Text>
              <Typography.Title level={3}>
                {currentSubject?.official_name || currentSubject?.subject_type.name}
              </Typography.Title>
            </div>
            <Space wrap>
              <Tag color={scoreState.tone === "risk" ? "red" : "blue"}>{scoreState.label}</Tag>
              <Typography.Text type="secondary">
                检测时间 {formatChineseDateTime(report.generated_at)}
              </Typography.Text>
            </Space>
          </section>

          <section className={styles.heroGrid} aria-label="核心诊断">
            <GlassSurface level="strong">
              <GeoScoreRing
                value={score}
                label="GEO 综合评分"
                statusLabel={scoreState.label}
                statusTone={scoreTone[scoreState.tone]}
                description={`建议先提升至 ${RECOMMENDED_TARGET} 分，再通过复测查看真实变化。`}
              />
            </GlassSurface>
            <div className={styles.metricGrid}>
              <MetricStat
                label="距离建议目标"
                value={gap}
                suffix="分"
                status={{
                  label: `目标 ${RECOMMENDED_TARGET} 分`,
                  tone: gap && gap > 0 ? "warning" : "positive",
                }}
                description="这是阶段性改善目标，不是行业平均值。"
              />
              <MetricStat
                label="曝光指数"
                value={exposure}
                suffix="分"
                status={metricSeverity(exposure)}
                description="衡量主体在回答中的整体曝光表现。"
              />
              <MetricStat
                label="品牌提及"
                value={mention}
                suffix="分"
                status={metricSeverity(mention)}
                description="衡量品牌在相关回答中被明确提到的表现。"
              />
              <MetricStat
                label="推荐表现"
                value={recommendation}
                suffix="分"
                status={metricSeverity(recommendation)}
                description="衡量品牌成为推荐对象的表现。"
              />
            </div>
          </section>

          <Card
            title="当前最需要解决的短板"
            extra={<Button href={`/geo/reports/${reportId}`}>查看检测证据</Button>}
          >
            <div className={styles.painGrid}>
              {painPoints.map((item) => (
                <PainPointCard item={item} key={item.key} />
              ))}
            </div>
          </Card>

          <section className={styles.impactPanel} aria-label="持续不处理可能产生的影响">
            <WarningOutlined aria-hidden="true" />
            <div>
              <h2>如果长期不处理，可能持续影响客户发现和选择您的机会</h2>
              <ul>
                <li>用户询问相关产品或服务时，品牌出现机会偏少。</li>
                <li>主体即使被提及，也可能无法进入优先推荐位置。</li>
                <li>公开资料与权威信源不足，会影响平台理解企业与业务的关系。</li>
              </ul>
              <Typography.Text type="secondary">
                上述内容是根据本次检测表现给出的风险提示，不代表确定的经营损失。
              </Typography.Text>
            </div>
          </section>
        </>
      ) : null}

      {selected?.status === "succeeded" ? (
        <>
          <section className={styles.sectionHeading}>
            <div>
              <Typography.Title level={3}>选择适合您的改善方案</Typography.Title>
              <Typography.Paragraph type="secondary">
                可以先选择推荐方案，再按实际需要调整行动项和媒体。
              </Typography.Paragraph>
            </div>
            {preview?.plan ? (
              <Button type="primary" href={`/geo/execution/${preview.plan.id}`}>
                查看当前执行计划 <ArrowRightOutlined />
              </Button>
            ) : null}
          </section>
          {previewError ? <Alert type="warning" showIcon message={previewError} /> : null}
          {previewLoading ? <Spin description="正在整理可执行方案" /> : null}

          {previewReady && preview ? (
            <>
              <div className={styles.packageGrid}>
                {preview.preview.packages.map((item) => {
                  const active = selectedPackageCode === item.code;
                  return (
                    <button
                      type="button"
                      disabled={Boolean(preview.plan)}
                      className={[styles.packageCard, active && styles.packageCardActive]
                        .filter(Boolean)
                        .join(" ")}
                      aria-pressed={active}
                      onClick={() => selectPackage(item)}
                      key={item.code}
                    >
                      <span className={styles.packageHeader}>
                        <strong>{item.name}</strong>
                        {item.recommended ? <Tag color="blue">推荐</Tag> : null}
                      </span>
                      <span>{item.description}</span>
                      <b>
                        {item.media_ids.length > 0
                          ? `媒体参考费用 ${formatPrice(item.estimated_price_cents)}`
                          : "暂不含付费媒体"}
                      </b>
                      <small>
                        预计 {item.estimated_days} 天 · {item.item_keys.length} 项行动
                      </small>
                    </button>
                  );
                })}
              </div>

              <Card title="行动项目" extra={<Tag>已选 {selectedItemKeys.size} 项</Tag>}>
                <div className={styles.actionList}>
                  {preview.preview.items.map((item) => {
                    const checked = selectedItemKeys.has(item.key);
                    const priority = priorityLabels[item.priority];
                    return (
                      <article className={styles.actionItem} key={item.key}>
                        <Checkbox
                          checked={checked}
                          disabled={Boolean(preview.plan)}
                          aria-label={`选择行动：${item.title}`}
                          onChange={(event) =>
                            setSelectedItemKeys((current) => {
                              const next = new Set(current);
                              if (event.target.checked) next.add(item.key);
                              else next.delete(item.key);
                              return next;
                            })
                          }
                        />
                        <div>
                          <Space wrap>
                            <strong>{item.title}</strong>
                            <Tag color={priority.color}>{priority.text}</Tag>
                            <Tag>{kindLabels[item.kind]}</Tag>
                          </Space>
                          <p>{item.problem}</p>
                          <dl>
                            <div>
                              <dt>为什么要做</dt>
                              <dd>{item.reason}</dd>
                            </div>
                            <div>
                              <dt>具体建议</dt>
                              <dd>{item.recommendation}</dd>
                            </div>
                            <div>
                              <dt>完成标准</dt>
                              <dd>{item.success_metric}</dd>
                            </div>
                          </dl>
                        </div>
                        <div className={styles.actionMeta}>
                          <span>
                            <ClockCircleOutlined /> {item.estimated_days} 天
                          </span>
                          <strong>{item.cost_note}</strong>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </Card>

              {preview.preview.recommended_media.length > 0 ? (
                <Card
                  title="推荐付费媒体"
                  extra={<Tag color="orange">已选 {selectedMediaIds.size} 家</Tag>}
                >
                  <Alert
                    type="info"
                    showIcon
                    message="系统只做推荐和预选。提交前会再次显示媒体名单与费用，并由管理员联系您确认。"
                  />
                  <div className={styles.mediaGrid}>
                    {preview.preview.recommended_media.map((media) => (
                      <article className={styles.mediaItem} key={media.id}>
                        <Checkbox
                          checked={selectedMediaIds.has(media.id)}
                          disabled={Boolean(preview.plan)}
                          aria-label={`选择媒体：${media.name}`}
                          onChange={(event) =>
                            setSelectedMediaIds((current) => {
                              const next = new Set(current);
                              if (event.target.checked) next.add(media.id);
                              else next.delete(media.id);
                              return next;
                            })
                          }
                        />
                        <MediaLogo media={media} />
                        <div>
                          {media.url ? (
                            <a href={media.url} target="_blank" rel="noopener noreferrer">
                              {media.name}
                            </a>
                          ) : (
                            <strong>{media.name}</strong>
                          )}
                          <span>{media.reason}</span>
                        </div>
                        <strong>{formatPrice(media.price_cents)}</strong>
                      </article>
                    ))}
                  </div>
                </Card>
              ) : null}

              <aside className={styles.summaryBar} aria-label="方案费用汇总">
                <div>
                  <Typography.Text type="secondary">当前选择</Typography.Text>
                  <strong>{selectedPackageName}</strong>
                </div>
                <div>
                  <Typography.Text type="secondary">行动项目</Typography.Text>
                  <strong>{selectedItemKeys.size} 项</strong>
                </div>
                <div>
                  <Typography.Text type="secondary">付费媒体</Typography.Text>
                  <strong>{selectedMediaIds.size} 家</strong>
                </div>
                <div>
                  <Typography.Text type="secondary">媒体参考费用</Typography.Text>
                  <strong className={styles.totalPrice}>{formatPrice(selectedTotal)}</strong>
                </div>
                {preview.plan ? (
                  <Button type="primary" size="large" href={`/geo/execution/${preview.plan.id}`}>
                    进入执行计划
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    size="large"
                    disabled={
                      !selectedPackageCode ||
                      (selectedItemKeys.size === 0 && selectedMediaIds.size === 0)
                    }
                    onClick={() => setConfirmingPlan(true)}
                  >
                    确认并建立执行计划
                  </Button>
                )}
              </aside>
            </>
          ) : null}
        </>
      ) : (
        <Card>
          <Empty description="先生成优化方案，系统才能进一步整理可执行行动。" />
        </Card>
      )}

      {selected?.status === "succeeded" && selected.body ? (
        <>
          <Card title="方案结论">
            <Typography.Paragraph className={styles.overviewText}>
              {selected.body.overview}
            </Typography.Paragraph>
            <List
              dataSource={[...selected.body.priorities]}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta
                    title={item.title}
                    description={
                      <Space orientation="vertical">
                        <Typography.Text>{item.rationale}</Typography.Text>
                        <ul>
                          {item.actions.map((action) => (
                            <li key={action}>{action}</li>
                          ))}
                        </ul>
                        <Typography.Text type="secondary">
                          完成标准：{item.success_metric}
                        </Typography.Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
          <Card title="阶段安排">
            <ProgressTimeline title="建议推进顺序" steps={timelineSteps} />
          </Card>
          <Card title="推荐文章主题">
            <List
              dataSource={[...selected.body.article_topics]}
              locale={{ emptyText: "当前方案暂无推荐文章主题" }}
              renderItem={(topic) => (
                <List.Item
                  actions={[
                    <Link key={topic.route} href={topic.route}>
                      带主题进入文章生成 <ArrowRightOutlined />
                    </Link>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<FileTextOutlined className={styles.articleIcon} />}
                    title={topic.title}
                    description={topic.reason}
                  />
                </List.Item>
              )}
            />
            <Typography.Text type="secondary">
              进入文章页面后仍由您确认资料和生成操作，不会自动扣除文章额度。
            </Typography.Text>
          </Card>
        </>
      ) : null}

      <Card title="生成与更新方案">
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <Radio.Group
            aria-label="方案周期"
            value={period}
            onChange={(event) => setPeriod(event.target.value as StrategyPeriod)}
            options={[
              { label: "7 天", value: "7d" },
              { label: "30 天", value: "30d" },
              { label: "90 天", value: "90d" },
              { label: "自定义", value: "custom" },
            ]}
          />
          {period === "custom" ? (
            <InputNumber
              aria-label="自定义天数"
              min={1}
              max={365}
              value={customDays}
              onChange={(value) => setCustomDays(value ?? 14)}
            />
          ) : null}
          <Space wrap>
            <Tag color={data?.first_free_available ? "green" : "blue"}>
              {data?.first_free_available ? "首份方案免费" : "已生成过方案"}
            </Tag>
            <Typography.Text>
              可重新生成次数：{formatRemaining(data?.remaining_regenerations)}
            </Typography.Text>
            <Button type="primary" loading={busy || generating} onClick={() => void generate()}>
              {data?.first_free_available ? "生成优化方案" : "重新生成方案"}
            </Button>
          </Space>
          <Typography.Text type="secondary">
            只有成功生成新方案才会扣除相应次数；未完成不会扣除，并会保留历史结果。
          </Typography.Text>
        </Space>
      </Card>

      {generating ? <Spin description="正在分析检测结果并生成方案" /> : null}
      {selected?.status === "failed" ? (
        <Alert
          type="error"
          showIcon
          message="优化方案未能生成，请稍后重新尝试；本次不会扣除次数。"
        />
      ) : null}
      {selected?.status === "succeeded" ? (
        <Card title="我的备注">
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Input.TextArea
              aria-label="个人备注"
              rows={4}
              maxLength={10000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
            <Button loading={busy} onClick={() => void saveNote()}>
              保存备注
            </Button>
          </Space>
        </Card>
      ) : null}

      <Card title="历史优化方案">
        <List
          locale={{ emptyText: "尚未生成优化方案" }}
          dataSource={data?.items ?? []}
          renderItem={(item) => (
            <List.Item
              onClick={() => setSelected(item)}
              className={styles.historyItem}
              actions={[<Button key={item.id}>查看</Button>]}
            >
              <List.Item.Meta
                avatar={
                  item.status === "succeeded" ? (
                    <CheckCircleOutlined className={styles.successIcon} />
                  ) : (
                    <SafetyCertificateOutlined />
                  )
                }
                title={`${item.period_days} 天方案 · ${strategyStatusLabel(item.status)}`}
                description={`${item.billing.first_free ? "首次生成" : "重新生成"} · ${formatChineseDateTime(item.created_at)}`}
              />
            </List.Item>
          )}
        />
      </Card>

      <Modal
        open={confirmingPlan}
        title="确认建立执行计划"
        okText="确认并进入执行计划"
        cancelText="返回调整"
        confirmLoading={creatingPlan}
        mask={{ closable: !creatingPlan }}
        keyboard={!creatingPlan}
        onOk={() => void createPlan()}
        onCancel={() => {
          if (!creatingPlan) setConfirmingPlan(false);
        }}
      >
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="本次确认后，所选媒体申请会一并提交管理员；不会自动付款或发布。"
          />
          <Row gutter={[12, 12]}>
            <Col span={12}>行动项目：{selectedItemKeys.size} 项</Col>
            <Col span={12}>推荐媒体：{selectedMediaIds.size} 家</Col>
            <Col span={24}>
              媒体参考费用：<strong>{formatPrice(selectedTotal)}</strong>
            </Col>
          </Row>
          {selectedMedia.length > 0 ? (
            <List
              size="small"
              header="本次提交的付费媒体"
              dataSource={selectedMedia.slice(0, 6)}
              renderItem={(media) => (
                <List.Item extra={<strong>{formatPrice(media.price_cents)}</strong>}>
                  {media.name}
                </List.Item>
              )}
            />
          ) : null}
          {selectedMedia.length > 6 ? (
            <Typography.Text type="secondary">
              另有 {selectedMedia.length - 6} 家媒体，均按当前勾选结果提交。
            </Typography.Text>
          ) : null}
          <Typography.Text type="secondary">
            其他功能可能按套餐额度规则结算。管理员收到申请后会联系您确认发布安排；
            确认前不会产生付款或发布动作。
          </Typography.Text>
        </Space>
      </Modal>
    </main>
  );
}
