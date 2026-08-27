"use client";

import {
  CopyOutlined,
  ReloadOutlined,
  SaveOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Input,
  InputNumber,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useSubjectSwitchGuard } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getDocumentParseResult,
  getSubjectDocuments,
  type SubjectDocument,
} from "@/lib/documents-client";
import { listWebSources } from "@/lib/web-sources-client";
import {
  createVideoScript,
  generateVideoScript,
  getVideoArticleOptions,
  getVideoScript,
  getVideoScriptJob,
  saveVideoScript,
  type VideoArticleOption,
  type VideoPlatform,
  type VideoScript,
  type VideoScriptContent,
  type VideoScriptJob,
  type VideoScriptScene,
  type VideoSourceMode,
  type VideoStyle,
  type VideoType,
} from "@/lib/video-scripts-client";

const { Text, Title } = Typography;
const POLL_INTERVAL_MS = 1200;

type Props = Readonly<{
  subjectId: string;
  initialTopic: string;
  initialSourceArticleId: string;
}>;

type DocumentOption = SubjectDocument & { confirmedSourceId: string };
type EditableScript = {
  hooks: string[];
  scenes: Array<{
    scene: number;
    start: number;
    end: number;
    visual: string;
    voiceover: string;
    subtitle: string;
  }>;
  full_voiceover: string;
  cta: string;
};

const platformOptions: Array<{ value: VideoPlatform; label: string }> = [
  { value: "douyin", label: "抖音" },
  { value: "wechat_channels", label: "视频号" },
  { value: "xiaohongshu", label: "小红书" },
  { value: "bilibili", label: "B站" },
  { value: "general", label: "通用" },
];

const typeOptions: Array<{ value: VideoType; label: string }> = [
  { value: "talking_head", label: "口播" },
  { value: "brand", label: "品牌介绍" },
  { value: "product", label: "产品介绍" },
  { value: "knowledge", label: "知识科普" },
  { value: "case", label: "案例分享" },
];

const styleOptions: Array<{ value: VideoStyle; label: string }> = [
  { value: "professional", label: "专业" },
  { value: "natural", label: "自然" },
  { value: "emotional", label: "情绪化" },
  { value: "conversion", label: "高转化" },
  { value: "knowledge", label: "知识型" },
];

const sourceOptions: Array<{ value: VideoSourceMode; label: string }> = [
  { value: "subject", label: "根据主体资料生成" },
  { value: "article", label: "根据已有文章改编" },
  { value: "custom", label: "自定义主题生成" },
];

function labelFor<T extends string>(options: Array<{ value: T; label: string }>, value: T) {
  return options.find((item) => item.value === value)?.label ?? value;
}

function cloneScript(script: VideoScriptContent | null): EditableScript | null {
  if (!script) return null;
  return {
    hooks: [...script.hooks],
    scenes: script.scenes.map((scene) => ({ ...scene })),
    full_voiceover: script.full_voiceover,
    cta: script.cta,
  };
}

function copyText(title: string, script: EditableScript) {
  const sceneText = script.scenes
    .map(
      (scene) =>
        `镜头 ${scene.scene}（${scene.start}-${scene.end}秒）\n画面：${scene.visual}\n口播：${scene.voiceover}\n屏幕文字：${scene.subtitle}`,
    )
    .join("\n\n");
  return [
    `视频标题：${title}`,
    "",
    "开场钩子：",
    ...script.hooks.map((hook, index) => `${index + 1}. ${hook}`),
    "",
    "分镜脚本：",
    sceneText,
    "",
    "完整口播稿：",
    script.full_voiceover,
    "",
    `结尾 CTA：${script.cta}`,
  ].join("\n");
}

