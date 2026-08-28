"use client";

import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  GlobalOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Empty, Input, Progress, Space, Spin, Tag, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  createWebsiteAudit,
  getWebsiteAudit,
  getWebsiteAuditHistory,
  type WebsiteAuditSummary,
  websiteAuditStatusLabel,
} from "@/lib/website-audit-client";

const { Paragraph, Text, Title } = Typography;

function stageProgress(audit: WebsiteAuditSummary | null) {
  if (!audit) return 0;
  if (audit.status === "failed") return 100;
  if (audit.status !== "succeeded") return audit.status === "running" ? 20 : 8;
  if (audit.browser_status === "queued" || audit.browser_status === "running") return 45;
  if (["failed", "partial"].includes(audit.browser_status)) return 60;
  if (audit.browser_status !== "succeeded") return 55;
  if (audit.semantic_status === "queued" || audit.semantic_status === "running") return 78;
  if (audit.semantic_status === "failed") return 92;
  if (audit.semantic_status === "succeeded") return 100;
  return 70;
}

function stageTag(label: string, status: string) {
  const color =
    status === "succeeded"
      ? "success"
      : status === "failed"
        ? "error"
        : status === "running"
          ? "processing"
          : status === "partial"
            ? "warning"
            : "default";
  return (
    <Tag color={color}>
      {label} · {websiteAuditStatusLabel(status)}
    </Tag>
  );
}

export default function WebsiteAuditsPage() {
  const router = useRouter();
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [history, setHistory] = useState<WebsiteAuditSummary[]>([]);
  const [current, setCurrent] = useState<WebsiteAuditSummary | null>(null);
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    if (subjectLoading) return () => undefined;
    if (!subject) {
      setHistory([]);
      setCurrent(null);
      return () => undefined;
    }
    setLoading(true);
    setError("");
    void getWebsiteAuditHistory(subject.id)
      .then((rows) => {
        if (!alive) return;
        const sorted = [...rows].sort(
          (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
        );
        setHistory(sorted);
        setCurrent(sorted[0] ?? null);
        if (!url && sorted[0]?.root_url) setUrl(sorted[0].root_url);
      })
      .catch((reason) => {
        if (alive) setError(userMessage(reason));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [subject, subjectLoading]);

  useEffect(() => {
    if (!current) return;
    const active =
      ["queued", "running"].includes(current.status) ||
      ["queued", "running"].includes(current.browser_status) ||
      ["queued", "running"].includes(current.semantic_status);
    if (!active) return;
    let alive = true;
    const timer = window.setInterval(() => {
      void getWebsiteAudit(current.id)
        .then((detail) => {
          if (!alive) return;
          setCurrent(detail);
          setHistory((rows) => rows.map((row) => (row.id === detail.id ? detail : row)));
        })
        .catch(() => undefined);
    }, 3000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [current?.id, current?.status, current?.browser_status, current?.semantic_status]);

  const progress = useMemo(() => stageProgress(current), [current]);

  const start = async () => {
    if (!subject || !url.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      const created = await createWebsiteAudit(subject.id, url.trim());
      router.push(`/geo/website-audits/${created.id}`);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  if (subjectLoading || (subject && loading)) {
    return <Spin fullscreen description="正在加载官网检测" />;
  }

  return (
    <main className="geo-dashboard website-audit-page">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">官网检测</Text>
          <Title level={2}>官网检测</Title>
          <Paragraph type="secondary">
            深度扫描官网的 SEO、GEO、浏览器渲染与 AI 内容准备度，定位影响搜索与生成式搜索理解的问题。
          </Paragraph>
        </div>
        <Button href="/geo/detections">返回主体检测</Button>
      </section>

      {error && <Alert type="warning" showIcon message={error} />}

      {!subject ? (
        <Card>
          <Empty description="请先创建并选择当前主体">
            <Button type="primary" href="/subjects">
              进入主体档案
            </Button>
          </Empty>
        </Card>
      ) : (
        <>
          <section className="geo-dashboard__subject-bar">
            <div>
              <Text type="secondary">当前主体</Text>
              <Title level={3}>{subject.official_name || subject.subject_type.name}</Title>
            </div>
            <Tag color="blue">官网深度检测</Tag>
          </section>

          <section className="website-audit-launch-grid">
            <Card title="开始官网检测" className="website-audit-launch-card">
              <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <Text type="secondary">输入当前主体的官网首页地址。</Text>
                <Input
                  size="large"
                  prefix={<GlobalOutlined />}
                  placeholder="输入当前主体的官网地址"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  onPressEnter={() => void start()}
                />
                <Alert
                  type="info"
                  showIcon
                  message="一次检测会依次完成整站扫描、SEO/GEO 规则、浏览器渲染和 AI 语义分析。"
                />
                <Button
                  type="primary"
                  size="large"
                  icon={<GlobalOutlined />}
                  loading={submitting}
                  disabled={!url.trim()}
                  onClick={() => void start()}
                >
                  开始检测
                </Button>
              </Space>
            </Card>

            <Card title="当前检测">
              {!current ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="还没有官网检测记录，请输入官网地址开始检测"
                />
              ) : (
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  <div className="website-audit-current-head">
                    <span>
                      <Text strong ellipsis={{ tooltip: current.root_url }}>
                        {current.root_host || current.root_url}
                      </Text>
                      <Text type="secondary">
                        {new Date(current.created_at).toLocaleString("zh-CN")}
                      </Text>
                    </span>
                    {["queued", "running"].includes(current.status) ? (
                      <LoadingOutlined />
                    ) : current.status === "succeeded" ? (
                      <CheckCircleOutlined />
                    ) : (
                      <ClockCircleOutlined />
                    )}
                  </div>
                  <Progress percent={progress} status={current.status === "failed" ? "exception" : "active"} />
                  <Space wrap>
                    {stageTag("整站扫描", current.status)}
                    {stageTag("浏览器", current.browser_status)}
                    {stageTag("AI 语义", current.semantic_status)}
                  </Space>
                  <Text type="secondary">
                    已抓取 {current.fetched_count} 页 · 发现 {current.discovered_count} 个网页地址
                  </Text>
                  <Button onClick={() => router.push(`/geo/website-audits/${current.id}`)}>
                    查看检测详情
                  </Button>
                </Space>
              )}
            </Card>
          </section>

          <Card title="最近检测">
            {history.length === 0 ? (
              <Text type="secondary">完成一次官网检测后，历史记录会显示在这里。</Text>
            ) : (
              <div className="website-audit-history">
                {history.slice(0, 10).map((audit) => (
                  <a key={audit.id} href={`/geo/website-audits/${audit.id}`} className="geo-report-row">
                    <span>
                      <Space wrap>
                        <Text strong>{audit.root_host || audit.root_url}</Text>
                        <Tag>{websiteAuditStatusLabel(audit.status)}</Tag>
                        {audit.semantic_status === "succeeded" && <Tag color="purple">AI 语义完成</Tag>}
                      </Space>
                      <Text type="secondary">
                        {audit.fetched_count} 页 · {new Date(audit.created_at).toLocaleString("zh-CN")}
                      </Text>
                    </span>
                    <ArrowRightOutlined />
                  </a>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </main>
  );
}
