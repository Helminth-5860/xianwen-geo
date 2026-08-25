"use client";

import { ArrowRightOutlined, BarChartOutlined, RadarChartOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import { getReportHistory, type GeoReport } from "@/lib/geo-report-client";

const { Paragraph, Text, Title } = Typography;
const value = (input: string | null | undefined) => input ?? "—";

export default function GeoReportsIndexPage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [reports, setReports] = useState<GeoReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    if (subjectLoading) return () => undefined;
    if (!subject) return () => undefined;
    void getReportHistory(subject.id)
      .then((result) => {
        if (!current) return;
        setReports(
          [...result.items].sort(
            (left, right) =>
              new Date(right.generated_at).getTime() - new Date(left.generated_at).getTime(),
          ),
        );
      })
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    return () => {
      current = false;
    };
  }, [subject, subjectLoading]);

  const latest = reports[0] ?? null;
  const scoredReports = useMemo(
    () => reports.filter((report) => report.summary.geo.score !== null),
    [reports],
  );

  if (subjectLoading || (subject && loading))
    return <Spin fullscreen description="正在加载 GEO 报告" />;

  return (
    <main className="geo-dashboard">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">GEO INSIGHTS</Text>
          <Title level={2}>GEO 报告与洞察</Title>
          <Paragraph type="secondary">
            汇总真实检测结果，查看 GEO Score、AI 曝光、提及、推荐、模型表现和历史变化。
          </Paragraph>
        </div>
        <Space wrap>
          <Button href="/workspace">返回 GEO 总览</Button>
          <Button type="primary" href="/geo/detections" icon={<RadarChartOutlined />}>
            新建检测
          </Button>
        </Space>
      </section>

      {error && <Alert type="error" showIcon message={error} />}

      {!subject ? (
        <Card>
          <Empty description="请先创建并选择当前主体">
            <Button type="primary" href="/subjects">
              进入主体与知识
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
            <Space wrap>
              <Tag>历史报告 {reports.length}</Tag>
              {subject.retest_required && <Tag color="orange">主体变更后需复测</Tag>}
            </Space>
          </section>

          {latest ? (
            <section className="geo-metric-grid" aria-label="最新 GEO 报告指标">
              <Card>
                <Text type="secondary">最新 GEO Score</Text>
                <div className="geo-metric-grid__value">{value(latest.summary.geo.score)}</div>
                <Text type="secondary">等级 {latest.summary.geo.grade || "—"}</Text>
              </Card>
              <Card>
                <Text type="secondary">AI 曝光指数</Text>
                <div className="geo-metric-grid__value">
                  {value(latest.summary.exposure.exposure_index)}
                </div>
                <Text type="secondary">{latest.summary.exposure.grade}</Text>
              </Card>
              <Card>
                <Text type="secondary">品牌提及</Text>
                <div className="geo-metric-grid__value">
                  {value(latest.summary.exposure.mention_rate_score)}
                </div>
                <Text type="secondary">最新报告指标</Text>
              </Card>
              <Card>
                <Text type="secondary">推荐表现</Text>
                <div className="geo-metric-grid__value">
                  {value(latest.summary.exposure.recommendation_rate_score)}
                </div>
                <Text type="secondary">最新报告指标</Text>
              </Card>
            </section>
          ) : null}

          <Card title="历史检测报告">
            {reports.length === 0 ? (
              <Empty description="当前主体还没有 GEO 报告">
                <Button type="primary" href="/geo/detections" icon={<BarChartOutlined />}>
                  开始首次检测
                </Button>
              </Empty>
            ) : (
              <div className="geo-report-list">
                {reports.map((report, index) => (
                  <a key={report.id} href={`/geo/reports/${report.id}`} className="geo-report-card">
                    <div>
                      <Space wrap>
                        <Text strong>{index === 0 ? "最新报告" : `历史报告 ${index + 1}`}</Text>
                        {report.retest_mode && (
                          <Tag>{report.retest_mode === "quick" ? "快速复测" : "调整复测"}</Tag>
                        )}
                        <Tag color={report.summary.geo.status === "formal" ? "blue" : "default"}>
                          {report.summary.geo.status === "formal" ? "正式结果" : "参考结果"}
                        </Tag>
                      </Space>
                      <Title level={4}>GEO Score {value(report.summary.geo.score)}</Title>
                      <Space wrap>
                        <Text type="secondary">
                          曝光 {value(report.summary.exposure.exposure_index)}
                        </Text>
                        <Text type="secondary">
                          提及 {value(report.summary.exposure.mention_rate_score)}
                        </Text>
                        <Text type="secondary">
                          推荐 {value(report.summary.exposure.recommendation_rate_score)}
                        </Text>
                      </Space>
                      <Text type="secondary" className="geo-report-card__time">
                        {new Date(report.generated_at).toLocaleString("zh-CN")}
                      </Text>
                    </div>
                    <ArrowRightOutlined />
                  </a>
                ))}
              </div>
            )}
          </Card>

          {scoredReports.length > 1 && (
            <Text type="secondary">
              已积累 {scoredReports.length} 次可评分报告，可通过报告内的对比与复测功能验证优化效果。
            </Text>
          )}
        </>
      )}
    </main>
  );
}
