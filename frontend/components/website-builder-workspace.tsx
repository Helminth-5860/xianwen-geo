"use client";

import {
  CheckOutlined,
  CloudUploadOutlined,
  PictureOutlined,
  ReloadOutlined,
  RocketOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Empty, Skeleton, Space, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { WebsiteDesignSelector } from "@/components/website-design-selector";
import { WebsiteDraftPreview, type WebsitePreviewImage } from "@/components/website-draft-preview";
import { userMessage } from "@/lib/auth-client";
import {
  completeUploadIntent,
  createUploadIntent,
  getSubjectDocuments,
  getUploadIntent,
  newUploadIdempotencyKey,
  uploadDirect,
  type SubjectDocument,
} from "@/lib/documents-client";
import { getSubjectImages, type ImageAsset } from "@/lib/images-client";
import {
  generateWebsite,
  getWebsiteDocumentUrl,
  getWebsiteJob,
  getWebsiteState,
  updateWebsiteDesign,
  type WebsiteDensityKey,
  type WebsiteJob,
  type WebsiteProject,
  type WebsiteState,
  type WebsiteStyleKey,
  type WebsiteThemeKey,
} from "@/lib/websites-client";

import styles from "./website-builder-workspace.module.css";

const MAX_MATERIALS = 12;
const IMAGE_KINDS = new Set(["jpeg", "jpg", "png", "webp"]);
const RUNNING_JOB_STATUSES = new Set<WebsiteJob["status"]>(["queued", "running"]);

type DocumentMaterial = Readonly<{
  document: SubjectDocument;
  previewUrl: string | null;
}>;

const sleep = (milliseconds: number) =>
  new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));

async function waitForUpload(intentId: string) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const intent = await getUploadIntent(intentId);
    if (intent.status === "completed") return intent;
    if (intent.status === "rejected" || intent.status === "expired") {
      throw new Error("图片未能保存，请重新上传");
    }
    await sleep(1000);
  }
  throw new Error("图片仍在处理中，请稍后刷新页面查看");
}

