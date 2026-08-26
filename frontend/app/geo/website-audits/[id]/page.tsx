"use client";

import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  GlobalOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Progress,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  getWebsiteAudit,
  type WebsiteAuditDetail,
  type WebsiteAuditIssue,
  websiteAuditStatusLabel,
} from "@/lib/website-audit-client";

const { Paragraph, Text, Title } = Typography;

const scoreLabels: Readonly<Record<string, string>> = {
  seo: "SEO",
  geo: "GEO",
  technical_health: "技术健康度",
  ai_readability: "AI 可读性",
  content_readiness: "内容准备度",
};

const semanticLabels: Readonly<Record<string, string>> = {
  entity_clarity: "主体实体清晰度",
  fact_density: "事实密度",
  citation_readiness: "内容可引用性",
  topic_coverage: "主题覆盖完整度",
  credibility: "可信度与证据",
  answer_readiness: "AI 回答准备度",
};

function scoreStatus(score: number | null) {
  if (score === null) return "normal" as const;
  if (score >= 80) return "success" as const;
  if (score >= 60) return "normal" as const;
  return "exception" as const;
}

function severityColor(severity: string) {
  if (severity === "critical") return "magenta";
  if (severity === "high") return "red";
  if (severity === "medium") return "orange";
  if (severity === "low") return "gold";
  return "default";
}

function severityLabel(severity: string) {
  const labels: Readonly<Record<string, string>> = {
    critical: "严重",
    high: "高风险",
    medium: "中风险",
    low: "低风险",
    info: "提示",
  };
  return labels[severity] ?? severity;
}

function categoryLabel(category: string) {
  const labels: Readonly<Record<string, string>> = {
    seo: "SEO",
    geo: "GEO",
    technical: "技术",
  };
  return labels[category] ?? category;
}

function stageDescription(audit: WebsiteAuditDetail) {
  if (["queued", "running"].includes(audit.status)) return "正在扫描官网与建立页面证据";
  if (["queued", "running"].includes(audit.browser_status)) return "正在执行移动端与桌面端浏览器检测";
  if (["queued", "running"].includes(audit.semantic_status)) return "正在进行 AI GEO 语义深度分析";
  if (audit.report.status === "complete") return "检测证据已完整，可以查看正式评分与问题明细";
  if (audit.report.status === "partial") return "部分检测层未完成，当前结果仅展示已有证据";
  return "检测已结束";
}

