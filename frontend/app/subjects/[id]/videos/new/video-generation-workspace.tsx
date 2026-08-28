"use client";

import {
  DownloadOutlined,
  ReloadOutlined,
  SaveOutlined,
  UploadOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  List,
  Pagination,
  Progress,
  Radio,
  Space,
  Tag,
  Typography,
  Upload,
} from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  completeUploadIntent,
  createUploadIntent,
  getUploadIntent,
  newUploadIdempotencyKey,
  uploadDirect,
} from "@/lib/documents-client";
import {
  createVideoDownloadIntent,
  createVideoJob,
  listSubjectVideoJobs,
  regenerateVideoJob,
  saveVideoToLibrary,
  videoFailureMessage,
  videoUserMessage,
  type VideoAspectRatio,
  type VideoDurationSeconds,
  type VideoGenerationMode,
  type VideoJob,
  type VideoJobStatus,
  type VideoPagination,
  type VideoQuota,
} from "@/lib/videos-client";

import styles from "./video-generation-workspace.module.css";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 2500;
const PROMPT_MAX_LENGTH = 1500;
const REFERENCE_IMAGE_MAX_BYTES = 20 * 1024 * 1024;
const ACTIVE_STATUSES: ReadonlySet<VideoJobStatus> = new Set([
  "queued",
  "processing",
  "running",
  "retry_wait",
]);

const EMPTY_QUOTA: VideoQuota = {
  available: 0,
  frozen: 0,
  consumed: 0,
  unlimited: false,
};

const EMPTY_PAGINATION: VideoPagination = {
  page: 1,
  page_size: PAGE_SIZE,
  count: 0,
  total_pages: 0,
};

const STATUS_LABELS: Readonly<Record<VideoJobStatus, string>> = {
  queued: "排队中",
  processing: "生成中",
  running: "生成中",
  retry_wait: "正在继续处理",
  succeeded: "已完成",
  failed: "未能完成",
};

const STATUS_COLORS: Readonly<Record<VideoJobStatus, string>> = {
  queued: "blue",
  processing: "processing",
  running: "processing",
  retry_wait: "orange",
  succeeded: "green",
  failed: "red",
};

type Props = Readonly<{ subjectId: string }>;
type UploadedReference = Readonly<{ documentVersionId: string; name: string }>;

function createdAtLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function isSupportedImage(file: File) {
  const extension = file.name.toLowerCase().split(".").pop() ?? "";
  return (
    ["jpg", "jpeg", "png", "webp"].includes(extension) &&
    (!file.type || ["image/jpeg", "image/png", "image/webp"].includes(file.type))
  );
}

