"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Input,
  List,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Steps,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useSubjectSwitchGuard } from "@/components/subject-workspace-context";
import {
  chooseComparison,
  confirmSourcePack,
  createArticle,
  createArticleExport,
  createChannelAdaptations,
  createSourcePack,
  generateArticle,
  generateOutline,
  getArticle,
  getArticleJob,
  getArticleTypes,
  getChannelAdaptations,
  getComparison,
  getPublishingChannels,
  optimizeArticle,
  recheckQuality,
  saveArticleDraft,
  saveOutline,
  type Article,
  type ArticleJob,
  type ArticleType,
  type ChannelAdaptation,
  type PublishingChannel,
  type SourcePack,
} from "@/lib/articles-client";
import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  getDocumentParseResult,
  getSubjectDocuments,
  type SubjectDocument,
} from "@/lib/documents-client";
import { listWebSources } from "@/lib/web-sources-client";

export const ARTICLE_POLL_INTERVAL_MS = 1200;

type Props = Readonly<{ subjectId: string; initialTopic: string }>;
type DocumentOption = SubjectDocument & { confirmedSourceId: string };
type JobError = Readonly<{ jobId: string; operation: string; message: string }>;

const ARTICLE_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  ARTICLE_ALREADY_GENERATED: "正文已经生成，请勿重复提交。",
  ARTICLE_GENERATION_IN_PROGRESS: "当前文章正在生成，请稍候。",
  ARTICLE_OUTLINE_NOT_CONFIRMED: "请先保存并确认大纲，再生成正文。",
  ARTICLE_OUTLINE_VERSION_CONFLICT: "大纲已被更新，请刷新页面后重新确认。",
  ARTICLE_PROVIDER_SCHEMA_INVALID: "生成的文章内容不完整，请重新生成。",
  ARTICLE_DEPTH_TARGET_NOT_MET: "文章未达到所选篇幅要求，本次额度已释放，请重新生成。",
  ARTICLE_LOCAL_SELECTION_REQUIRED: "请先在正文中选择需要优化的内容。",
  ARTICLE_PROVIDER_TIMEOUT: "文章生成时间较长，本次额度已释放，请重新生成。",
  ARTICLE_PROVIDER_RATE_LIMITED: "当前使用人数较多，本次额度已释放，请稍后重新生成。",
  ARTICLE_PROVIDER_TEMPORARY: "文章生成服务暂时不稳定，本次额度已释放，请重新生成。",
  ARTICLE_PROVIDER_REJECTED: "本次文章未能生成，额度已释放，请调整内容后重新生成。",
  ARTICLE_PROVIDER_UNAVAILABLE: "文章生成服务暂时不可用，请稍后重新生成。",
  ARTICLE_QUEUE_UNAVAILABLE: "文章生成服务暂时繁忙，请稍后重新生成。",
  ARTICLE_SOURCE_PACK_NOT_READY: "资料包尚未确认，请先完成资料确认。",
  ARTICLE_SUBJECT_NOT_READY: "当前主体资料尚未正式可用，请先保存主体资料。",
};

const ARTICLE_SOURCE_LABELS: Readonly<Record<string, string>> = {
  subject: "主体资料",
  document: "文件资料",
  web: "网页资料",
};

const ARTICLE_DEPTH_LABELS: Readonly<Record<Article["content_depth"], string>> = {
  concise: "简短（800～1200字）",
  standard: "标准（1500～2500字）",
  deep: "深度（3000～5000字）",
};

const ARTICLE_QUALITY_DIMENSION_LABELS: Readonly<Record<string, string>> = {
  subject_consistency: "主体信息一致性",
  factual_reliability: "事实可信度",
  topic_relevance: "主题相关度",
  structural_completeness: "结构完整度",
  readability: "阅读流畅度",
  keyword_naturalness: "关键词自然度",
};

const ARTICLE_QUALITY_GRADE_LABELS: Readonly<Record<string, string>> = {
  excellent: "优秀",
  good: "良好",
  fair: "尚可",
  optimization_recommended: "建议优化",
};

const PRIMARY_CHANNEL_KEYS = new Set(["general", "wechat", "baijiahao", "toutiao", "zhihu"]);

const CHANNEL_WRITING_GUIDES: Readonly<Record<string, string>> = {
  general: "适合官网、内容库和后续改编，表达专业自然，结构完整。",
  wechat: "采用自然导语和清晰分节，段落适合手机阅读，结尾完整收束。",
  baijiahao: "标题和主题清楚，重点信息便于搜索理解，事实表达具体。",
  toutiao: "开头直接进入主题，信息密度较高，段落简短，阅读节奏明快。",
  zhihu: "围绕问题展开，结论先行，重视分析过程、依据和可信表达。",
};

