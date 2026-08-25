"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
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
  checkPublication,
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
import { userMessage } from "@/lib/auth-client";
import {
  getDocumentParseResult,
  getSubjectDocuments,
  type SubjectDocument,
} from "@/lib/documents-client";
import { listWebSources } from "@/lib/web-sources-client";
import { ArticleImagesWorkspace } from "@/components/article-images-workspace";

export const ARTICLE_POLL_INTERVAL_MS = 1200;

type Props = Readonly<{ subjectId: string; initialTopic: string }>;
type DocumentOption = SubjectDocument & { confirmedSourceId: string };

export default function ArticleWorkspace({ subjectId, initialTopic }: Props) {
  const [types, setTypes] = useState<ArticleType[]>([]);
  const [documents, setDocuments] = useState<DocumentOption[]>([]);
  const [imageReferenceDocuments, setImageReferenceDocuments] = useState<
    Array<{ id: string; label: string }>
  >([]);
  const [webSources, setWebSources] = useState<Array<{ id: string; label: string }>>([]);
  const [channels, setChannels] = useState<PublishingChannel[]>([]);
  const [selectedType, setSelectedType] = useState("");
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [selectedWebSources, setSelectedWebSources] = useState<string[]>([]);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
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
  const [publicationUrl, setPublicationUrl] = useState("");
  const [publicationChannel, setPublicationChannel] = useState("");
  const [publicationResult, setPublicationResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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
      setDocuments(
        parsed.flatMap(({ document, result }) =>
          result.current_confirmed_version
            ? [{ ...document, confirmedSourceId: result.current_confirmed_version.id }]
            : [],
        ),
      );
      setImageReferenceDocuments(
        documentData.documents
          .filter((document) => ["jpeg", "png", "webp"].includes(document.detected_file_kind))
          .map((document) => ({
            id: document.document_version_id,
            label: `${document.display_name} · ${document.detected_file_kind.toUpperCase()}`,
          })),
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
      setError(userMessage(reason));
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
          current.map((job) => refreshed.find((item) => item.id === job.id) ?? job),
        );
        const completed = refreshed.filter((job) => ["succeeded", "failed"].includes(job.status));
        if (completed.length && article) {
          applyArticle(await getArticle(article.id));
          setAdaptations((await getChannelAdaptations(article.id)).items);
          const comparisonId = completed.find((job) => job.comparison_id)?.comparison_id;
          if (comparisonId) setComparison(await getComparison(comparisonId));
          const failed = completed.find((job) => job.status === "failed");
          if (failed) setError(`AI 任务失败：${failed.safe_error_code}`);
        }
      } catch (reason) {
        setError(userMessage(reason));
      }
    }, ARTICLE_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [applyArticle, article, jobs]);

  const activeType = useMemo(
    () => types.find((item) => item.id === selectedType),
    [selectedType, types],
  );
  const hasActiveJob = jobs.some((job) => ["queued", "running"].includes(job.status));

  const createDraft = async (confirmedPack: SourcePack) => {
    const created = await createArticle(subjectId, {
      article_type_id: selectedType,
      content_depth: depth,
      title,
      source_pack_id: confirmedPack.id,
    });
    applyArticle(created);
    setNotice("资料包已冻结并绑定文章草稿。仅主动生成正文时才进入文章额度。");
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
        setNotice("资料包检测到关键事实冲突，请选择后再确认。AI 不会自行猜测。");
      }
    } catch (reason) {
      setError(userMessage(reason));
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
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const submitJob = async (factory: () => Promise<ArticleJob>, message: string) => {
    setBusy(true);
    setError("");
    try {
      const job = await factory();
      setJobs((current) => [...current.filter((item) => item.id !== job.id), job]);
      setNotice(message);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    if (!article) return;
    if (mode === "outline" && article.outline?.status === "empty") {
      await submitJob(
        () => generateOutline(article.id),
        "首次大纲已提交，不消耗文章额度。确认后再生成正文。",
      );
      return;
    }
    await submitJob(
      () => generateArticle(article.id),
      "正文任务已提交；成功扣 1 个文章额度，provider/网络/结构失败自动释放。",
    );
  };

  const confirmOutline = async () => {
    if (!article) return;
    setBusy(true);
    try {
      await saveOutline(article, outline, true);
      applyArticle(await getArticle(article.id));
      setNotice("大纲已确认，可以生成正文");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const saveDraft = async () => {
    if (!article) return false;
    setBusy(true);
    try {
      let currentArticle = article;
      if (outline !== (article.outline?.text ?? "")) {
        await saveOutline(article, outline, false);
        currentArticle = await getArticle(article.id);
      }
      applyArticle(await saveArticleDraft(currentArticle, title, content));
      setNotice("当前唯一稿已自动保存；AI 原始生成事实未被修改");
      return true;
    } catch (reason) {
      setError(userMessage(reason));
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
    try {
      const result = await createChannelAdaptations(article.id, selectedChannels);
      setJobs((current) => [...current, ...result.items.map((item) => item.job)]);
      setAdaptations(result.items);
      setNotice(
        `已提交 ${result.estimated_article_credits} 个独立渠道稿；每个成功稿扣 1 个文章额度。`,
      );
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const exportArticle = async (format: string) => {
    if (!article) return;
    try {
      const result = await createArticleExport(article.id, format);
      window.location.assign(result.download_url);
    } catch (reason) {
      setError(userMessage(reason));
    }
  };

  const runPublicationCheck = async () => {
    if (!article || !publicationChannel || !publicationUrl) return;
    setBusy(true);
    try {
      const result = await checkPublication(
        subjectId,
        article.id,
        publicationChannel,
        publicationUrl,
      );
      setPublicationResult(`${result.result}：${result.match_summary}`);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Space wrap align="baseline">
          <Typography.Title level={2}>GEO 内容生成与分发</Typography.Title>
          <Link href={`/subjects/${subjectId}`}>返回主体</Link>
        </Space>
        <Alert
          type="info"
          showIcon
          title="文章只使用已确认并冻结的主体、文件和网页资料；不会把未核验互联网内容伪装成引用。"
        />
        {error && <Alert type="error" showIcon title={error} />}
        {notice && <Alert type="success" showIcon title={notice} />}

        <Steps
          current={!pack ? 0 : !article ? 1 : article.status === "draft" ? 2 : 3}
          items={[
            { title: "选择资料" },
            { title: "冻结资料包" },
            { title: "生成与编辑" },
            { title: "分发与检测" },
          ]}
        />

        {!article && (
          <Card title="1. 类型、模板与资料包">
            <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
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
                  title={`${activeType.description} · 模板 v${activeType.template_version.version_no}`}
                  description={`来源范围：${activeType.template_version.allowed_source_types.join("、")}；引用${activeType.template_version.citation_required ? "必需" : "可选"}`}
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
                  { label: "简洁", value: "concise" },
                  { label: "标准", value: "standard" },
                  { label: "深度", value: "deep" },
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
              <Button type="primary" loading={busy} disabled={!selectedType} onClick={preparePack}>
                核验并冻结资料包
              </Button>
              {pack?.conflicts.map((conflict) => (
                <Card key={conflict.key} size="small" title={`冲突事实：${conflict.key}`}>
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
                  <Tag>{article.content_depth}</Tag>
                  <Tag color={article.moderation_status === "passed" ? "green" : "orange"}>
                    审核 {article.moderation_status}
                  </Tag>
                  <Tag>当前稿 v{article.version}</Tag>
                </Space>
                <Radio.Group
                  value={mode}
                  options={[
                    { label: "先确认大纲", value: "outline" },
                    { label: "直接生成正文", value: "direct" },
                  ]}
                  onChange={(event) => setMode(event.target.value)}
                />
                {mode === "outline" && article.outline?.status !== "empty" && (
                  <>
                    <Input.TextArea
                      aria-label="文章大纲"
                      rows={8}
                      value={outline}
                      onChange={(event) => setOutline(event.target.value)}
                    />
                    <Space wrap>
                      <Button onClick={() => void confirmOutline()} disabled={hasActiveJob}>
                        保存并确认大纲
                      </Button>
                      <Button
                        onClick={() =>
                          void submitJob(
                            () => generateOutline(article.id),
                            "重新生成大纲已提交；成功后消耗一次大纲重生成次数。",
                          )
                        }
                        disabled={hasActiveJob}
                      >
                        重新生成大纲
                      </Button>
                    </Space>
                  </>
                )}
                <Button type="primary" loading={busy || hasActiveJob} onClick={generate}>
                  {mode === "outline" && article.outline?.status === "empty"
                    ? "生成首次免费大纲"
                    : "生成正文（成功扣 1 文章额度）"}
                </Button>
                {jobs.map((job) => (
                  <Tag key={job.id} color={job.status === "failed" ? "red" : "blue"}>
                    {job.operation} · {job.status} · {job.billing.quota_type ?? "首次免费"}
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
                  onChange={(event) => setContent(event.target.value)}
                />
                <Space wrap>
                  <Button type="primary" onClick={() => void saveDraft()} disabled={hasActiveJob}>
                    保存当前稿
                  </Button>
                  <Button
                    onClick={() =>
                      void submitJob(
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
                          title="文章质量（仅建议）"
                          value={article.quality.total_score}
                          suffix={article.quality.grade}
                        />
                      </Col>
                      {Object.entries(article.quality.dimensions).map(([key, value]) => (
                        <Col xs={12} md={8} key={key}>
                          <Statistic
                            title={`${key} · 权重 ${article.quality?.weights[key]}%`}
                            value={value}
                          />
                        </Col>
                      ))}
                    </Row>
                    <List
                      header="修改建议（低分不阻止导出或分发）"
                      dataSource={[...article.quality.suggestions]}
                      renderItem={(item) => <List.Item>{item}</List.Item>}
                    />
                  </>
                )}
              </Space>
            </Card>

            <Card title="4. 临时优化对比">
              <Space orientation="vertical" style={{ width: "100%" }}>
                <Input
                  value={optimizationInstruction}
                  onChange={(event) => setOptimizationInstruction(event.target.value)}
                />
                <Space wrap>
                  <Button
                    onClick={() =>
                      void submitJob(
                        () => optimizeArticle(article.id, "local", optimizationInstruction),
                        "局部优化已提交；成功消耗一次局部 AI 修改次数。",
                      )
                    }
                    disabled={hasActiveJob}
                  >
                    局部优化
                  </Button>
                  <Button
                    onClick={() =>
                      void submitJob(
                        () => optimizeArticle(article.id, "full", optimizationInstruction),
                        "整篇优化已提交；成功扣 1 个文章额度。",
                      )
                    }
                    disabled={hasActiveJob}
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

            <Card title="5. 导出、渠道适配与发布链接即时检测">
              <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                <Space wrap>
                  {(["word", "pdf", "txt", "markdown", "html"] as const).map((format) => (
                    <Button key={format} onClick={() => void exportArticle(format)}>
                      导出 {format.toUpperCase()}
                    </Button>
                  ))}
                </Space>
                <Divider />
                <Checkbox.Group
                  value={selectedChannels}
                  options={channels.map((channel) => ({
                    value: channel.id,
                    label: `${channel.name}（1 文章额度）`,
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
                        title={`${item.channel.name} · ${item.status}`}
                        description={`${item.title || "生成中"} · 质量 ${item.quality_score ?? "-"}`}
                      />
                    </List.Item>
                  )}
                />
                <Alert type="info" title="系统不代替登录或发布，也不会把适配稿标记为已发布。" />
                <Select
                  value={publicationChannel || undefined}
                  placeholder="选择已发布渠道"
                  options={channels.map((channel) => ({
                    value: channel.id,
                    label: channel.name,
                  }))}
                  onChange={setPublicationChannel}
                />
                <Input
                  value={publicationUrl}
                  placeholder="粘贴公开发布链接"
                  onChange={(event) => setPublicationUrl(event.target.value)}
                />
                <Button loading={busy} onClick={() => void runPublicationCheck()}>
                  立即检测一次
                </Button>
                {publicationResult && <Alert type="info" title={publicationResult} />}
              </Space>
            </Card>
          </>
        )}
        {article && (
          <ArticleImagesWorkspace
            subjectId={subjectId}
            articleId={article.id}
            articleTitle={article.title || title}
            referenceDocuments={imageReferenceDocuments}
          />
        )}

        {!types.length && !error && <Spin description="正在加载文章类型与已确认资料" />}
      </Space>
    </main>
  );
}
