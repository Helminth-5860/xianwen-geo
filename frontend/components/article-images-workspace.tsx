"use client";

import {
  Alert,
  Button,
  Card,
  Image,
  Input,
  List,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  attachImage,
  deriveImage,
  deriveImageAI,
  generateImage,
  getImageJob,
  getImageRecommendations,
  getImageSizes,
  getImageStyles,
  getSubjectImages,
  saveImageToLibrary,
  type ImageAsset,
  type ImageJob,
  type ImageQuota,
  type ImageRecommendation,
  type ImageSizePreset,
  type ImageStylePreset,
} from "@/lib/images-client";

export const IMAGE_POLL_INTERVAL_MS = 1200;

type Props = Readonly<{
  subjectId: string;
  articleId?: string | null;
  articleTitle?: string;
  referenceDocuments?: ReadonlyArray<{ id: string; label: string }>;
}>;

const IMAGE_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  IMAGE_INPUT_TEXT_SENSITIVE: "提示词未通过内容安全检查，额度已释放。",
  IMAGE_INPUT_REFERENCE_SENSITIVE: "参考图未通过内容安全检查，额度已释放。",
  IMAGE_OUTPUT_SENSITIVE: "生成结果未通过内容安全检查，额度已释放。",
  IMAGE_CREDENTIAL_UNAVAILABLE: "图片生成服务凭据尚未配置，请联系管理员。",
  IMAGE_CREDENTIAL_BINDING_UNAVAILABLE: "图片生成服务凭据尚未启用，请联系管理员。",
  IMAGE_CREDENTIAL_DECRYPTION_FAILED: "图片生成服务凭据读取失败，请联系管理员。",
  IMAGE_CREDENTIAL_PROVENANCE_CHANGED: "图片生成服务配置已变更，请重新提交。",
  IMAGE_RUNTIME_UNAVAILABLE: "图片生成服务尚未启用，请联系管理员。",
  IMAGE_STORAGE_UNAVAILABLE: "图片存储服务尚未配置，请联系管理员。",
  IMAGE_STORAGE_VERIFICATION_FAILED: "图片保存校验失败，本次额度已释放，请重试。",
  IMAGE_PROVIDER_AUTHENTICATION_FAILED: "豆包图片服务鉴权失败，请联系管理员。",
  IMAGE_PROVIDER_QUOTA_EXCEEDED: "豆包图片服务额度不足，请联系管理员。",
  IMAGE_PROVIDER_RATE_LIMIT: "图片生成请求较多，请稍后重试。",
  IMAGE_PROVIDER_TIMEOUT: "图片生成响应超时，本次额度已释放，请重试。",
  IMAGE_PROVIDER_NETWORK_FAILURE: "图片生成网络暂时不可用，请稍后重试。",
  IMAGE_PROVIDER_TEMPORARY_FAILURE: "豆包图片服务暂时不可用，请稍后重试。",
  IMAGE_PROVIDER_REQUEST_REJECTED: "豆包图片服务拒绝了本次请求，请调整内容后重试。",
  IMAGE_PROVIDER_REQUEST_INVALID: "图片生成参数不正确，请调整后重试。",
  IMAGE_PROVIDER_RESPONSE_INVALID: "豆包图片服务返回格式异常，请稍后重试。",
  IMAGE_QUEUE_UNAVAILABLE: "图片任务队列暂时不可用，请稍后重试。",
  IMAGE_INTERNAL_FAILURE: "图片生成处理失败，本次额度已释放，请稍后重试。",
  IMAGE_PLAN_REQUIRED: "当前账号尚未开通图片生成权限。",
  IMAGE_QUOTA_ACCOUNT_UNAVAILABLE: "图片额度账户不可用，请联系管理员。",
};

const IMAGE_JOB_STATUS: Readonly<Record<ImageJob["status"], string>> = {
  queued: "等待处理",
  running: "生成中",
  retry_wait: "等待重试",
  succeeded: "生成成功",
  failed: "生成失败",
};