const EXPORT_LABELS: Readonly<Record<string, string>> = {
  word: "Word 文档",
  pdf: "PDF 文档",
  txt: "纯文本",
  markdown: "排版稿",
  html: "网页文件",
};

const ARTICLE_REVIEW_LABELS: Readonly<Record<Article["moderation_status"], string>> = {
  not_checked: "尚未审核",
  passed: "审核通过",
  manual_review: "待人工复核",
  rejected: "审核未通过",
};

const ARTICLE_JOB_STATUS_LABELS: Readonly<Record<ArticleJob["status"], string>> = {
  queued: "等待处理",
  running: "处理中",
  succeeded: "已完成",
  failed: "未完成",
};

const ARTICLE_OPERATION_LABELS: Readonly<Record<string, string>> = {
  outline: "大纲生成",
  body: "正文生成",
  quality: "质量复检",
  local_optimize: "局部优化",
  full_optimize: "全文优化",
  channel_adapt: "渠道稿生成",
};

const ARTICLE_QUOTA_LABELS: Readonly<Record<string, string>> = {
  article_credits: "文章额度",
  outline_regenerations: "大纲重生成额度",
  local_ai_edits: "局部优化额度",
  quality_rechecks: "质量复检额度",
};

const CHANNEL_ADAPTATION_STATUS_LABELS: Readonly<Record<ChannelAdaptation["status"], string>> = {
  queued: "等待生成",
  running: "生成中",
  ready: "已生成",
  failed: "生成未完成",
};

function textByCharacterRange(value: string, start: number, end: number): string {
  return Array.from(value).slice(start, end).join("");
}

function characterOffset(value: string, browserOffset: number): number {
  return Array.from(value.slice(0, browserOffset)).length;
}

function articleJobQuotaLabel(job: ArticleJob): string {
  if (!job.billing.quota_type) return "首次免费";
  const quota = ARTICLE_QUOTA_LABELS[job.billing.quota_type] ?? "相关额度";
  if (job.billing.consumed) return `${quota}已扣除`;
  if (job.billing.held) return `${quota}已预留`;
  return job.status === "failed" ? `${quota}未扣除` : `${quota}成功后扣除`;
}

function articleUserMessage(reason: unknown): string {
  let contentCode = "";
  if (typeof reason === "string") {
    contentCode = reason;
  } else if (reason instanceof AuthApiError) {
    const detailCode = reason.details.content_code;
    contentCode = typeof detailCode === "string" ? detailCode : reason.message;
  } else if (reason instanceof Error) {
    contentCode = reason.message;
  }

  if (ARTICLE_ERROR_MESSAGES[contentCode]) return ARTICLE_ERROR_MESSAGES[contentCode];
  if (contentCode.startsWith("ARTICLE_")) return "文章操作未完成，请稍后重新尝试。";
  return userMessage(reason);
}

export function replaceLatestJob(current: ArticleJob[], next: ArticleJob): ArticleJob[] {
  if (next.operation === "channel_adapt") {
    return [...current.filter((item) => item.id !== next.id), next];
  }
  return [...current.filter((item) => item.operation !== next.operation), next];
}