export default function WebsiteAuditDetailPage() {
  const params = useParams<{ id: string }>();
  const auditId = params.id;
  const [audit, setAudit] = useState<WebsiteAuditDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!auditId) return;
    try {
      const data = await getWebsiteAudit(auditId);
      setAudit(data);
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [auditId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!audit) return;
    const active =
      ["queued", "running"].includes(audit.status) ||
      ["queued", "running"].includes(audit.browser_status) ||
      ["queued", "running"].includes(audit.semantic_status);
    if (!active) return;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [audit, refresh]);

  const mainScores = useMemo(
    () =>
      audit
        ? Object.entries(audit.report.scores).map(([key, score]) => ({
            key,
            label: scoreLabels[key] ?? key,
            score,
          }))
        : [],
    [audit],
  );

  if (loading && !audit) return <Spin fullscreen description="正在加载官网检测报告" />;

  if (!audit) {
    return (
      <main className="geo-dashboard">
        <Alert type="error" showIcon message={error || "检测记录不存在"} />
        <Button href="/geo/website-audits" icon={<ArrowLeftOutlined />}>
          返回官网检测
        </Button>
      </main>
    );
  }

  const report = audit.report;
  const semantic = audit.semantic_result ?? {};
  const topicGaps = semantic.topic_gaps ?? [];
  const questionAssessments = semantic.question_assessments ?? [];
  const citeablePassages = semantic.citeable_passages ?? [];
  const isPending = report.status === "pending";

  return (
    <main className="geo-dashboard website-audit-page">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">WEBSITE AUDIT REPORT</Text>
          <Title level={2}>官网深度检测报告</Title>
          <Paragraph type="secondary">{audit.root_url}</Paragraph>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>
            刷新
          </Button>
          <Button href="/geo/website-audits" icon={<ArrowLeftOutlined />}>
            返回官网检测
          </Button>
        </Space>
      </section>

      {error && <Alert type="warning" showIcon message={error} />}

      <section className="website-audit-stage-card">
        <Card>
          <div className="website-audit-stage-head">
            <span>
              <Space>
                {report.status === "complete" ? (
                  <CheckCircleOutlined className="website-audit-stage-icon website-audit-stage-icon--success" />
                ) : isPending ? (
                  <ClockCircleOutlined className="website-audit-stage-icon" />
                ) : (
                  <ExclamationCircleOutlined className="website-audit-stage-icon website-audit-stage-icon--warning" />
                )}
                <Text strong>{stageDescription(audit)}</Text>
              </Space>
              <Text type="secondary">
                创建于 {new Date(audit.created_at).toLocaleString("zh-CN")}
              </Text>
            </span>
            <Space wrap>
              <Tag color={audit.status === "succeeded" ? "success" : "processing"}>
                整站扫描 · {websiteAuditStatusLabel(audit.status)}
              </Tag>
              <Tag color={audit.browser_status === "succeeded" ? "success" : "processing"}>
                浏览器 · {websiteAuditStatusLabel(audit.browser_status)}
              </Tag>
              <Tag color={audit.semantic_status === "succeeded" ? "purple" : "processing"}>
                AI 语义 · {websiteAuditStatusLabel(audit.semantic_status)}
              </Tag>
            </Space>
          </div>
          {report.missing_layers.length > 0 && report.status !== "pending" && (
            <Alert
              type="warning"
              showIcon
              message="检测证据未完整"
              description={`缺少：${report.missing_layers.join("、")}。当前页面不会把缺失层按 0 分计入最终评分。`}
            />
          )}
        </Card>
      </section>

      <section className="website-audit-score-hero">
        <Card className="website-audit-overall-score">
          <Text type="secondary">官网综合评分</Text>
          <div className="website-audit-overall-score__value">
            {report.overall_score === null ? "—" : report.overall_score}
          </div>
          <Text type="secondary">
            {report.overall_score === null ? "等待完整检测证据" : `评分版本 ${report.score_version}`}
          </Text>
        </Card>

        <div className="website-audit-score-grid">
          {mainScores.map((item) => (
            <Card key={item.key} size="small">
              <Text type="secondary">{item.label}</Text>
              <div className="website-audit-score-row">
                <Text strong>{item.score ?? "—"}</Text>
                <Progress
                  percent={item.score ?? 0}
                  showInfo={false}
                  status={scoreStatus(item.score)}
                  size="small"
                />
              </div>
            </Card>
          ))}
        </div>
      </section>

      {Object.keys(report.semantic_dimensions).length > 0 && (
        <Card title="GEO 语义六维评分">
          <div className="website-audit-semantic-grid">
            {Object.entries(report.semantic_dimensions).map(([key, score]) => (
              <div key={key} className="website-audit-semantic-item">
                <span>
                  <Text>{semanticLabels[key] ?? key}</Text>
                  <Text strong>{score}</Text>
                </span>
                <Progress percent={score} showInfo={false} size="small" status={scoreStatus(score)} />
              </div>
            ))}
          </div>
        </Card>
      )}

      <section className="website-audit-report-grid">
        <Card title="关键问题">
          {report.top_issues.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有需要优先处理的问题" />
          ) : (
            <Space direction="vertical" size="small" style={{ width: "100%" }}>
              {report.top_issues.map((issue: WebsiteAuditIssue) => (
                <div key={`${issue.check_key}-${issue.method}`} className="website-audit-issue-row">
                  <Space wrap>
                    <Tag>{categoryLabel(issue.category)}</Tag>
                    <Tag color={severityColor(issue.severity)}>{severityLabel(issue.severity)}</Tag>
                    <Text strong>{issue.title}</Text>
                  </Space>
                  <Text type="secondary">{issue.summary}</Text>
                  {issue.recommendation && <Text>建议：{issue.recommendation}</Text>}
                </div>
              ))}
            </Space>
          )}
        </Card>

        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Card title="检测证据">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="抓取页面">{report.evidence.fetched_pages}</Descriptions.Item>
              <Descriptions.Item label="抓取失败">{report.evidence.failed_pages}</Descriptions.Item>
              <Descriptions.Item label="浏览器完成">{report.evidence.browser_completed}</Descriptions.Item>
              <Descriptions.Item label="浏览器失败">{report.evidence.browser_failed}</Descriptions.Item>
              <Descriptions.Item label="AI 语义页面">{report.evidence.semantic_pages}</Descriptions.Item>
              <Descriptions.Item label="AI 评估问题">{report.evidence.semantic_questions}</Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="问题回答覆盖">
            <div className="website-audit-coverage-grid">
              <span>
                <Text type="secondary">总问题</Text>
                <Text strong>{report.semantic_summary.question_coverage.total}</Text>
              </span>
              <span>
                <Text type="secondary">完整回答</Text>
                <Text strong>{report.semantic_summary.question_coverage.answered}</Text>
              </span>
              <span>
                <Text type="secondary">部分回答</Text>
                <Text strong>{report.semantic_summary.question_coverage.partial}</Text>
              </span>
              <span>
                <Text type="secondary">缺失</Text>
                <Text strong>{report.semantic_summary.question_coverage.missing}</Text>
              </span>
            </div>
          </Card>
        </Space>
      </section>

      {Object.keys(report.browser_metrics).length > 0 && (
        <Card title="浏览器性能">
          <div className="website-audit-browser-grid">
            {Object.entries(report.browser_metrics).map(([profile, metrics]) => (
              <Card key={profile} size="small" title={profile === "mobile" ? "移动端" : profile === "desktop" ? "桌面端" : profile}>
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="样本页面">{metrics.sample_count}</Descriptions.Item>
                  <Descriptions.Item label="TTFB P75">{metrics.ttfb_p75_ms ?? "—"} ms</Descriptions.Item>
                  <Descriptions.Item label="LCP P75">{metrics.lcp_p75_ms ?? "—"} ms</Descriptions.Item>
                  <Descriptions.Item label="CLS P75">{metrics.cls_p75 ?? "—"}</Descriptions.Item>
                  <Descriptions.Item label="TBT P75">{metrics.tbt_p75_ms ?? "—"} ms</Descriptions.Item>
                  <Descriptions.Item label="失败请求">{metrics.failed_requests}</Descriptions.Item>
                </Descriptions>
              </Card>
            ))}
          </div>
        </Card>
      )}

      {(topicGaps.length > 0 || questionAssessments.length > 0 || citeablePassages.length > 0) && (
        <Collapse
          items={[
            {
              key: "topic-gaps",
              label: `主题缺口（${topicGaps.length}）`,
              children:
                topicGaps.length === 0 ? (
                  <Text type="secondary">暂无主题缺口。</Text>
                ) : (
                  <Space direction="vertical" style={{ width: "100%" }}>
                    {topicGaps.map((gap, index) => (
                      <div key={`${gap.topic}-${index}`} className="website-audit-issue-row">
                        <Space wrap>
                          <Tag color={severityColor(gap.importance)}>{severityLabel(gap.importance)}</Tag>
                          <Text strong>{gap.topic}</Text>
                        </Space>
                        <Text type="secondary">{gap.reason}</Text>
                        <Text>建议：{gap.suggested_content}</Text>
                      </div>
                    ))}
                  </Space>
                ),
            },
            {
              key: "questions",
              label: `问题覆盖明细（${questionAssessments.length}）`,
              children: (
                <Space direction="vertical" style={{ width: "100%" }}>
                  {questionAssessments.map((item, index) => (
                    <div key={`${item.question}-${index}`} className="website-audit-question-row">
                      <span>
                        <Tag color={item.status === "answered" ? "success" : item.status === "partial" ? "warning" : "error"}>
                          {item.status === "answered" ? "已回答" : item.status === "partial" ? "部分覆盖" : "缺失"}
                        </Tag>
                        <Text strong>{item.question}</Text>
                      </span>
                      <Progress percent={item.coverage_score} size="small" />
                      {item.answer_summary && <Text type="secondary">{item.answer_summary}</Text>}
                      {item.missing_points.length > 0 && <Text>缺少：{item.missing_points.join("、")}</Text>}
                    </div>
                  ))}
                </Space>
              ),
            },
            {
              key: "passages",
              label: `可引用内容（${citeablePassages.length}）`,
              children: (
                <Space direction="vertical" style={{ width: "100%" }}>
                  {citeablePassages.map((item, index) => (
                    <div key={`${item.url}-${index}`} className="website-audit-quote-row">
                      <Space>
                        <GlobalOutlined />
                        <Text type="secondary" ellipsis={{ tooltip: item.url }}>
                          {item.url}
                        </Text>
                      </Space>
                      <Paragraph>“{item.excerpt}”</Paragraph>
                      <Text type="secondary">{item.reason}</Text>
                    </div>
                  ))}
                </Space>
              ),
            },
          ]}
        />
      )}

      <Card title="页面级明细">
        <Table
          rowKey="id"
          size="small"
          pagination={{ pageSize: 10 }}
          dataSource={audit.pages}
          columns={[
            {
              title: "页面",
              dataIndex: "title",
              render: (value: string, row) => (
                <span className="website-audit-page-cell">
                  <Text strong>{value || row.url}</Text>
                  <Text type="secondary" ellipsis={{ tooltip: row.url }}>
                    {row.url}
                  </Text>
                </span>
              ),
            },
            { title: "状态", dataIndex: "http_status", width: 90 },
            { title: "响应", dataIndex: "response_ms", width: 100, render: (value) => (value === null ? "—" : `${value} ms`) },
            { title: "内链", dataIndex: "internal_links_count", width: 80 },
            { title: "外链", dataIndex: "external_links_count", width: 80 },
            { title: "正文字符", dataIndex: "text_characters", width: 100 },
          ]}
        />
      </Card>
    </main>
  );
}
