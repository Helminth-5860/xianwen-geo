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
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  getDetectionProgress,
  terminalDetectionStatuses,
  type DetectionStatus,
  type GeoDetectionJob,
  type GeoModelProgress,
} from "@/lib/geo-detection-client";

export const DETECTION_POLL_INTERVAL_MS = 3000;

const statusPresentation: Record<DetectionStatus, { label: string; color: string }> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "检测中", color: "processing" },
  partial: { label: "部分完成", color: "warning" },
  succeeded: { label: "已完成", color: "success" },
  failed: { label: "失败", color: "error" },
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

export default function DetectionProgressPage() {
  const { detectionId } = useParams<{ detectionId: string }>();
  const [job, setJob] = useState<GeoDetectionJob>();
  const [models, setModels] = useState<GeoModelProgress[]>([]);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const result = await getDetectionProgress(detectionId);
      setJob(result.job);
      setModels(result.models);
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setRefreshing(false);
    }
  }, [detectionId]);

  useEffect(() => {
    let current = true;
    const fetchCurrent = async () => {
      if (!current) return;
      await load();
    };
    void fetchCurrent();
    return () => {
      current = false;
    };
  }, [load]);

  useEffect(() => {
    if (!job || terminalDetectionStatuses.has(job.status)) return;
    const timer = window.setTimeout(() => void load(), DETECTION_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [job, load]);

  if (!job && !error) return <Spin fullscreen description="正在恢复检测进度" />;

  return (
    <main className="page-shell">
      {error && (
        <Alert
          type="error"
          showIcon
          title="检测进度加载失败"
          description={error}
          action={<Button onClick={() => void load()}>重试</Button>}
        />
      )}
      {job && (
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
          <Space wrap align="baseline">
            <Typography.Title level={2}>GEO 检测进度</Typography.Title>
            <StatusTag status={job.status} />
          </Space>
          {job.status === "queued" && job.queue_position && (
            <Alert type="info" showIcon title={`当前排队位置：${job.queue_position}`} />
          )}
          {job.status === "failed" && (
            <Alert type="error" showIcon title="检测未能完成，失败调用已释放检测点" />
          )}
          {job.status === "partial" && (
            <Alert type="warning" showIcon title="部分模型调用未成功，已按实际成功数量结算" />
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
              已终结 {job.completed_calls} / {job.planned_detection_points} 次模型调用
            </Typography.Text>
          </Card>

          <Card title={`模型状态（${models.length}/${job.planned_model_count}）`}>
            <Row gutter={[16, 16]}>
              {models.map((model) => (
                <Col xs={24} md={12} xl={6} key={model.model_id}>
                  <Card
                    size="small"
                    title={model.model_key}
                    extra={<StatusTag status={model.status} />}
                  >
                    <Progress
                      size="small"
                      percent={Math.floor((model.completed_calls * 100) / model.planned_calls)}
                      status={model.status === "failed" ? "exception" : undefined}
                    />
                    <Typography.Paragraph type="secondary" style={{ marginBottom: 4 }}>
                      调用进度：{model.completed_calls} / {model.planned_calls}
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
                <Statistic title="计划／冻结" value={job.quota.held} suffix="点" />
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
              <Button onClick={() => void load()}>刷新最终状态</Button>
            </Space>
          )}
        </Space>
      )}
    </main>
  );
}
