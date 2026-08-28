"use client";

import { ArrowRightOutlined, RadarChartOutlined, SyncOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import { getReportHistory, type GeoReport } from "@/lib/geo-report-client";

const { Paragraph, Text, Title } = Typography;

export default function GeoRetestIndexPage() {
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

  if (subjectLoading || (subject && loading))
    return <Spin fullscreen description="正在加载复测验证" />;

  const latest = reports[0] ?? null;

  return (
    <main className="geo-dashboard">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">GEO 复测</Text>
          <Title level={2}>复测验证</Title>
          <Paragraph type="secondary">
            GEO
            优化不是“生成内容就结束”。完成主体或内容调整后，用同一套报告基线复测，确认指标是否真实提升。
          </Paragraph>
        </div>
        <Button href="/workspace">返回 GEO 总览</Button>
      </section>

      {error && <Alert type="error" showIcon message={error} />}

      {!subject ? (
        <Card>
          <Empty description="请先创建并选择当前主体">
            <Button type="primary" href="/subjects">
              进入主体档案
            </Button>
          </Empty>
        </Card>
      ) : !latest ? (
        <Card>
          <Empty description="当前主体还没有首次 GEO 检测，暂时没有可复测的基线。">
            <Button type="primary" href="/geo/detections" icon={<RadarChartOutlined />}>
              先建立首次检测基线
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
              <Tag>已有报告 {reports.length}</Tag>
              {subject.retest_required ? (
                <Tag color="orange">主体资料已变化，建议复测</Tag>
              ) : (
                <Tag color="green">已有可比较基线</Tag>
              )}
            </Space>
          </section>

          <section className="geo-dashboard__main-grid">
            <Card title="当前复测基线">
              <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <div>
                  <Text type="secondary">最新报告</Text>
                  <Title level={3}>GEO 评分 {latest.summary.geo.score ?? "—"}</Title>
                  <Space wrap>
                    <Text type="secondary">曝光 {latest.summary.exposure.exposure_index}</Text>
                    <Text type="secondary">提及 {latest.summary.exposure.mention_rate_score}</Text>
                    <Text type="secondary">
                      推荐 {latest.summary.exposure.recommendation_rate_score}
                    </Text>
                  </Space>
                </div>
                <Alert
                  type={subject.retest_required ? "warning" : "info"}
                  showIcon
                  message={
                    subject.retest_required ? "主体正式资料已发生变化" : "可以按优化节奏安排复测"
                  }
                  description={
                    subject.retest_required
                      ? "当前主体资料已更新，进入最新报告后选择复测方式。"
                      : "完成一轮优化后，进入最新报告发起快速复测或调整复测，并与基线比较。"
                  }
                />
                <Button type="primary" href={`/geo/reports/${latest.id}`} icon={<SyncOutlined />}>
                  进入报告并发起复测
                </Button>
              </Space>
            </Card>

            <Card title="验证原则">
              <Space direction="vertical" size="middle">
                <Text>1. 先保留基线报告，不覆盖历史结果。</Text>
                <Text>2. 优先使用相同问题、相同模型做可比复测。</Text>
                <Text>3. 对比 GEO 评分、曝光、提及、推荐及各模型变化。</Text>
                <Text>4. 指标没有改善时，回到策略和内容环节继续迭代。</Text>
              </Space>
            </Card>
          </section>

          {reports.length > 1 && (
            <Card title="历史验证记录">
              <div className="geo-report-list">
                {reports.slice(0, 6).map((report) => (
                  <a key={report.id} href={`/geo/reports/${report.id}`} className="geo-report-card">
                    <div>
                      <Text strong>GEO 评分 {report.summary.geo.score ?? "—"}</Text>
                      <Text type="secondary">
                        {new Date(report.generated_at).toLocaleString("zh-CN")}
                      </Text>
                    </div>
                    <ArrowRightOutlined />
                  </a>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