export default function VideoScriptWorkspace({
  subjectId,
  initialTopic,
  initialSourceArticleId,
}: Props) {
  const [documents, setDocuments] = useState<DocumentOption[]>([]);
  const [webSources, setWebSources] = useState<Array<{ id: string; label: string }>>([]);
  const [articles, setArticles] = useState<VideoArticleOption[]>([]);
  const [platform, setPlatform] = useState<VideoPlatform>("douyin");
  const [videoType, setVideoType] = useState<VideoType>("talking_head");
  const [durationSeconds, setDurationSeconds] = useState(30);
  const [style, setStyle] = useState<VideoStyle>("professional");
  const [sourceMode, setSourceMode] = useState<VideoSourceMode>(
    initialSourceArticleId ? "article" : "subject",
  );
  const [topic, setTopic] = useState(initialTopic);
  const [sourceArticleId, setSourceArticleId] = useState(initialSourceArticleId);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [selectedWebSources, setSelectedWebSources] = useState<string[]>([]);
  const [video, setVideo] = useState<VideoScript>();
  const [job, setJob] = useState<VideoScriptJob>();
  const [draftTitle, setDraftTitle] = useState("");
  const [draftScript, setDraftScript] = useState<EditableScript | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const applyVideo = useCallback((next: VideoScript) => {
    setVideo(next);
    setDraftTitle(next.title);
    setDraftScript(cloneScript(next.script));
  }, []);

  const loadCatalogs = useCallback(async () => {
    try {
      const [documentData, webData, articleData] = await Promise.all([
        getSubjectDocuments(subjectId),
        listWebSources(subjectId),
        getVideoArticleOptions(subjectId),
      ]);
      const parsed = await Promise.all(
        documentData.documents.map(async (document) => ({
          document,
          result: await getDocumentParseResult(document.id),
        })),
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
      setArticles(articleData.items);
      if (initialSourceArticleId) {
        const selected = articleData.items.find((item) => item.id === initialSourceArticleId);
        if (selected) setTopic((current) => current || selected.title);
      }
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [initialSourceArticleId, subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadCatalogs(), 0);
    return () => window.clearTimeout(timer);
  }, [loadCatalogs]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const refreshed = await getVideoScriptJob(job.id);
        setJob(refreshed);
        if (refreshed.status === "succeeded") {
          applyVideo(await getVideoScript(refreshed.article_id));
          setNotice("视频脚本已生成，可直接编辑、复制或重新生成。");
        } else if (refreshed.status === "failed") {
          setError("视频脚本生成失败，请重新生成。");
        }
      } catch (reason) {
        setError(userMessage(reason));
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [applyVideo, job]);

  const isGenerating = Boolean(job && ["queued", "running"].includes(job.status));
  const hasUnsavedChanges = useMemo(() => {
    if (!video?.script || !draftScript) return false;
    return draftTitle !== video.title || JSON.stringify(draftScript) !== JSON.stringify(video.script);
  }, [draftScript, draftTitle, video]);

  const saveDraft = useCallback(async () => {
    if (!video || !draftScript) return true;
    setBusy(true);
    setError("");
    try {
      const saved = await saveVideoScript(video, {
        title: draftTitle,
        hooks: draftScript.hooks,
        scenes: draftScript.scenes,
        full_voiceover: draftScript.full_voiceover,
        cta: draftScript.cta,
      });
      applyVideo(saved);
      setNotice("脚本修改已保存。");
      return true;
    } catch (reason) {
      setError(userMessage(reason));
      return false;
    } finally {
      setBusy(false);
    }
  }, [applyVideo, draftScript, draftTitle, video]);

  useSubjectSwitchGuard(`video-script-workspace:${subjectId}`, hasUnsavedChanges, saveDraft);

  const submitInitialGeneration = async () => {
    if (sourceMode === "article" && !sourceArticleId) {
      setError("请选择一篇已有文章。");
      return;
    }
    if (sourceMode !== "article" && !topic.trim()) {
      setError("请输入视频主题。");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const created = await createVideoScript(subjectId, {
        platform,
        video_type: videoType,
        duration_seconds: durationSeconds,
        style,
        source_mode: sourceMode,
        topic,
        document_source_ids: selectedDocuments,
        web_source_ids: selectedWebSources,
        source_article_id: sourceMode === "article" ? sourceArticleId || null : null,
      });
      applyVideo(created);
      const nextJob = await generateVideoScript(created.id);
      setJob(nextJob);
      setNotice("生成任务已提交；成功后计入 1 次内容生成额度，生成失败不会扣减。");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    if (!video) return;
    setBusy(true);
    setError("");
    try {
      const nextJob = await generateVideoScript(video.id);
      setJob(nextJob);
      setNotice("正在按当前设置重新生成视频脚本。");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const copyScript = async () => {
    if (!draftScript) return;
    try {
      await navigator.clipboard.writeText(copyText(draftTitle, draftScript));
      setNotice("脚本已复制到剪贴板。");
    } catch {
      setError("复制失败，请手动复制。");
    }
  };

  const resetWorkspace = () => {
    setVideo(undefined);
    setJob(undefined);
    setDraftTitle("");
    setDraftScript(null);
    setError("");
    setNotice("");
  };

  const updateHook = (index: number, value: string) => {
    setDraftScript((current) => {
      if (!current) return current;
      const hooks = [...current.hooks];
      hooks[index] = value;
      return { ...current, hooks };
    });
  };

  const updateScene = (index: number, patch: Partial<VideoScriptScene>) => {
    setDraftScript((current) => {
      if (!current) return current;
      return {
        ...current,
        scenes: current.scenes.map((scene, sceneIndex) =>
          sceneIndex === index ? { ...scene, ...patch } : scene,
        ),
      };
    });
  };

  const step = !video ? 0 : !video.script ? 1 : 2;

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Space wrap align="baseline">
          <Title level={2}>视频脚本生成</Title>
          <Link href={`/subjects/${subjectId}`}>返回主体</Link>
        </Space>

        <Alert
          type="info"
          showIcon
          title="脚本只使用当前主体、你选择的已确认资料和已有文章；AI 不会把未核验信息写成事实。"
        />
        {error && <Alert type="error" showIcon title={error} />}
        {notice && <Alert type="success" showIcon title={notice} />}

        <Steps
          current={step}
          items={[{ title: "视频设置" }, { title: "AI 生成" }, { title: "编辑与保存" }]}
        />

        {!video && (
          <Card title="1. 视频设置">
            <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
              <Row gutter={[16, 16]}>
                <Col xs={24} md={12} xl={6}>
                  <Text strong>视频平台</Text>
                  <Select
                    aria-label="视频平台"
                    value={platform}
                    options={platformOptions}
                    style={{ width: "100%", marginTop: 8 }}
                    onChange={setPlatform}
                  />
                </Col>
                <Col xs={24} md={12} xl={6}>
                  <Text strong>视频类型</Text>
                  <Select
                    aria-label="视频类型"
                    value={videoType}
                    options={typeOptions}
                    style={{ width: "100%", marginTop: 8 }}
                    onChange={setVideoType}
                  />
                </Col>
                <Col xs={24} md={12} xl={6}>
                  <Text strong>视频时长</Text>
                  <InputNumber
                    aria-label="视频时长"
                    min={10}
                    max={180}
                    value={durationSeconds}
                    addonAfter="秒"
                    style={{ width: "100%", marginTop: 8 }}
                    onChange={(value) => setDurationSeconds(Number(value || 30))}
                  />
                </Col>
                <Col xs={24} md={12} xl={6}>
                  <Text strong>表达风格</Text>
                  <Select
                    aria-label="表达风格"
                    value={style}
                    options={styleOptions}
                    style={{ width: "100%", marginTop: 8 }}
                    onChange={setStyle}
                  />
                </Col>
              </Row>

              <Divider />
              <Text strong>生成来源</Text>
              <Radio.Group
                aria-label="生成来源"
                value={sourceMode}
                options={sourceOptions}
                onChange={(event) => setSourceMode(event.target.value)}
              />

              {sourceMode === "article" && (
                <Select
                  aria-label="已有文章"
                  showSearch
                  optionFilterProp="label"
                  value={sourceArticleId || undefined}
                  placeholder="选择一篇已有文章"
                  style={{ width: "100%" }}
                  options={articles.map((article) => ({
                    value: article.id,
                    label: article.title,
                  }))}
                  onChange={(value) => {
                    setSourceArticleId(value);
                    const selected = articles.find((article) => article.id === value);
                    if (selected && !topic.trim()) setTopic(selected.title);
                  }}
                />
              )}

              <Input
                aria-label="视频主题"
                value={topic}
                placeholder={
                  sourceMode === "article"
                    ? "视频主题（可留空，默认使用文章标题）"
                    : "输入视频主题，例如：为什么企业需要做 GEO 优化"
                }
                onChange={(event) => setTopic(event.target.value)}
              />

              <Row gutter={[16, 16]}>
                <Col xs={24} md={12}>
                  <Text strong>补充文件（可选）</Text>
                  <Select
                    aria-label="补充文件"
                    mode="multiple"
                    allowClear
                    value={selectedDocuments}
                    placeholder="选择已确认文件"
                    style={{ width: "100%", marginTop: 8 }}
                    options={documents.map((document) => ({
                      value: document.confirmedSourceId,
                      label: document.display_name,
                    }))}
                    onChange={setSelectedDocuments}
                  />
                </Col>
                <Col xs={24} md={12}>
                  <Text strong>补充网页（可选）</Text>
                  <Select
                    aria-label="补充网页"
                    mode="multiple"
                    allowClear
                    value={selectedWebSources}
                    placeholder="选择已确认网页"
                    style={{ width: "100%", marginTop: 8 }}
                    options={webSources.map((source) => ({
                      value: source.id,
                      label: source.label,
                    }))}
                    onChange={setSelectedWebSources}
                  />
                </Col>
              </Row>

              <Space wrap>
                <Button
                  type="primary"
                  icon={<VideoCameraOutlined />}
                  loading={busy}
                  onClick={() => void submitInitialGeneration()}
                >
                  生成视频脚本
                </Button>
                <Text type="secondary">
                  建议时长 15-90 秒；首次先生成完整分镜，再按需要编辑。
                </Text>
              </Space>
            </Space>
          </Card>
        )}

        {video && (
          <Card
            title="2. AI 视频脚本"
            extra={
              <Button type="link" onClick={resetWorkspace}>
                新建脚本
              </Button>
            }
          >
            <Space orientation="vertical" size="large" style={{ width: "100%" }}>
              <Space wrap>
                <Tag color="blue">{labelFor(platformOptions, video.config.platform)}</Tag>
                <Tag>{labelFor(typeOptions, video.config.video_type)}</Tag>
                <Tag>{video.config.duration_seconds} 秒</Tag>
                <Tag>{labelFor(styleOptions, video.config.style)}</Tag>
                <Tag>已冻结 {video.source_summary.item_count} 项资料</Tag>
              </Space>

              {isGenerating && (
                <Alert
                  type="info"
                  showIcon
                  title="正在生成视频脚本"
                  description={
                    <Space>
                      <Spin size="small" />
                      <span>正在生成标题、3 个开场钩子、分镜、完整口播稿和 CTA。</span>
                    </Space>
                  }
                />
              )}

              {draftScript && (
                <>
                  <div>
                    <Text strong>视频标题</Text>
                    <Input
                      aria-label="视频标题"
                      value={draftTitle}
                      style={{ marginTop: 8 }}
                      onChange={(event) => setDraftTitle(event.target.value)}
                    />
                  </div>

                  <div>
                    <Title level={4}>开场钩子</Title>
                    <Text type="secondary">AI 一次给出 3 个前 3 秒开场，可直接挑选或修改。</Text>
                    <Space orientation="vertical" size="small" style={{ width: "100%", marginTop: 12 }}>
                      {draftScript.hooks.map((hook, index) => (
                        <Input
                          key={`hook-${index}`}
                          aria-label={`开场钩子 ${index + 1}`}
                          addonBefore={`${index + 1}`}
                          value={hook}
                          onChange={(event) => updateHook(index, event.target.value)}
                        />
                      ))}
                    </Space>
                  </div>

                  <Divider />
                  <div>
                    <Title level={4}>分镜脚本</Title>
                    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                      {draftScript.scenes.map((scene, index) => (
                        <Card
                          size="small"
                          key={`scene-${scene.scene}`}
                          title={`镜头 ${scene.scene} · ${scene.start}-${scene.end} 秒`}
                        >
                          <Row gutter={[16, 12]}>
                            <Col xs={24} lg={8}>
                              <Text strong>画面</Text>
                              <Input.TextArea
                                aria-label={`镜头 ${scene.scene} 画面`}
                                rows={4}
                                value={scene.visual}
                                style={{ marginTop: 8 }}
                                onChange={(event) =>
                                  updateScene(index, { visual: event.target.value })
                                }
                              />
                            </Col>
                            <Col xs={24} lg={10}>
                              <Text strong>口播</Text>
                              <Input.TextArea
                                aria-label={`镜头 ${scene.scene} 口播`}
                                rows={4}
                                value={scene.voiceover}
                                style={{ marginTop: 8 }}
                                onChange={(event) =>
                                  updateScene(index, { voiceover: event.target.value })
                                }
                              />
                            </Col>
                            <Col xs={24} lg={6}>
                              <Text strong>屏幕文字</Text>
                              <Input.TextArea
                                aria-label={`镜头 ${scene.scene} 屏幕文字`}
                                rows={4}
                                value={scene.subtitle}
                                style={{ marginTop: 8 }}
                                onChange={(event) =>
                                  updateScene(index, { subtitle: event.target.value })
                                }
                              />
                            </Col>
                          </Row>
                        </Card>
                      ))}
                    </Space>
                  </div>

                  <Divider />
                  <div>
                    <Title level={4}>完整口播稿</Title>
                    <Input.TextArea
                      aria-label="完整口播稿"
                      rows={9}
                      value={draftScript.full_voiceover}
                      onChange={(event) =>
                        setDraftScript((current) =>
                          current ? { ...current, full_voiceover: event.target.value } : current,
                        )
                      }
                    />
                  </div>

                  <div>
                    <Title level={4}>结尾 CTA</Title>
                    <Input
                      aria-label="结尾 CTA"
                      value={draftScript.cta}
                      onChange={(event) =>
                        setDraftScript((current) =>
                          current ? { ...current, cta: event.target.value } : current,
                        )
                      }
                    />
                  </div>

                  <Space wrap>
                    <Button
                      type="primary"
                      icon={<SaveOutlined />}
                      loading={busy}
                      disabled={!hasUnsavedChanges}
                      onClick={() => void saveDraft()}
                    >
                      保存修改
                    </Button>
                    <Button
                      icon={<ReloadOutlined />}
                      loading={busy || isGenerating}
                      disabled={isGenerating}
                      onClick={() => void regenerate()}
                    >
                      重新生成
                    </Button>
                    <Button icon={<CopyOutlined />} onClick={() => void copyScript()}>
                      复制脚本
                    </Button>
                  </Space>
                </>
              )}
            </Space>
          </Card>
        )}
      </Space>
    </main>
  );
}