export function WebsiteBuilderWorkspace() {
  const { currentSubject, loading: subjectLoading } = useSubjectWorkspace();
  const [messageApi, messageHolder] = message.useMessage();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const initializedSubjectRef = useRef<string | null>(null);

  const [state, setState] = useState<WebsiteState | null>(null);
  const [images, setImages] = useState<ImageAsset[]>([]);
  const [documents, setDocuments] = useState<DocumentMaterial[]>([]);
  const [styleKey, setStyleKey] = useState<WebsiteStyleKey>("professional");
  const [themeKey, setThemeKey] = useState<WebsiteThemeKey>("ocean");
  const [densityKey, setDensityKey] = useState<WebsiteDensityKey>("standard");
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [activeJob, setActiveJob] = useState<WebsiteJob | null>(null);
  const [project, setProject] = useState<WebsiteProject | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [generating, setGenerating] = useState(false);
  const [savingDesign, setSavingDesign] = useState(false);

  const loadDocumentMaterials = useCallback(async (subjectId: string) => {
    const { documents: rows } = await getSubjectDocuments(subjectId);
    const imageRows = rows.filter((document) => IMAGE_KINDS.has(document.detected_file_kind));
    const signed = await Promise.allSettled(
      imageRows.slice(0, 24).map(async (document) => {
        const value = await getWebsiteDocumentUrl(document.id);
        return { document, previewUrl: value.url } satisfies DocumentMaterial;
      }),
    );
    return signed.flatMap((result) => (result.status === "fulfilled" ? [result.value] : []));
  }, []);

  const loadWorkspace = useCallback(
    async (subjectId: string) => {
      setLoading(true);
      setError("");
      try {
        const [website, imageResponse, documentMaterials] = await Promise.all([
          getWebsiteState(subjectId),
          getSubjectImages(subjectId, true),
          loadDocumentMaterials(subjectId),
        ]);
        setState(website);
        setImages(imageResponse.results.filter((image) => Boolean(image.url)));
        setDocuments(documentMaterials);
        setProject(website.project);
        setActiveJob(website.latest_job);
        setGenerating(
          Boolean(website.latest_job && RUNNING_JOB_STATUSES.has(website.latest_job.status)),
        );
        if (website.project) {
          setStyleKey(website.project.style_key);
          setThemeKey(website.project.theme_key);
          setDensityKey(website.project.density_key);
          setSelectedAssetIds(website.project.selected_asset_ids);
          setSelectedDocumentIds(website.project.selected_document_ids);
        } else if (initializedSubjectRef.current !== subjectId) {
          setStyleKey(website.recommendation.style_key);
          setThemeKey(website.recommendation.theme_key);
          setDensityKey(website.recommendation.density_key);
          const defaultDocumentIds = documentMaterials.map((item) => item.document.id);
          const remaining = Math.max(0, 6 - defaultDocumentIds.length);
          const defaultAssetIds = imageResponse.results
            .filter((image) => Boolean(image.url))
            .slice(0, remaining)
            .map((image) => image.id);
          setSelectedDocumentIds(defaultDocumentIds.slice(0, 6));
          setSelectedAssetIds(defaultAssetIds);
        }
        initializedSubjectRef.current = subjectId;
      } catch (reason: unknown) {
        setError(userMessage(reason));
      } finally {
        setLoading(false);
      }
    },
    [loadDocumentMaterials],
  );

  useEffect(() => {
    const subjectId = currentSubject?.id ?? null;
    const timer = window.setTimeout(() => {
      if (!subjectId) {
        setState(null);
        setProject(null);
        setActiveJob(null);
        setImages([]);
        setDocuments([]);
        setGenerating(false);
        return;
      }
      void loadWorkspace(subjectId);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [currentSubject?.id, loadWorkspace]);

  const activeJobId = activeJob?.id ?? null;
  const activeJobStatus = activeJob?.status ?? null;

  useEffect(() => {
    if (!activeJobId || !activeJobStatus || !RUNNING_JOB_STATUSES.has(activeJobStatus)) return;
    let active = true;
    let timer: number | null = null;

    const poll = async () => {
      try {
        const response = await getWebsiteJob(activeJobId);
        if (!active) return;
        setActiveJob(response.job);
        setProject(response.project);
        setGenerating(RUNNING_JOB_STATUSES.has(response.job.status));
        if (RUNNING_JOB_STATUSES.has(response.job.status)) {
          timer = window.setTimeout(() => void poll(), 1800);
        }
      } catch (reason: unknown) {
        if (!active) return;
        setGenerating(false);
        setError(userMessage(reason));
      }
    };

    timer = window.setTimeout(() => void poll(), 900);
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [activeJobId, activeJobStatus]);

  const selectedCount = selectedAssetIds.length + selectedDocumentIds.length;
  const designDirty = Boolean(
    project &&
    (project.style_key !== styleKey ||
      project.theme_key !== themeKey ||
      project.density_key !== densityKey),
  );

  const selectStyle = (value: WebsiteStyleKey) => {
    setStyleKey(value);
    const recommendedThemes = state?.design_options.recommended_themes[value] ?? [];
    const firstRecommendedTheme = recommendedThemes[0];
    if (firstRecommendedTheme && !recommendedThemes.includes(themeKey)) {
      setThemeKey(firstRecommendedTheme);
    }
  };

  const saveDesign = async () => {
    if (!currentSubject?.id || !project || !designDirty) return;
    setSavingDesign(true);
    setError("");
    try {
      const response = await updateWebsiteDesign(currentSubject.id, {
        style_key: styleKey,
        theme_key: themeKey,
        density_key: densityKey,
        expected_version: project.version,
      });
      setProject(response.project);
      messageApi.success("网站设计已保存，文字内容保持不变");
    } catch (reason: unknown) {
      setError(userMessage(reason));
    } finally {
      setSavingDesign(false);
    }
  };

  const toggleAsset = (id: string) => {
    setSelectedAssetIds((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      if (current.length + selectedDocumentIds.length >= MAX_MATERIALS) {
        messageApi.warning(`官网素材最多选择 ${MAX_MATERIALS} 张图片`);
        return current;
      }
      return [...current, id];
    });
  };

  const toggleDocument = (id: string) => {
    setSelectedDocumentIds((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      if (current.length + selectedAssetIds.length >= MAX_MATERIALS) {
        messageApi.warning(`官网素材最多选择 ${MAX_MATERIALS} 张图片`);
        return current;
      }
      return [...current, id];
    });
  };

  const uploadFiles = async (files: FileList | null) => {
    if (!files || !currentSubject?.id) return;
    const candidates = Array.from(files).filter((file) =>
      ["image/jpeg", "image/png", "image/webp"].includes(file.type),
    );
    if (!candidates.length) {
      messageApi.warning("请选择 JPG、PNG 或 WebP 图片");
      return;
    }
    setUploading(true);
    setUploadProgress(0);
    const completedIds: string[] = [];
    try {
      for (let index = 0; index < candidates.length; index += 1) {
        const file = candidates[index];
        const { intent, upload } = await createUploadIntent(
          currentSubject.id,
          file,
          newUploadIdempotencyKey(),
        );
        if (!upload) throw new Error("图片上传暂不可用，请稍后再试");
        await uploadDirect(upload, file, (percent) => {
          const total = Math.round(((index + percent / 100) / candidates.length) * 100);
          setUploadProgress(total);
        });
        const verifying = await completeUploadIntent(intent);
        const completed =
          verifying.status === "completed" ? verifying : await waitForUpload(verifying.id);
        if (completed.document_id) completedIds.push(completed.document_id);
      }
      messageApi.success("图片已保存，可用于官网素材");
      await loadWorkspace(currentSubject.id);
      if (completedIds.length) {
        setSelectedDocumentIds((current) => {
          const merged = [...completedIds, ...current];
          return Array.from(new Set(merged)).slice(0, MAX_MATERIALS - selectedAssetIds.length);
        });
      }
    } catch (reason: unknown) {
      messageApi.error(userMessage(reason));
    } finally {
      setUploading(false);
      setUploadProgress(0);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const startGeneration = async () => {
    if (!currentSubject?.id || !state?.readiness.can_generate) return;
    setError("");
    setGenerating(true);
    try {
      const response = await generateWebsite(currentSubject.id, {
        style_key: styleKey,
        theme_key: themeKey,
        density_key: densityKey,
        image_asset_ids: selectedAssetIds,
        document_ids: selectedDocumentIds,
      });
      setProject(response.project);
      setActiveJob(response.job);
      setStyleKey(response.project.style_key);
      setThemeKey(response.project.theme_key);
      setDensityKey(response.project.density_key);
      setSelectedAssetIds(response.project.selected_asset_ids);
      setSelectedDocumentIds(response.project.selected_document_ids);
      setGenerating(RUNNING_JOB_STATUSES.has(response.job.status));
    } catch (reason: unknown) {
      setGenerating(false);
      setError(userMessage(reason));
    }
  };

  const previewMaterials = useMemo<WebsitePreviewImage[]>(() => {
    const documentMap = new Map(documents.map((item) => [item.document.id, item]));
    const assetMap = new Map(images.map((image) => [image.id, image]));
    const uploaded = selectedDocumentIds.flatMap((id) => {
      const item = documentMap.get(id);
      if (!item?.previewUrl) return [];
      return [
        {
          id,
          url: item.previewUrl,
          name: item.document.display_name,
          source: "客户上传" as const,
        },
      ];
    });
    const library = selectedAssetIds.flatMap((id) => {
      const image = assetMap.get(id);
      if (!image?.url) return [];
      return [
        {
          id,
          url: image.url,
          name: image.role === "cover" ? "品牌主图" : "内容图片",
          source: "内容图片库" as const,
        },
      ];
    });
    return [...uploaded, ...library];
  }, [documents, images, selectedAssetIds, selectedDocumentIds]);

  if (subjectLoading) {
    return (
      <main className="page-shell">
        <Skeleton active paragraph={{ rows: 8 }} />
      </main>
    );
  }

  if (!currentSubject) {
    return (
      <main className="page-shell">
        <Empty
          description="请先绑定主体，再为这个主体搭建官网"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </main>
    );
  }

  const readiness = state?.readiness;
  const hasMaterials = documents.length > 0 || images.length > 0;
  const jobFailed = activeJob?.status === "failed";
  const subjectName =
    state?.subject.official_name ||
    currentSubject.official_name ||
    currentSubject.subject_type.name ||
    "当前主体";

  return (
    <main className="page-shell">
      {messageHolder}
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={2} style={{ marginBottom: 8 }}>
            官网实体建设
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            围绕当前主体的真实资料，一键生成适合 GEO 与搜索理解的企业官网草稿。
          </Typography.Paragraph>
        </div>

        {error && <Alert type="warning" showIcon title={error} />}
        {jobFailed && !error && (
          <Alert type="warning" showIcon title="官网生成暂未完成，你可以直接重新生成" />
        )}

        <section className={styles.heroPanel}>
          <div className={styles.heroContent}>
            <div className={styles.heroCopy}>
              <Typography.Text type="secondary">当前主体</Typography.Text>
              <h2 className={styles.subjectName}>{subjectName}</h2>
              <p className={styles.subtitle}>
                系统会自动读取已确认的企业资料、产品与服务、关键词和检测问题。你可以补充真实图片素材，也可以直接使用显问推荐的网站设计。
              </p>
            </div>
            <Space wrap>
              <Tag color="blue">只使用已确认资料</Tag>
              <Tag color="green">客户真实图片优先</Tag>
              <Tag>设计可随时更换</Tag>
            </Space>
          </div>
        </section>

        <Card title="已准备资料" loading={loading}>
          {readiness && (
            <div className={styles.sourceGrid}>
              <div className={styles.sourceItem}>
                <span className={styles.sourceLabel}>主体资料</span>
                <strong className={styles.sourceValue}>
                  {readiness.subject_ready ? "已准备" : "待完善"}
                </strong>
              </div>
              <div className={styles.sourceItem}>
                <span className={styles.sourceLabel}>产品与服务</span>
                <strong className={styles.sourceValue}>{readiness.product_count}</strong>
              </div>
              <div className={styles.sourceItem}>
                <span className={styles.sourceLabel}>关键词</span>
                <strong className={styles.sourceValue}>{readiness.keyword_count}</strong>
              </div>
              <div className={styles.sourceItem}>
                <span className={styles.sourceLabel}>检测问题</span>
                <strong className={styles.sourceValue}>{readiness.question_count}</strong>
              </div>
              <div className={styles.sourceItem}>
                <span className={styles.sourceLabel}>可用图片</span>
                <strong className={styles.sourceValue}>{readiness.image_count}</strong>
              </div>
            </div>
          )}
        </Card>

        {state && (
          <WebsiteDesignSelector
            options={state.design_options}
            recommendation={state.recommendation}
            styleKey={styleKey}
            themeKey={themeKey}
            densityKey={densityKey}
            disabled={generating || savingDesign}
            canSave={Boolean(project?.site && designDirty)}
            saving={savingDesign}
            onStyleChange={selectStyle}
            onThemeChange={setThemeKey}
            onDensityChange={setDensityKey}
            onSave={() => void saveDesign()}
          />
        )}

        <Card>
          <div className={styles.materialHeader}>
            <div>
              <Typography.Title level={4} style={{ margin: 0 }}>
                官网图片素材
              </Typography.Title>
              <Typography.Text type="secondary">
                已选择 {selectedCount}/{MAX_MATERIALS}{" "}
                张。客户上传的真实图片会优先用于首屏和内容展示。
              </Typography.Text>
            </div>
            <Space wrap>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                hidden
                onChange={(event) => void uploadFiles(event.target.files)}
              />
              <Button
                icon={<CloudUploadOutlined />}
                loading={uploading}
                onClick={() => fileInputRef.current?.click()}
              >
                {uploading ? `正在上传 ${uploadProgress}%` : "上传企业图片"}
              </Button>
              <Button
                icon={<ReloadOutlined />}
                disabled={loading}
                onClick={() => void loadWorkspace(currentSubject.id)}
              >
                刷新素材
              </Button>
            </Space>
          </div>

          <div style={{ height: 16 }} />
          {!hasMaterials ? (
            <div className={styles.emptyMaterials}>
              <PictureOutlined style={{ marginRight: 8 }} />
              暂无图片也可以生成官网；首屏会使用简洁的品牌视觉。上传企业真实图片后，官网会更有可信度。
            </div>
          ) : (
            <div className={styles.materialGrid}>
              {documents.map(({ document, previewUrl }) => {
                const selected = selectedDocumentIds.includes(document.id);
                return (
                  <button
                    type="button"
                    className={`${styles.materialCard} ${selected ? styles.materialCardSelected : ""}`}
                    key={`document-${document.id}`}
                    onClick={() => toggleDocument(document.id)}
                  >
                    {previewUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        className={styles.materialImage}
                        src={previewUrl}
                        alt={document.display_name}
                      />
                    ) : (
                      <span className={styles.materialFallback}>企业图片</span>
                    )}
                    {selected && (
                      <span className={styles.selectedMark} aria-label="已选择">
                        <CheckOutlined />
                      </span>
                    )}
                    <span className={styles.materialMeta}>
                      <span className={styles.materialName}>{document.display_name}</span>
                      <span className={styles.materialSource}>客户上传</span>
                    </span>
                  </button>
                );
              })}

              {images.map((image) => {
                const selected = selectedAssetIds.includes(image.id);
                return (
                  <button
                    type="button"
                    className={`${styles.materialCard} ${selected ? styles.materialCardSelected : ""}`}
                    key={`asset-${image.id}`}
                    onClick={() => toggleAsset(image.id)}
                  >
                    {image.url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img className={styles.materialImage} src={image.url} alt="内容图片" />
                    ) : (
                      <span className={styles.materialFallback}>内容图片</span>
                    )}
                    {selected && (
                      <span className={styles.selectedMark} aria-label="已选择">
                        <CheckOutlined />
                      </span>
                    )}
                    <span className={styles.materialMeta}>
                      <span className={styles.materialName}>
                        {image.role === "cover" ? "品牌主图" : "内容图片"}
                      </span>
                      <span className={styles.materialSource}>内容图片库</span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </Card>

        <section className={styles.generatePanel}>
          <div>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {project?.site ? "重新生成官网内容" : "生成当前主体官网"}
            </Typography.Title>
            <Typography.Text type="secondary">
              自动规划首页、关于我们、产品服务、解决方案、常见问题和联系我们，并生成 GEO
              友好的中文内容。
            </Typography.Text>
          </div>
          <Button
            type="primary"
            size="large"
            icon={<RocketOutlined />}
            loading={generating}
            disabled={!readiness?.can_generate || uploading || loading}
            onClick={() => void startGeneration()}
          >
            {project?.site ? "重新生成官网内容" : "AI 一键生成官网"}
          </Button>
        </section>

        {generating && (
          <Card>
            <Space orientation="vertical" size="small">
              <Typography.Title level={4} style={{ margin: 0 }}>
                正在围绕当前主体生成官网
              </Typography.Title>
              <Typography.Text type="secondary">
                系统正在整理真实企业资料并生成网站内容。完成后，官网预览会自动出现在这里。
              </Typography.Text>
              <div className={styles.generatingSteps}>
                <span className={styles.generatingStepActive}>● 正在生成官网草稿</span>
                <span className={styles.generatingStep}>不会自动发布，生成完成后由你确认</span>
              </div>
            </Space>
          </Card>
        )}

        {project?.site && (
          <WebsiteDraftPreview
            project={project}
            subjectName={subjectName}
            materials={previewMaterials}
            design={{ styleKey, themeKey, densityKey }}
          />
        )}
      </Space>
    </main>
  );
}