const IMAGE_ROLE_LABEL: Readonly<Record<ImageAsset["role"], string>> = {
  cover: "文章封面",
  illustration: "正文插图",
  channel: "渠道图片",
};

const IMAGE_REVIEW_LABEL: Readonly<Record<ImageAsset["moderation_status"], string>> = {
  approved: "审核通过",
  suspected: "待复核",
  rejected: "未通过",
  service_error: "审核服务异常",
};

function imageErrorMessage(code: string): string {
  if (!code) return "";
  return IMAGE_ERROR_MESSAGES[code] ?? "图片生成失败，请稍后重试。";
}

function imageUserMessage(error: unknown): string {
  if (error instanceof AuthApiError) {
    const detailCode = error.details.image_code;
    const code = typeof detailCode === "string" ? detailCode : error.message;
    if (code.startsWith("IMAGE_")) return imageErrorMessage(code);
  }
  return userMessage(error);
}

export function ArticleImagesWorkspace({
  subjectId,
  articleId = null,
  articleTitle = "",
  referenceDocuments = [],
}: Props) {
  const [sizes, setSizes] = useState<ImageSizePreset[]>([]);
  const [styles, setStyles] = useState<ImageStylePreset[]>([]);
  const [recommendations, setRecommendations] = useState<ImageRecommendation[]>([]);
  const [images, setImages] = useState<ImageAsset[]>([]);
  const [quota, setQuota] = useState<ImageQuota>({
    available: 0,
    frozen: 0,
    consumed: 0,
    unlimited: false,
  });
  const [role, setRole] = useState<ImageAsset["role"]>("cover");
  const [prompt, setPrompt] = useState(
    articleTitle
      ? `为《${articleTitle}》生成专业、清晰的文章封面`
      : "为当前主体生成专业、清晰的品牌配图",
  );
  const [sizeId, setSizeId] = useState("");
  const [styleId, setStyleId] = useState("");
  const [referenceAssetId, setReferenceAssetId] = useState<string | null>(null);
  const [referenceDocumentVersionId, setReferenceDocumentVersionId] = useState<string | null>(null);
  const [referenceUrl, setReferenceUrl] = useState("");
  const [job, setJob] = useState<ImageJob>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const reloadLibrary = useCallback(async () => {
    const result = await getSubjectImages(subjectId);
    setImages(result.results);
    setQuota(result.quota);
  }, [subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      try {
        const [sizeRows, styleRows, recommendationRows] = await Promise.all([
          getImageSizes(),
          getImageStyles(),
          articleId
            ? getImageRecommendations(articleId)
            : Promise.resolve({ recommendations: [] as ImageRecommendation[] }),
        ]);
        setSizes(sizeRows);
        setStyles(styleRows);
        setSizeId(sizeRows[0]?.id ?? "");
        setStyleId(styleRows[0]?.id ?? "");
        setRecommendations(recommendationRows.recommendations);
        await reloadLibrary();
      } catch (reason) {
        setError(imageUserMessage(reason));
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [articleId, reloadLibrary]);

  useEffect(() => {
    if (!job || !["queued", "running", "retry_wait"].includes(job.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await getImageJob(job.id);
        setJob(next);
        setQuota((current) => ({
          ...current,
          frozen:
            next.status === "succeeded" || next.status === "failed"
              ? Math.max(0, current.frozen - 1)
              : current.frozen,
        }));
        if (next.status === "succeeded") {
          setError("");
          setNotice("图片已转存到私有存储并通过审核；图片额度已扣除。 ");
          await reloadLibrary();
        } else if (next.status === "failed") {
          setError("");
          await reloadLibrary();
        }
      } catch (reason) {
        setError(imageUserMessage(reason));
      }
    }, IMAGE_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [job, reloadLibrary]);

  const activeImage = job?.image;
  const canGenerate = Boolean(
    prompt.trim() && sizeId && styleId && (quota.unlimited || quota.available > 0),
  );
  const approvedImages = useMemo(
    () => images.filter((image) => image.moderation_status === "approved"),
    [images],
  );

  const applyRecommendation = (item: ImageRecommendation) => {
    setRole(item.role);
    setPrompt(item.prompt);
    setSizeId(item.size_preset_id);
    setStyleId(item.style_preset_id);
    setNotice("推荐方案已填入，确认或修改后再生成。系统不会自动扣额度。");
  };

  const submit = async () => {
    if (!canGenerate) return;
    setBusy(true);
    setError("");
    try {
      const result = await generateImage(subjectId, {
        article_id: articleId,
        role,
        prompt,
        size_preset_id: sizeId,
        style_preset_id: styleId,
        reference_asset_id: referenceAssetId,
        reference_document_version_id: referenceDocumentVersionId,
        reference_url: referenceAssetId || referenceDocumentVersionId ? "" : referenceUrl,
      });
      setJob(result.job);
      setQuota(result.quota);
      setNotice("图片任务已提交并冻结 1 个图片额度；失败会自动释放。 ");
    } catch (reason) {
      setError(imageUserMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const updateAsset = (updated: ImageAsset) => {
    setImages((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    if (job?.image?.id === updated.id) setJob({ ...job, image: updated });
  };

  return (
    <Card title={articleId ? "4. GEO 配图生成" : "图片生成"}>
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Space wrap>
          <Statistic title="可用图片额度" value={quota.unlimited ? "不限" : quota.available} />
          <Statistic title="已冻结" value={quota.frozen} />
          <Statistic title="已消耗" value={quota.consumed} />
        </Space>
        <Alert
          type="info"
          showIcon
          title="图片由豆包图片模型生成，成功后立即校验并转存私有存储"
          description="页面只接收系统内的私有图片地址，不展示供应商临时链接、原始响应或凭据。"
        />
        {error && <Alert type="error" showIcon title={error} />}
        {notice && <Alert type="success" showIcon title={notice} />}
        {articleId && (
          <>
            <Typography.Text strong>AI 推荐配图（需要用户确认）</Typography.Text>
            <List
              size="small"
              dataSource={recommendations}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button key="use" onClick={() => applyRecommendation(item)}>
                      采用并编辑
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={`${item.purpose} · ${item.position}`}
                    description={item.prompt}
                  />
                </List.Item>
              )}
            />
          </>
        )}
        <Space wrap style={{ width: "100%" }}>
          <Select
            aria-label="图片用途"
            value={role}
            options={[
              { value: "cover", label: "文章封面" },
              { value: "illustration", label: "正文插图" },
              { value: "channel", label: "渠道图片" },
            ]}
            onChange={setRole}
          />
          <Select
            aria-label="图片尺寸"
            value={sizeId || undefined}
            style={{ minWidth: 180 }}
            options={sizes.map((item) => ({
              value: item.id,
              label: `${item.name} · ${item.aspect_ratio}`,
            }))}
            onChange={setSizeId}
          />
          <Select
            aria-label="图片风格"
            value={styleId || undefined}
            style={{ minWidth: 180 }}
            options={styles.map((item) => ({ value: item.id, label: item.name }))}
            onChange={setStyleId}
          />
        </Space>
        <Input.TextArea
          aria-label="图片提示词"
          value={prompt}
          rows={4}
          maxLength={4000}
          onChange={(event) => setPrompt(event.target.value)}
        />
        <Select
          aria-label="主体图库参考图"
          allowClear
          value={referenceAssetId ?? undefined}
          placeholder="可选：使用已审核主体图片作为参考图"
          style={{ width: "100%" }}
          options={approvedImages.map((image) => ({
            value: image.id,
            label: `${IMAGE_ROLE_LABEL[image.role]} · ${image.width}×${image.height}`,
          }))}
          onChange={(value) => {
            setReferenceAssetId(value ?? null);
            if (value) {
              setReferenceDocumentVersionId(null);
              setReferenceUrl("");
            }
          }}
        />
        <Select
          aria-label="临时上传参考图"
          allowClear
          value={referenceDocumentVersionId ?? undefined}
          placeholder="可选：使用已上传的 PNG/JPEG/WEBP 资料"
          style={{ width: "100%" }}
          options={referenceDocuments.map((document) => ({
            value: document.id,
            label: document.label,
          }))}
          onChange={(value) => {
            setReferenceDocumentVersionId(value ?? null);
            if (value) {
              setReferenceAssetId(null);
              setReferenceUrl("");
            }
          }}
        />
        <Input
          aria-label="HTTPS 参考图地址"
          value={referenceUrl}
          disabled={Boolean(referenceAssetId || referenceDocumentVersionId)}
          placeholder="可选：粘贴安全的图片链接（系统会校验链接与文件）"
          onChange={(event) => {
            setReferenceUrl(event.target.value);
            if (event.target.value) {
              setReferenceAssetId(null);
              setReferenceDocumentVersionId(null);
            }
          }}
        />
        <Button
          type="primary"
          loading={busy}
          disabled={!canGenerate || ["queued", "running", "retry_wait"].includes(job?.status ?? "")}
          onClick={submit}
        >
          生成图片（成功交付后扣 1 图片额度）
        </Button>
        {job && (
          <Alert
            type={
              job.status === "failed" ? "error" : job.status === "succeeded" ? "success" : "info"
            }
            showIcon
            title={`图片任务：${IMAGE_JOB_STATUS[job.status]}`}
            description={
              job.status === "failed"
                ? imageErrorMessage(job.safe_error_code)
                : `尝试 ${job.attempt_count}/${job.max_retries + 1} · ${IMAGE_JOB_STATUS[job.status]}`
            }
            action={
              job.status === "failed" ? <Button onClick={submit}>修改后重试</Button> : undefined
            }
          />
        )}
        {activeImage?.url && (
          <Card size="small" title="私有存储预览">
            <Space orientation="vertical">
              <Image src={activeImage.url} alt="生成图片预览" width={320} />
              <Space wrap>
                <Tag>
                  {activeImage.width}×{activeImage.height}
                </Tag>
                <Tag>{IMAGE_REVIEW_LABEL[activeImage.moderation_status]}</Tag>
                {articleId && (
                  <Button
                    onClick={async () =>
                      updateAsset(
                        await attachImage(activeImage.id, articleId, activeImage.version ?? 1),
                      )
                    }
                  >
                    选入当前文章
                  </Button>
                )}
                <Button
                  onClick={async () =>
                    updateAsset(await saveImageToLibrary(activeImage.id, activeImage.version ?? 1))
                  }
                >
                  保存到主体图库
                </Button>
                <Button
                  onClick={async () => {
                    const result = await deriveImage(activeImage.id, {
                      kind: "channel",
                      width: 1200,
                      height: 630,
                      output_format: "jpeg",
                    });
                    if (result.url) window.location.assign(result.url);
                  }}
                >
                  免费生成渠道图
                </Button>
                <Button
                  disabled={!canGenerate}
                  onClick={async () => {
                    try {
                      const result = await deriveImageAI(activeImage.id, {
                        prompt: `基于参考图进行渠道适配重构：${prompt}`,
                        size_preset_id: sizeId,
                        style_preset_id: styleId,
                      });
                      setJob(result.job);
                      setQuota(result.quota);
                      setNotice("AI 智能处理已提交并冻结 1 个图片额度；交付成功后扣除。");
                    } catch (reason) {
                      setError(imageUserMessage(reason));
                    }
                  }}
                >
                  AI 智能扩图/重构（成功扣 1 额度）
                </Button>
              </Space>
            </Space>
          </Card>
        )}
      </Space>
    </Card>
  );
}