export default function VideoGenerationWorkspace({ subjectId }: Props) {
  const [mode, setMode] = useState<VideoGenerationMode>("text");
  const [prompt, setPrompt] = useState("");
  const [aspectRatio, setAspectRatio] = useState<VideoAspectRatio>("9:16");
  const [durationSeconds, setDurationSeconds] = useState<VideoDurationSeconds>(5);
  const [reference, setReference] = useState<UploadedReference | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number>();
  const [jobs, setJobs] = useState<VideoJob[]>([]);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState<VideoPagination>(EMPTY_PAGINATION);
  const [quota, setQuota] = useState<VideoQuota>(EMPTY_QUOTA);
  const [quotaLoaded, setQuotaLoaded] = useState(false);
  const [loadedSubjectId, setLoadedSubjectId] = useState("");
  const [listLoading, setListLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const submissionKey = useRef<string | null>(null);
  const regenerationKeys = useRef(new Map<string, string>());
  const uploadGeneration = useRef(0);

  const resetSubmissionKey = () => {
    submissionKey.current = null;
  };

  const loadJobs = useCallback(
    async (signal?: AbortSignal, quiet = false) => {
      if (!quiet) setListLoading(true);
      try {
        const result = await listSubjectVideoJobs(subjectId, page, PAGE_SIZE, signal);
        if (signal?.aborted) return;
        setJobs(result.items);
        setPagination(result.pagination);
        setQuota(result.quota);
        setQuotaLoaded(true);
        setLoadedSubjectId(subjectId);
        if (!quiet) setError("");
      } catch (reason) {
        if (signal?.aborted) return;
        setError(videoUserMessage(reason));
        setLoadedSubjectId(subjectId);
      } finally {
        if (!signal?.aborted && !quiet) setListLoading(false);
      }
    },
    [page, subjectId],
  );

  useEffect(
    () => () => {
      uploadGeneration.current += 1;
    },
    [subjectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void loadJobs(controller.signal), 0);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [loadJobs]);

  const visibleJobs = loadedSubjectId === subjectId ? jobs : [];
  const hasActiveJobs = visibleJobs.some((job) => ACTIVE_STATUSES.has(job.status));

  useEffect(() => {
    if (!hasActiveJobs) return;
    let cancelled = false;
    let timer = 0;
    let controller: AbortController | null = null;
    const schedule = () => {
      timer = window.setTimeout(async () => {
        controller = new AbortController();
        await loadJobs(controller.signal, true);
        if (!cancelled) schedule();
      }, POLL_INTERVAL_MS);
    };
    schedule();
    return () => {
      cancelled = true;
      controller?.abort();
      window.clearTimeout(timer);
    };
  }, [hasActiveJobs, loadJobs]);

  const estimatedCredits = durationSeconds;
  const hasEnoughQuota = quota.unlimited || quota.available >= estimatedCredits;
  const canGenerate = Boolean(
    prompt.trim() &&
    prompt.trim().length <= PROMPT_MAX_LENGTH &&
    (mode === "text" || reference) &&
    quotaLoaded &&
    hasEnoughQuota &&
    uploadProgress === undefined,
  );

  const uploadReference = async (file: File) => {
    resetSubmissionKey();
    setError("");
    setNotice("");
    if (!isSupportedImage(file)) {
      setError("仅支持 PNG、JPEG 或 WEBP 格式的参考图片。");
      return;
    }
    if (file.size > REFERENCE_IMAGE_MAX_BYTES) {
      setError("参考图片不能超过 20 MB。");
      return;
    }
    const generation = ++uploadGeneration.current;
    setUploadProgress(0);
    try {
      const created = await createUploadIntent(subjectId, file, newUploadIdempotencyKey());
      if (!created.upload) throw new Error("参考图片暂时无法上传，请稍后重试。");
      await uploadDirect(created.upload, file, (percent) => {
        if (generation === uploadGeneration.current) setUploadProgress(percent);
      });
      let intent = await completeUploadIntent(created.intent);
      for (let attempt = 0; attempt < 90 && intent.status === "verifying"; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 800));
        if (generation !== uploadGeneration.current) return;
        intent = await getUploadIntent(intent.id);
      }
      if (generation !== uploadGeneration.current) return;
      if (intent.status !== "completed" || !intent.document_version_id) {
        throw new Error("参考图片未能通过安全检查，请重新上传。");
      }
      setReference({ documentVersionId: intent.document_version_id, name: file.name });
      setNotice("参考图片已安全保存，可以开始生成视频。 ");
    } catch (reason) {
      if (generation === uploadGeneration.current) setError(videoUserMessage(reason));
    } finally {
      if (generation === uploadGeneration.current) setUploadProgress(undefined);
    }
  };

  const submit = async () => {
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt) {
      setError("请填写内容描述。");
      return;
    }
    if (cleanPrompt.length > PROMPT_MAX_LENGTH) {
      setError("内容描述最多可填写 1500 个字。");
      return;
    }
    if (mode === "image" && !reference) {
      setError("图片生成视频需要先上传一张参考图片。");
      return;
    }
    if (!hasEnoughQuota) {
      setError("当前视频额度不足，请查看套餐与额度。");
      return;
    }
    if (submitting) return;

    setSubmitting(true);
    setError("");
    setNotice("");
    const key = submissionKey.current ?? crypto.randomUUID();
    submissionKey.current = key;
    try {
      const result = await createVideoJob(
        subjectId,
        {
          generation_mode: mode,
          prompt: cleanPrompt,
          source_document_version_id:
            mode === "image" ? (reference?.documentVersionId ?? null) : null,
          aspect_ratio: aspectRatio,
          duration_seconds: durationSeconds,
        },
        key,
      );
      submissionKey.current = null;
      setQuota(result.quota);
      setQuotaLoaded(true);
      setNotice(`视频已进入生成流程，暂时预留 ${estimatedCredits} 个视频额度；未完成不会扣除。`);
      setLoadedSubjectId(subjectId);
      if (page === 1) {
        setJobs((current) => [result.job, ...current.filter((item) => item.id !== result.job.id)]);
        setPagination((current) => ({ ...current, count: current.count + 1 }));
      } else {
        setPage(1);
      }
    } catch (reason) {
      setError(videoUserMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const updateJobVideo = (jobId: string, video: NonNullable<VideoJob["video"]>) => {
    setJobs((current) => current.map((item) => (item.id === jobId ? { ...item, video } : item)));
  };

  const download = async (job: VideoJob) => {
    setActionBusy(`download:${job.id}`);
    setError("");
    try {
      const result = await createVideoDownloadIntent(job.id);
      window.location.assign(result.url);
    } catch (reason) {
      setError(videoUserMessage(reason));
    } finally {
      setActionBusy("");
    }
  };

  const save = async (job: VideoJob) => {
    if (!job.video) return;
    setActionBusy(`save:${job.id}`);
    setError("");
    try {
      const video = await saveVideoToLibrary(job.id, job.video.version);
      updateJobVideo(job.id, video);
      setNotice("视频已保存到当前主体的视频库。 ");
    } catch (reason) {
      setError(videoUserMessage(reason));
    } finally {
      setActionBusy("");
    }
  };

  const regenerate = async (job: VideoJob) => {
    if (actionBusy) return;
    setActionBusy(`regenerate:${job.id}`);
    setError("");
    setNotice("");
    const key = regenerationKeys.current.get(job.id) ?? crypto.randomUUID();
    regenerationKeys.current.set(job.id, key);
    try {
      const result = await regenerateVideoJob(job.id, key);
      regenerationKeys.current.delete(job.id);
      setQuota(result.quota);
      setQuotaLoaded(true);
      setNotice(
        `已重新开始生成，暂时预留 ${result.job.duration_seconds} 个视频额度；未完成不会扣除。`,
      );
      setLoadedSubjectId(subjectId);
      if (page === 1) {
        setJobs((current) => [result.job, ...current.filter((item) => item.id !== result.job.id)]);
        setPagination((current) => ({ ...current, count: current.count + 1 }));
      } else {
        setPage(1);
      }
    } catch (reason) {
      setError(videoUserMessage(reason));
    } finally {
      setActionBusy("");
    }
  };

  const quotaLabel = useMemo(() => (quota.unlimited ? "不限" : quota.available), [quota]);

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div className={styles.heading}>
          <div>
            <Typography.Title level={2}>AI 视频生成</Typography.Title>
            <Typography.Text type="secondary">
              将文字或参考图片生成简短视频，完成后可以播放、下载或保存到视频库
            </Typography.Text>
          </div>
          <Tag color="blue">清晰度固定为 720P</Tag>
        </div>

        {error && <Alert type="error" showIcon title={error} />}
        {notice && <Alert type="success" showIcon title={notice} />}

        <Card title="生成设置">
          <div className={styles.formGrid}>
            <div>
              <div className={styles.field}>
                <Typography.Text strong>生成方式</Typography.Text>
                <Radio.Group
                  className={styles.choiceGroup}
                  value={mode}
                  buttonStyle="solid"
                  onChange={(event) => {
                    setMode(event.target.value as VideoGenerationMode);
                    resetSubmissionKey();
                    setError("");
                  }}
                >
                  <Radio.Button value="text">文字生成视频</Radio.Button>
                  <Radio.Button value="image">图片生成视频</Radio.Button>
                </Radio.Group>
              </div>

              <div className={styles.field}>
                <Space align="baseline" style={{ justifyContent: "space-between" }}>
                  <Typography.Text strong>内容描述</Typography.Text>
                  <Typography.Text type="secondary">
                    {prompt.length}/{PROMPT_MAX_LENGTH}
                  </Typography.Text>
                </Space>
                <Input.TextArea
                  aria-label="视频内容描述"
                  value={prompt}
                  rows={6}
                  maxLength={PROMPT_MAX_LENGTH}
                  showCount={false}
                  placeholder="描述希望生成的画面、主体、动作、场景和氛围"
                  onChange={(event) => {
                    setPrompt(event.target.value);
                    resetSubmissionKey();
                  }}
                />
              </div>

              {mode === "image" && (
                <div className={styles.field}>
                  <Typography.Text strong>参考图片</Typography.Text>
                  <div className={styles.uploadPanel}>
                    <Space orientation="vertical" size="small" style={{ width: "100%" }}>
                      <Typography.Text type="secondary">
                        支持 PNG、JPEG、WEBP，最大 20 MB。图片会先安全保存，再用于本次生成。
                      </Typography.Text>
                      <Space wrap>
                        <Upload
                          accept=".jpg,.jpeg,.png,.webp"
                          showUploadList={false}
                          disabled={uploadProgress !== undefined}
                          beforeUpload={(file) => {
                            void uploadReference(file);
                            return false;
                          }}
                        >
                          <Button icon={<UploadOutlined />} loading={uploadProgress !== undefined}>
                            {reference ? "更换参考图片" : "上传参考图片"}
                          </Button>
                        </Upload>
                        {reference && <Tag color="green">已上传：{reference.name}</Tag>}
                        {reference && (
                          <Button
                            type="link"
                            onClick={() => {
                              setReference(null);
                              resetSubmissionKey();
                            }}
                          >
                            移除
                          </Button>
                        )}
                      </Space>
                      {uploadProgress !== undefined && (
                        <Progress percent={uploadProgress} size="small" />
                      )}
                    </Space>
                  </div>
                </div>
              )}

              <div className={styles.field}>
                <Typography.Text strong>视频比例</Typography.Text>
                <Radio.Group
                  className={styles.choiceGroup}
                  value={aspectRatio}
                  buttonStyle="solid"
                  onChange={(event) => {
                    setAspectRatio(event.target.value as VideoAspectRatio);
                    resetSubmissionKey();
                  }}
                >
                  <Radio.Button value="9:16">竖屏 9:16</Radio.Button>
                  <Radio.Button value="16:9">横屏 16:9</Radio.Button>
                </Radio.Group>
              </div>

              <div className={styles.field}>
                <Typography.Text strong>视频时长</Typography.Text>
                <Radio.Group
                  className={styles.choiceGroup}
                  value={durationSeconds}
                  buttonStyle="solid"
                  onChange={(event) => {
                    setDurationSeconds(event.target.value as VideoDurationSeconds);
                    resetSubmissionKey();
                  }}
                >
                  <Radio.Button value={5}>5 秒</Radio.Button>
                  <Radio.Button value={10}>10 秒</Radio.Button>
                </Radio.Group>
              </div>
            </div>

            <aside className={styles.quotaPanel} aria-label="本次生成额度">
              <Typography.Text type="secondary">本次预计消耗</Typography.Text>
              <span className={styles.quotaValue}>{estimatedCredits} 个视频额度</span>
              <Typography.Text type="secondary">当前可用：{quotaLabel}</Typography.Text>
              <Typography.Text type="secondary">
                提交后先预留额度；视频成功保存后才扣除，未完成会自动释放。
              </Typography.Text>
              {!quota.unlimited && quotaLoaded && !hasEnoughQuota && (
                <Alert type="warning" showIcon title="当前视频额度不足" />
              )}
              <Button
                type="primary"
                size="large"
                icon={<VideoCameraOutlined />}
                loading={submitting}
                disabled={!canGenerate || submitting}
                onClick={() => void submit()}
              >
                生成视频
              </Button>
            </aside>
          </div>
        </Card>

        <Card title={`生成记录 ${pagination.count} 条`}>
          <List
            loading={listLoading || loadedSubjectId !== subjectId}
            dataSource={visibleJobs}
            locale={{
              emptyText: <Empty description="还没有视频，完成上方设置后即可开始生成。" />,
            }}
            renderItem={(job) => (
              <List.Item>
                <div className={styles.record}>
                  <div className={styles.recordMeta}>
                    <Space wrap>
                      <Tag color={STATUS_COLORS[job.status]}>{STATUS_LABELS[job.status]}</Tag>
                      <Tag>{job.generation_mode === "text" ? "文字生成" : "图片生成"}</Tag>
                      <Tag>{job.duration_seconds} 秒</Tag>
                      <Tag>{job.aspect_ratio}</Tag>
                      <Tag>720P</Tag>
                    </Space>
                    <Typography.Paragraph className={styles.prompt} ellipsis={{ rows: 3 }}>
                      {job.prompt}
                    </Typography.Paragraph>
                    <Typography.Text type="secondary">
                      创建于 {createdAtLabel(job.created_at)}
                    </Typography.Text>
                    {job.status === "failed" && (
                      <Alert
                        style={{ marginTop: 12 }}
                        type="error"
                        showIcon
                        title={videoFailureMessage(job.safe_error_code)}
                      />
                    )}
                    {ACTIVE_STATUSES.has(job.status) && (
                      <Alert
                        style={{ marginTop: 12 }}
                        type="info"
                        showIcon
                        title={job.status === "queued" ? "正在等待生成" : "视频正在生成，请稍候"}
                      />
                    )}
                    <Space className={styles.recordActions} wrap>
                      {job.status === "succeeded" && job.video && (
                        <>
                          <Button
                            icon={<DownloadOutlined />}
                            loading={actionBusy === `download:${job.id}`}
                            disabled={Boolean(actionBusy)}
                            onClick={() => void download(job)}
                          >
                            下载
                          </Button>
                          <Button
                            icon={<SaveOutlined />}
                            loading={actionBusy === `save:${job.id}`}
                            disabled={Boolean(actionBusy) || job.video.is_subject_library}
                            onClick={() => void save(job)}
                          >
                            {job.video.is_subject_library ? "已保存到视频库" : "保存到视频库"}
                          </Button>
                        </>
                      )}
                      {["succeeded", "failed"].includes(job.status) && (
                        <Button
                          icon={<ReloadOutlined />}
                          loading={actionBusy === `regenerate:${job.id}`}
                          disabled={Boolean(actionBusy)}
                          onClick={() => void regenerate(job)}
                        >
                          重新生成
                        </Button>
                      )}
                    </Space>
                  </div>
                  {job.status === "succeeded" && job.video?.url && (
                    <video
                      className={styles.video}
                      src={job.video.url}
                      controls
                      preload="metadata"
                      aria-label="生成视频预览"
                    />
                  )}
                </div>
              </List.Item>
            )}
          />
          {pagination.count > PAGE_SIZE && (
            <div className={styles.pagination}>
              <Pagination
                aria-label="视频生成记录分页"
                current={page}
                pageSize={PAGE_SIZE}
                total={pagination.count}
                showSizeChanger={false}
                onChange={setPage}
              />
            </div>
          )}
        </Card>
      </Space>
    </main>
  );
}
