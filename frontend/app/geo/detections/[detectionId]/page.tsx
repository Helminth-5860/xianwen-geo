"use client";

import {
  Alert,
  Button,
  Card,
  Col,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { aiModelDisplayName } from "@/lib/product-copy";
import {
  getDetectionJob,
  getDetectionModelProgress,
  terminalDetectionStatuses,
  type DetectionStatus,
  type GeoDetectionJob,
  type GeoModelProgress,
} from "@/lib/geo-detection-client";

export const DETECTION_POLL_INTERVAL_MS = 3000;
export const DETECTION_RUNNING_POLL_INTERVAL_MS = 2000;
export const DETECTION_REQUEST_TIMEOUT_MS = 9000;
export const DETECTION_QUEUED_MODELS_POLL_INTERVAL_MS = 15000;
export const DETECTION_STALE_QUEUE_MS = 60000;

const DETECTION_MAX_RETRY_INTERVAL_MS = 12000;
const CLOCK_REFRESH_INTERVAL_MS = 5000;

const statusPresentation: Record<DetectionStatus, { label: string; color: string }> = {
  queued: { label: "等待检测", color: "default" },
  running: { label: "检测中", color: "processing" },
  partial: { label: "部分完成", color: "warning" },
  succeeded: { label: "已完成", color: "success" },
  failed: { label: "未完成", color: "error" },
  cancelled: { label: "已取消", color: "default" },
};

const settlementLabels = {
  open: "待结算",
  partially_settled: "部分结算",
  settled: "已结算",
} as const;

function StatusTag({ status }: { status: DetectionStatus }) {
  const presentation = statusPresentation[status];
  return <Tag color={presentation.color}>{presentation.label}</Tag>;
}

function formatElapsed(milliseconds: number) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  if (totalSeconds < 60) return `${totalSeconds} 秒`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes} 分 ${seconds} 秒`;
  const hours = Math.floor(minutes / 60);
  return `${hours} 小时 ${minutes % 60} 分`;
}

function formatRefreshTime(timestamp: number) {
  return new Date(timestamp).toLocaleTimeString("zh-CN", { hour12: false });
}

function requestErrorMessage(reason: unknown, timedOut: boolean) {
  if (timedOut || (reason instanceof Error && reason.name === "AbortError")) {
    return "数据更新时间较长，系统会自动再次尝试。";
  }
  return userMessage(reason);
}

export default function DetectionProgressPage() {
  const { detectionId } = useParams<{ detectionId: string }>();
  const [job, setJob] = useState<GeoDetectionJob>();
  const [models, setModels] = useState<GeoModelProgress[]>([]);
  const [error, setError] = useState("");
  const [modelsError, setModelsError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [lastSuccessfulRefreshAt, setLastSuccessfulRefreshAt] = useState<number>();
  const [clock, setClock] = useState(() => Date.now());
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), CLOCK_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let active = true;
    let pollTimer: number | undefined;
    let jobController: AbortController | undefined;
    let modelController: AbortController | undefined;
    let latestStatus: DetectionStatus | undefined;
    let failureCount = 0;
    let lastModelsRequestAt = 0;
    let modelsRequestInFlight = false;
    let hasAttemptedModels = false;

    const schedule = (delay: number, poll: () => Promise<void>) => {
      if (!active) return;
      pollTimer = window.setTimeout(() => void poll(), delay);
    };

    const loadModels = async (status: DetectionStatus, force = false) => {
      const now = Date.now();
      const minimumInterval = status === "queued" ? DETECTION_QUEUED_MODELS_POLL_INTERVAL_MS : 0;
      if (modelsRequestInFlight || (!force && now - lastModelsRequestAt < minimumInterval)) {
        return;
      }

      modelsRequestInFlight = true;
      hasAttemptedModels = true;
      lastModelsRequestAt = now;
      const controller = new AbortController();
      modelController = controller;
      let timedOut = false;
      const timeout = window.setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, DETECTION_REQUEST_TIMEOUT_MS);

      try {
        const result = await getDetectionModelProgress(detectionId, controller.signal);
        if (!active) return;
        setModels(result.items);
        setModelsError("");
      } catch (reason) {
        if (!active) return;
        setModelsError(requestErrorMessage(reason, timedOut));
      } finally {
        window.clearTimeout(timeout);
        if (modelController === controller) modelController = undefined;
        modelsRequestInFlight = false;
      }
    };

    const poll = async () => {
      if (!active) return;
      setRefreshing(true);
      const controller = new AbortController();
      jobController = controller;
      let timedOut = false;
      let succeeded = false;
      const timeout = window.setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, DETECTION_REQUEST_TIMEOUT_MS);

      try {
        const nextJob = await getDetectionJob(detectionId, controller.signal);
        if (!active) return;
        succeeded = true;
        failureCount = 0;
        latestStatus = nextJob.status;
        setJob(nextJob);
        setError("");
        setLastSuccessfulRefreshAt(Date.now());
        void loadModels(
          nextJob.status,
          !hasAttemptedModels || terminalDetectionStatuses.has(nextJob.status),
        );
      } catch (reason) {
        if (!active) return;
        failureCount += 1;
        setError(requestErrorMessage(reason, timedOut));
      } finally {
        window.clearTimeout(timeout);
        if (jobController === controller) jobController = undefined;
        if (!active) return;
        setRefreshing(false);

        if (latestStatus && terminalDetectionStatuses.has(latestStatus)) return;
        const delay = succeeded
          ? latestStatus === "running"
            ? DETECTION_RUNNING_POLL_INTERVAL_MS
            : DETECTION_POLL_INTERVAL_MS
          : Math.min(
              DETECTION_POLL_INTERVAL_MS * 2 ** Math.max(0, failureCount - 1),
              DETECTION_MAX_RETRY_INTERVAL_MS,
            );
        schedule(delay, poll);
      }
    };

    void poll();
    return () => {
      active = false;
      if (pollTimer !== undefined) window.clearTimeout(pollTimer);
      jobController?.abort();
      modelController?.abort();
    };
  }, [detectionId, retryVersion]);

  const queueElapsed =
    job?.status === "queued" && clock
      ? Math.max(0, clock - new Date(job.queued_at).getTime())
      : undefined;
  const retryNow = () => {
    setError("");
    setModelsError("");
    setRetryVersion((current) => current + 1);
  };

  if (!job && !error) return <Spin fullscreen description="正在恢复检测进度" />;

  return (
    <main className="page-shell">
      {error && (
        <Alert
          type="error"
          showIcon
          title={job ? "检测进度暂未更新，系统会自动再次尝试" : "暂时无法查看检测进度"}
          description={error}
          action={<Button onClick={retryNow}>重新查看</Button>}
        />
      )}
      {job && (
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
          <Space wrap align="baseline">
            <Typography.Title level={2}>GEO 检测进度</Typography.Title>
            <StatusTag status={job.status} />
            {lastSuccessfulRefreshAt && (
              <Typography.Text type="secondary">
                最近更新：{formatRefreshTime(lastSuccessfulRefreshAt)}
              </Typography.Text>
            )}
          </Space>
          {job.status === "queued" && job.queue_position !== null && (
            <Alert
              type="info"
              showIcon
              title={`当前等待顺序：${job.queue_position}`}
              description={
                queueElapsed === undefined ? undefined : `已等待 ${formatElapsed(queueElapsed)}`
              }
            />
          )}
          {job.status === "queued" &&
            queueElapsed !== undefined &&
            queueElapsed >= DETECTION_STALE_QUEUE_MS && (
              <Alert
                type="warning"
                showIcon
                title="检测等待时间较长"
                description="系统仍在自动检查；检测服务繁忙时可能需要多等一会儿。"
              />
            )}
          {job.status === "failed" && (
            <Alert type="error" showIcon title="检测未能完成，未完成部分的检测点已退还" />
          )}
          {job.status === "partial" && (
            <Alert type="warning" showIcon title="部分模型检测未成功，已按实际完成数量结算" />
          )}
          {job.status === "cancelled" && (
            <Alert type="warning" showIcon title="检测已取消，未消耗的检测点已释放" />
          )}

          <Card title="总体进度" extra={refreshing ? "正在刷新" : undefined}>
            <Progress
              percent={job.progress_percent}
              status={job.status === "failed" ? "exception" : undefined}
            />
            <Typography.Text type="secondary">
              已完成 {job.completed_calls} / {job.planned_detection_points} 项检测
            </Typography.Text>
          </Card>

          <Card title={`各模型检测进度（共 ${job.planned_model_count} 个）`}>
            {modelsError && (
              <Alert
                type="warning"
                showIcon
                title={
                  terminalDetectionStatuses.has(job.status)
                    ? "模型明细暂时未更新"
                    : "模型明细暂时未更新，系统会自动再次尝试"
                }
                description={modelsError}
                action={
                  terminalDetectionStatuses.has(job.status) ? (
                    <Button onClick={retryNow}>重新加载明细</Button>
                  ) : undefined
                }
                style={{ marginBottom: 16 }}
              />
            )}
            <Row gutter={[16, 16]}>
              {models.map((model) => (
                <Col xs={24} md={12} xl={6} key={model.model_id}>
                  <Card
                    size="small"
                    title={aiModelDisplayName(model.model_key)}
                    extra={<StatusTag status={model.status} />}
                  >
                    <Progress
                      size="small"
                      percent={Math.floor((model.completed_calls * 100) / model.planned_calls)}
                      status={model.status === "failed" ? "exception" : undefined}
                    />
                    <Typography.Paragraph type="secondary" style={{ marginBottom: 4 }}>
                      检测进度：{model.completed_calls} / {model.planned_calls}
                    </Typography.Paragraph>
                    <Typography.Text type="secondary">
                      成功 {model.successful_calls} · 失败 {model.failed_calls} · 取消{" "}
                      {model.cancelled_calls}
                    </Typography.Text>
                  </Card>
                </Col>
              ))}
            </Row>
          </Card>

          <Card title="检测点结算" extra={<Tag>{settlementLabels[job.quota.status]}</Tag>}>
            <Row gutter={16}>
              <Col xs={24} sm={8}>
                <Statistic title="预计／预留" value={job.quota.held} suffix="点" />
              </Col>
              <Col xs={24} sm={8}>
                <Statistic title="实际扣除" value={job.quota.consumed} suffix="点" />
              </Col>
              <Col xs={24} sm={8}>
                <Statistic title="返还／释放" value={job.quota.released} suffix="点" />
              </Col>
            </Row>
          </Card>

          {terminalDetectionStatuses.has(job.status) && (
            <Space>
              <Link href={`/geo/detections/${job.id}/report`}>
                <Button type="primary">查看检测报告</Button>
              </Link>
              <Link href={`/subjects/${job.subject_id}`}>
                <Button>返回主体</Button>
              </Link>
              <Button onClick={retryNow}>刷新最终状态</Button>
            </Space>
          )}
        </Space>
      )}
    </main>
  );
}