export default function ArticleWorkspace({ subjectId, initialTopic }: Props) {
  const [types, setTypes] = useState<ArticleType[]>([]);
  const [documents, setDocuments] = useState<DocumentOption[]>([]);
  const [webSources, setWebSources] = useState<Array<{ id: string; label: string }>>([]);
  const [channels, setChannels] = useState<PublishingChannel[]>([]);
  const [selectedType, setSelectedType] = useState("");
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [selectedWebSources, setSelectedWebSources] = useState<string[]>([]);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [selectedPrimaryChannel, setSelectedPrimaryChannel] = useState("");
  const [depth, setDepth] = useState<Article["content_depth"]>("standard");
  const [mode, setMode] = useState<"direct" | "outline">("outline");
  const [pack, setPack] = useState<SourcePack>();
  const [conflictValues, setConflictValues] = useState<Record<string, string>>({});
  const [article, setArticle] = useState<Article>();
  const [title, setTitle] = useState(initialTopic);
  const [content, setContent] = useState("");
  const [outline, setOutline] = useState("");
  const [jobs, setJobs] = useState<ArticleJob[]>([]);
  const [comparison, setComparison] = useState<{
    id: string;
    original: { title: string; content: string };
    optimized: { title: string; content: string };
  }>();
  const [adaptations, setAdaptations] = useState<ChannelAdaptation[]>([]);
  const [optimizationInstruction, setOptimizationInstruction] =
    useState("按质量建议提升表达与结构");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [jobError, setJobError] = useState<JobError>();
  const [notice, setNotice] = useState("");
  const [saveToLibrary, setSaveToLibrary] = useState(true);
  const [textSelection, setTextSelection] = useState({ start: 0, end: 0 });

  const applyArticle = useCallback((next: Article) => {
    setArticle(next);
    setTitle(next.title);
    setContent(next.content);
    setOutline(next.outline?.text ?? "");
  }, []);

  const loadCatalogs = useCallback(async () => {
    try {
      const [typeData, channelData, documentData, webData] = await Promise.all([
        getArticleTypes(),
        getPublishingChannels(),
        getSubjectDocuments(subjectId),
        listWebSources(subjectId),
      ]);
      const parsed = await Promise.all(
        documentData.documents.map(async (document) => ({
          document,
          result: await getDocumentParseResult(document.id),
        })),
      );
      setTypes(typeData.items);
      setSelectedType((current) => current || typeData.items[0]?.id || "");
      setChannels(channelData.items);
      setSelectedPrimaryChannel(
        (current) =>
          current ||
          channelData.items.find((item) => item.key === "general")?.id ||
          channelData.items.find((item) => PRIMARY_CHANNEL_KEYS.has(item.key))?.id ||
          "",
      );
      setDocuments(
        parsed.flatMap(({ document, result }) =>
          result.current_confirmed_version
            ? [{ ...document, confirmedSourceId: result.current_confirmed_version.id }]
            : [],
        ),
      );
      setWebSources(
        webData.results.flatMap((source) =>
          source.current_confirmed_version
            ? [{ id: source.current_confirmed_version.id, label: source.display_url }]
            : [],
        ),
      );
      setError("");
    } catch (reason) {
      setError(articleUserMessage(reason));
    }
  }, [subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadCatalogs(), 0);
    return () => window.clearTimeout(timer);
  }, [loadCatalogs]);

  useEffect(() => {
    const active = jobs.filter((job) => ["queued", "running"].includes(job.status));
    if (!active.length) return;
    const timer = window.setTimeout(async () => {
      try {
        const refreshed = await Promise.all(active.map((job) => getArticleJob(job.id)));
        setJobs((current) =>
          refreshed.reduce((latest, job) => replaceLatestJob(latest, job), current),
        );
        const completed = refreshed.filter((job) => ["succeeded", "failed"].includes(job.status));
        if (completed.length && article) {
          let refreshedArticle = await getArticle(article.id);
          const bodySucceeded = completed.some(
            (job) => job.operation === "body" && job.status === "succeeded",
          );
          if (bodySucceeded && saveToLibrary && refreshedArticle.content.trim()) {
            refreshedArticle = await saveArticleDraft(
              refreshedArticle,
              refreshedArticle.title,
              refreshedArticle.content,
            );
          }
          applyArticle(refreshedArticle);
          setAdaptations((await getChannelAdaptations(article.id)).items);
          const comparisonId = completed.find((job) => job.comparison_id)?.comparison_id;
          if (comparisonId) setComparison(await getComparison(comparisonId));
          const failed = completed.find((job) => job.status === "failed");
          if (failed) {
            setJobError({
              jobId: failed.id,
              operation: failed.operation,
              message: articleUserMessage(failed.safe_error_code),
            });
          } else {
            const succeededOperations = new Set(completed.map((job) => job.operation));
            setJobError((current) => {
              if (!current) return current;
              if (current.operation === "channel_adapt") {
                return completed.some(
                  (job) => job.id === current.jobId && job.status === "succeeded",
                )
                  ? undefined
                  : current;
              }
              return succeededOperations.has(current.operation) ? undefined : current;
            });
            if (bodySucceeded) {
              setNotice(
                saveToLibrary
                  ? "正文生成完成，已保存到内容库。"
                  : "正文生成完成。你可以编辑后点击“保存当前稿”加入内容库。",
              );
            }
          }
        }
      } catch (reason) {
        setError(articleUserMessage(reason));
      }
    }, ARTICLE_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [applyArticle, article, jobs, saveToLibrary]);

  const activeType = useMemo(
    () => types.find((item) => item.id === selectedType),
    [selectedType, types],
  );
  const primaryChannels = useMemo(
    () => channels.filter((item) => PRIMARY_CHANNEL_KEYS.has(item.key)),
    [channels],
  );
  const activePrimaryChannel = useMemo(
    () => channels.find((item) => item.id === selectedPrimaryChannel),
    [channels, selectedPrimaryChannel],
  );
  const selectedText = useMemo(() => {
    const { start, end } = textSelection;
    const characterLength = Array.from(content).length;
    if (start < 0 || end <= start || end > characterLength) return "";
    return textByCharacterRange(content, start, end);
  }, [content, textSelection]);
  const adaptationChannels = useMemo(
    () =>
      channels.filter((item) => item.key !== "general" && item.id !== article?.primary_channel?.id),
    [article?.primary_channel?.id, channels],
  );
  const hasActiveJob = jobs.some((job) => ["queued", "running"].includes(job.status));
  const outlineStatus = article?.outline?.status ?? "empty";
  const outlineIsGenerating = outlineStatus === "generating";
  const outlineNeedsConfirmation = outlineStatus === "ready";
  const outlineFailed = outlineStatus === "failed";
  const outlineFlowLocked = outlineIsGenerating || outlineNeedsConfirmation || outlineFailed;
  const outlineHasChanges = outline !== (article?.outline?.text ?? "");

  useEffect(() => {
    if (!article || !outlineIsGenerating || hasActiveJob) return;
    const timer = window.setTimeout(async () => {
      try {
        applyArticle(await getArticle(article.id));
      } catch (reason) {
        setError(articleUserMessage(reason));
      }
    }, ARTICLE_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [applyArticle, article, hasActiveJob, outlineIsGenerating]);

  const createDraft = async (confirmedPack: SourcePack) => {
    const created = await createArticle(subjectId, {
      article_type_id: selectedType,
      content_depth: depth,
      title,
      source_pack_id: confirmedPack.id,
      primary_channel_id: selectedPrimaryChannel,
    });
    applyArticle(created);
    setNotice("参考资料已确认，文章草稿已创建。只有主动生成正文才会使用文章额度。");
  };

  const preparePack = async () => {
    if (!selectedType) return;
    setBusy(true);
    setError("");
    try {
      const created = await createSourcePack(
        subjectId,
        selectedType,
        selectedDocuments,
        selectedWebSources,
      );
      setPack(created);
      if (!created.conflicts.length) {
        const confirmed = await confirmSourcePack(
          created,
          created.items.map((item) => item.id),
          [],
        );
        setPack(confirmed);
        await createDraft(confirmed);
      } else {
        setNotice("参考资料中存在关键信息冲突，请选择正确内容后再确认，系统不会自行猜测。");
      }
    } catch (reason) {
      setError(articleUserMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const resolvePack = async () => {
    if (!pack) return;
    if (pack.conflicts.some((conflict) => !conflictValues[conflict.key])) {
      setError("请为每个关键事实冲突选择一个来源事实");
      return;
    }
    setBusy(true);
    try {
      const confirmed = await confirmSourcePack(
        pack,
        pack.items.map((item) => item.id),
        pack.conflicts.map((conflict) => ({
          key: conflict.key,
          value: conflictValues[conflict.key],
        })),
      );
      setPack(confirmed);
      await createDraft(confirmed);
    } catch (reason) {
      setError(articleUserMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const submitJob = async (
    operation: string,
    factory: () => Promise<ArticleJob>,
    message: string,
  ) => {
    setBusy(true);
    setError("");
    setJobError((current) => (current?.operation === operation ? undefined : current));
    setNotice("");
    try {
      const job = await factory();
      setJobs((current) => replaceLatestJob(current, job));
      if (job.status === "failed") {
        setJobError({
          jobId: job.id,
          operation: job.operation,
          message: articleUserMessage(job.safe_error_code),
        });
      } else {
        setNotice(message);
      }
    } catch (reason) {
      setError(articleUserMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    if (!article) return;
    const currentOutlineStatus = article.outline?.status ?? "empty";
    if (currentOutlineStatus === "generating") {
      setError("大纲正在生成，请稍候。");
      return;
    }
    if (currentOutlineStatus === "ready") {
      setError("请先保存并确认大纲，再生成正文。");
      return;
    }
    if (currentOutlineStatus === "failed") {
      await submitJob(
        "outline",
        () => generateOutline(article.id),
        "正在重新生成大纲，完成后请确认内容。",
      );
      return;
    }
    if (mode === "outline" && currentOutlineStatus === "empty") {
      await submitJob(
        "outline",
        () => generateOutline(article.id),
        "首次大纲已提交，不消耗文章额度。确认后再生成正文。",
      );
      return;
    }
    await submitJob(
      "body",
      () => generateArticle(article.id),
      "正文已开始生成；成功后扣 1 个文章额度，未完成则不会扣除。",
    );
  };

  const confirmOutline = async () => {
    if (!article) return;
    if (!outline.trim()) {
      setError("大纲内容不能为空。");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const savedOutline = await saveOutline(article, outline, true);
      if (savedOutline.status !== "confirmed") {
        throw new Error("ARTICLE_OUTLINE_NOT_CONFIRMED");
      }
      applyArticle({
        ...article,
        outline: {
          text: savedOutline.text,
          status: savedOutline.status,
          generation_count: article.outline?.generation_count ?? 0,
          version: savedOutline.version,
        },
      });
      setError("");
      setNotice("大纲已确认，可以生成正文");
    } catch (reason) {
      setError(articleUserMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const persistCurrentDraft = async () => {
    if (!article) return undefined;
    let currentArticle = article;
    if (outline !== (article.outline?.text ?? "")) {
      await saveOutline(article, outline, false);
      currentArticle = await getArticle(article.id);
    }
    if (title !== currentArticle.title || content !== currentArticle.content) {
      currentArticle = await saveArticleDraft(currentArticle, title, content);
    }
    applyArticle(currentArticle);
    return currentArticle;
  };

  const saveDraft = async () => {
    if (!article) return false;
    setBusy(true);
    try {
      await persistCurrentDraft();
      setNotice("当前修改已保存到内容库。");
      return true;
    } catch (reason) {
      setError(articleUserMessage(reason));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const hasUnsavedArticleChanges = Boolean(
    article
      ? title !== article.title ||
          content !== article.content ||
          outline !== (article.outline?.text ?? "")
      : title.trim() || selectedDocuments.length || selectedWebSources.length,
  );
  useSubjectSwitchGuard(`article-workspace:${subjectId}`, hasUnsavedArticleChanges, saveDraft);

  const adapt = async () => {
    if (!article || !selectedChannels.length) return;
    setBusy(true);
    setError("");
    setJobError((current) => (current?.operation === "channel_adapt" ? undefined : current));
    try {
      const result = await createChannelAdaptations(article.id, selectedChannels);
      setJobs((current) => [...current, ...result.items.map((item) => item.job)]);
      setAdaptations(result.items);
      setNotice(
        `已提交 ${result.estimated_article_credits} 个独立渠道稿；每个成功稿扣 1 个文章额度。`,
      );
    } catch (reason) {
      setError(articleUserMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const optimize = async (mode: "local" | "full") => {
    if (!article) return;
    if (mode === "local" && !selectedText.trim()) {
      setError("请先在正文中选择需要优化的内容。");
      return;
    }
    await submitJob(
      mode === "local" ? "local_optimize" : "full_optimize",
      async () => {
        const currentArticle = await persistCurrentDraft();
        if (!currentArticle) throw new Error("ARTICLE_VERSION_CONFLICT");
        return optimizeArticle(
          currentArticle.id,
          mode,
          optimizationInstruction,
          mode === "local"
            ? { text: selectedText, start: textSelection.start, end: textSelection.end }
            : null,
        );
      },
      mode === "local"
        ? "已开始优化所选内容，完成后可对比并决定是否采用。"
        : "已开始优化整篇文章，完成后可对比并决定是否采用。",
    );
  };

  const exportArticle = async (format: string) => {
    if (!article) return;
    setBusy(true);
    setError("");
    try {
      const currentArticle = await persistCurrentDraft();
      if (!currentArticle) return;
      const result = await createArticleExport(currentArticle.id, format);
      const link = document.createElement("a");
      link.href = result.download_url;
      link.download = result.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setNotice(`${EXPORT_LABELS[format] ?? "文章文件"}已开始下载。`);
    } catch (reason) {
      setError(articleUserMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Space wrap align="baseline">
          <Typography.Title level={2}>文章生成</Typography.Title>
          <Link href={`/subjects/${subjectId}`}>返回主体</Link>
        </Space>
        <Alert
          type="info"
          showIcon
          title="文章只使用已确认的主体、文件和网页资料；不会把未核验内容作为可靠引用。"
        />
        {(error || jobError) && <Alert type="error" showIcon title={error || jobError?.message} />}
        {notice && <Alert type="success" showIcon title={notice} />}

        <Steps
          current={!pack ? 0 : !article ? 1 : article.status === "draft" ? 2 : 3}
          items={[
            { title: "选择渠道与资料" },
            { title: "确认参考资料" },
            { title: "生成与编辑" },
            { title: "保存与导出" },
          ]}
        />

        {!article && (
          <Card title="1. 发布渠道、文章类型与参考资料">
            <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Text strong>准备发布到哪里</Typography.Text>
              <Select
                aria-label="发布渠道"
                value={selectedPrimaryChannel || undefined}
                placeholder="选择文章的主要发布渠道"
                style={{ width: "100%" }}
                options={primaryChannels.map((item) => ({ value: item.id, label: item.name }))}
                onChange={setSelectedPrimaryChannel}
              />
              {activePrimaryChannel && (
                <Alert
                  type="info"
                  title={`${activePrimaryChannel.name}写作特点`}
                  description={
                    CHANNEL_WRITING_GUIDES[activePrimaryChannel.key] ??
                    "系统会按照所选平台的阅读习惯组织标题、段落和表达方式。"
                  }
                />
              )}
              <Typography.Text strong>选择文章类型</Typography.Text>
              <Select
                aria-label="文章类型"
                value={selectedType || undefined}
                style={{ width: "100%" }}
                options={types.map((item) => ({ value: item.id, label: item.name }))}
                onChange={setSelectedType}
              />
              {activeType && (
                <Alert
                  type="info"
                  title={activeType.description}
                  description={`可使用：${activeType.template_version.allowed_source_types
                    .map((source) => ARTICLE_SOURCE_LABELS[source] ?? "其他已确认资料")
                    .join(
                      "、",
                    )}；${activeType.template_version.citation_required ? "需要引用来源" : "可按需引用来源"}`}
                />
              )}
              <Input
                aria-label="文章主题"
                value={title}
                placeholder="输入文章主题"
                onChange={(event) => setTitle(event.target.value)}
              />
              <Radio.Group
                aria-label="内容深度"
                value={depth}
                options={[
                  { label: ARTICLE_DEPTH_LABELS.concise, value: "concise" },
                  { label: ARTICLE_DEPTH_LABELS.standard, value: "standard" },
                  { label: ARTICLE_DEPTH_LABELS.deep, value: "deep" },
                ]}
                onChange={(event) => setDepth(event.target.value)}
              />
              <Select
                aria-label="已确认文件资料"
                mode="multiple"
                value={selectedDocuments}
                placeholder="可选：已确认解析的主体文件"
                options={documents.map((item) => ({
                  value: item.confirmedSourceId,
                  label: item.display_name,
                }))}
                onChange={setSelectedDocuments}
              />
              <Select
                aria-label="已确认网页资料"
                mode="multiple"
                value={selectedWebSources}
                placeholder="可选：已确认解析的公开网页"
                options={webSources.map((item) => ({ value: item.id, label: item.label }))}
                onChange={setSelectedWebSources}
              />
              <Button
                type="primary"
                loading={busy}
                disabled={!selectedType || !selectedPrimaryChannel}
                onClick={preparePack}
              >
                核验并确认参考资料
              </Button>
              {pack?.conflicts.map((conflict, conflictIndex) => (
                <Card key={conflict.key} size="small" title={`待确认信息 ${conflictIndex + 1}`}>
                  <Radio.Group
                    value={conflictValues[conflict.key]}
                    options={conflict.options.map((option) => ({
                      value: option.value,
                      label: option.value,
                    }))}
                    onChange={(event) =>
                      setConflictValues((current) => ({
                        ...current,
                        [conflict.key]: event.target.value,
                      }))
                    }
                  />
                </Card>
              ))}
              {pack?.conflict_status === "pending" && (
                <Button type="primary" loading={busy} onClick={resolvePack}>
                  确认冲突选择并创建草稿
                </Button>
              )}
            </Space>
          </Card>
        )}

        {article && (
          <>
            <Card title="2. 大纲与正文生成">
              <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                <Space wrap>
                  <Tag color="blue">{article.article_type?.name ?? article.custom_type}</Tag>
                  <Tag>{ARTICLE_DEPTH_LABELS[article.content_depth]}</Tag>
                  <Tag color="purple">{article.primary_channel?.name ?? "通用型"}</Tag>
                  <Tag color={article.moderation_status === "passed" ? "green" : "orange"}>
                    {ARTICLE_REVIEW_LABELS[article.moderation_status]}
                  </Tag>
                  <Tag>当前编辑稿</Tag>
                </Space>
                <Radio.Group
                  value={mode}
                  options={[
                    { label: "先确认大纲", value: "outline" },
                    { label: "直接生成正文", value: "direct" },
                  ]}
                  onChange={(event) => setMode(event.target.value)}
                  disabled={busy || hasActiveJob || outlineFlowLocked}
                />
                {outlineIsGenerating && (
                  <Alert
                    type="info"
                    showIcon
                    message="大纲正在生成"
                    description="生成完成后即可编辑和确认，请勿重复提交。"
                  />
                )}
                {outlineFailed && (
                  <Alert
                    type="error"
                    showIcon
                    message="大纲生成未完成"
                    description="请重新生成大纲；在大纲生成并确认前不会开始生成正文。"
                  />
                )}
                {outlineNeedsConfirmation && (
                  <Alert
                    type="warning"
                    showIcon
                    message="请先保存并确认大纲"
                    description="确认成功后才会开放正文生成，不会提前扣除文章额度。"
                  />
                )}
                {(outlineNeedsConfirmation ||
                  (mode === "outline" && outlineStatus === "confirmed")) && (
                  <>
                    <Input.TextArea
                      aria-label="文章大纲"
                      rows={8}
                      value={outline}
                      onChange={(event) => setOutline(event.target.value)}
                    />
                    <Space wrap>
                      <Button
                        type="primary"
                        loading={busy}
                        onClick={() => void confirmOutline()}
                        disabled={
                          hasActiveJob ||
                          outlineIsGenerating ||
                          (outlineStatus === "confirmed" && !outlineHasChanges)
                        }
                      >
                        {outlineNeedsConfirmation ? "保存并确认大纲" : "保存大纲修改"}
                      </Button>
                      <Button
                        onClick={() =>
                          void submitJob(
                            "outline",
                            () => generateOutline(article.id),
                            "重新生成大纲已提交；成功后消耗一次大纲重生成次数。",
                          )
                        }
                        disabled={busy || hasActiveJob || outlineIsGenerating}
                      >
                        重新生成大纲
                      </Button>
                    </Space>
                  </>
                )}
                {!outlineNeedsConfirmation && (
                  <Space orientation="vertical" size="small">
                    <Checkbox
                      checked={saveToLibrary}
                      disabled={busy || hasActiveJob}
                      onChange={(event) => setSaveToLibrary(event.target.checked)}
                    >
                      正文生成成功后保存到内容库
                    </Checkbox>
                    <Button
                      type="primary"
                      loading={busy || hasActiveJob}
                      disabled={outlineIsGenerating}
                      onClick={generate}
                    >
                      {outlineIsGenerating
                        ? "正在生成大纲…"
                        : outlineFailed
                          ? "重新生成大纲"
                          : mode === "outline" && outlineStatus === "empty"
                            ? "生成首次免费大纲"
                            : "生成正文（成功扣 1 文章额度）"}
                    </Button>
                  </Space>
                )}
                {jobs.map((job) => (
                  <Tag key={job.id} color={job.status === "failed" ? "red" : "blue"}>
                    {ARTICLE_OPERATION_LABELS[job.operation] ?? "文章处理"} ·{" "}
                    {ARTICLE_JOB_STATUS_LABELS[job.status]} · {articleJobQuotaLabel(job)}
                  </Tag>
                ))}
              </Space>
            </Card>

            <Card title="3. 当前唯一稿与质量建议">
              <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                <Input value={title} onChange={(event) => setTitle(event.target.value)} />
                <Input.TextArea
                  aria-label="文章正文"
                  rows={18}
                  value={content}
                  onChange={(event) => {
                    setContent(event.target.value);
                    setTextSelection({ start: 0, end: 0 });
                  }}
                  onSelect={(event) =>
                    setTextSelection({
                      start: characterOffset(content, event.currentTarget.selectionStart),
                      end: characterOffset(content, event.currentTarget.selectionEnd),
                    })
                  }
                />
                <Space wrap>
                  <Button type="primary" onClick={() => void saveDraft()} disabled={hasActiveJob}>
                    保存当前稿
                  </Button>
                  <Button
                    onClick={() =>
                      void submitJob(
                        "quality",
                        () => recheckQuality(article.id),
                        "质量复检已提交；成功消耗一次质量复检次数。",
                      )
                    }
                    disabled={hasActiveJob || !content}
                  >
                    重新质量检测
                  </Button>
                </Space>
                {article.quality && (
                  <>
                    <Row gutter={[16, 16]}>
                      <Col xs={24} md={8}>
                        <Statistic
                          title="文章综合表现"
                          value={article.quality.total_score}
                          suffix={ARTICLE_QUALITY_GRADE_LABELS[article.quality.grade] ?? ""}
                        />
                      </Col>
                      {Object.entries(article.quality.dimensions).map(([key, value]) => (
                        <Col xs={12} md={8} key={key}>
                          <Statistic
                            title={ARTICLE_QUALITY_DIMENSION_LABELS[key] ?? "文章表现"}
                            value={value}
                          />
                        </Col>
                      ))}
                    </Row>
                    <List
                      header="改进建议"
                      dataSource={[...article.quality.suggestions]}
                      renderItem={(item) => <List.Item>{item}</List.Item>}
                    />
                  </>
                )}
              </Space>
            </Card>

            <Card title="4. 智能优化与版本对比">
              <Space orientation="vertical" style={{ width: "100%" }}>
                <Input
                  value={optimizationInstruction}
                  placeholder="例如：表达更自然，补充有依据的细节，适配当前发布渠道"
                  onChange={(event) => setOptimizationInstruction(event.target.value)}
                />
                <Alert
                  type={selectedText ? "success" : "info"}
                  showIcon
                  title={
                    selectedText
                      ? `已选择 ${selectedText.replace(/\s+/g, "").length} 字，可进行局部优化`
                      : "如需局部优化，请先在上方正文中选择一段内容"
                  }
                />
                <Space wrap>
                  <Button
                    onClick={() => void optimize("local")}
                    loading={busy}
                    disabled={busy || hasActiveJob || !selectedText.trim()}
                  >
                    优化所选内容
                  </Button>
                  <Button
                    onClick={() => void optimize("full")}
                    loading={busy}
                    disabled={busy || hasActiveJob}
                  >
                    整篇优化
                  </Button>
                </Space>
                {comparison && (
                  <Row gutter={[16, 16]}>
                    {(["original", "optimized"] as const).map((choice) => (
                      <Col xs={24} md={12} key={choice}>
                        <Card title={choice === "original" ? "原稿" : "优化稿"}>
                          <Typography.Title level={5}>{comparison[choice].title}</Typography.Title>
                          <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                            {comparison[choice].content}
                          </Typography.Paragraph>
                          <Button
                            type="primary"
                            onClick={async () => {
                              applyArticle(await chooseComparison(comparison.id, choice));
                              setComparison(undefined);
                            }}
                          >
                            保留此稿并丢弃另一稿
                          </Button>
                        </Card>
                      </Col>
                    ))}
                  </Row>
                )}
              </Space>
            </Card>

            <Card title="5. 保存与导出">
              <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                <Typography.Text type="secondary">
                  导出前会自动保存页面中的最新内容，下载文件使用当前文章标题命名。
                </Typography.Text>
                <Space wrap>
                  {(["word", "pdf", "txt", "markdown", "html"] as const).map((format) => (
                    <Button
                      key={format}
                      loading={busy}
                      disabled={hasActiveJob || article.moderation_status !== "passed"}
                      onClick={() => void exportArticle(format)}
                    >
                      导出{EXPORT_LABELS[format]}
                    </Button>
                  ))}
                </Space>
                {article.moderation_status !== "passed" && (
                  <Alert type="warning" showIcon title="文章审核通过后即可下载文件。" />
                )}
              </Space>
            </Card>

            <Card title="6. 生成其他平台版本">
              <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                <Typography.Text type="secondary">
                  当前文章已经按照{article.primary_channel?.name ?? "通用型"}
                  生成。如需发布到其他平台，可在这里生成独立版本。
                </Typography.Text>
                <Checkbox.Group
                  value={selectedChannels}
                  options={adaptationChannels.map((channel) => ({
                    value: channel.id,
                    label: `${channel.name}（使用 1 次文章额度）`,
                  }))}
                  onChange={(values) => setSelectedChannels(values as string[])}
                />
                <Button
                  type="primary"
                  disabled={!selectedChannels.length || article.moderation_status !== "passed"}
                  loading={busy || hasActiveJob}
                  onClick={() => void adapt()}
                >
                  批量生成 {selectedChannels.length} 个独立渠道稿
                </Button>
                <List
                  dataSource={adaptations}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Typography.Link
                          key={item.channel.official_url}
                          href={item.channel.official_url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          打开官方平台
                        </Typography.Link>,
                      ]}
                    >
                      <List.Item.Meta
                        title={`${item.channel.name} · ${CHANNEL_ADAPTATION_STATUS_LABELS[item.status]}`}
                        description={`${item.title || "生成中"} · 文章表现 ${item.quality_score ?? "-"} 分`}
                      />
                    </List.Item>
                  )}
                />
                <Alert type="info" title="这里仅生成适合对应平台的文章，不会代替用户登录或发布。" />
              </Space>
            </Card>
          </>
        )}
        {!types.length && !error && <Spin description="正在加载文章类型与已确认资料" />}
      </Space>
    </main>
  );
}
