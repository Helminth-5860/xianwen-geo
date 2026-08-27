"use client";

import {
  ArrowRightOutlined,
  FundProjectionScreenOutlined,
  RadarChartOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Empty, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import { getReportHistory, type GeoReport } from "@/lib/geo-report-client";

const { Paragraph, Text, Title } = Typography;

type StrategyIndexState = Readonly<{
  subjectId: string;
  reports: GeoReport[];
  error: string;
}>;

export default function GeoStrategyIndexPage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [reportState, setReportState] = useState<StrategyIndexState>();
  const subjectId = subject?.id ?? "";

  useEffect(() => {
    let current = true;
    if (subjectLoading || !subjectId) return () => undefined;
    void getReportHistory(subjectId)
      .then((result) => {
        if (!current) return;
        setReportState({
          subjectId,
          reports: [...result.items].sort(
            (left, right) =>
              new Date(right.generated_at).getTime() - new Date(left.generated_at).getTime(),
          ),
          error: "",
        });
      })
      .catch((reason) => {
        if (current) {
          setReportState({ subjectId, reports: [], error: userMessage(reason) });
        }
      });

    return () => {
      current = false;
    };
  }, [subjectId, subjectLoading]);

  const state = reportState?.subjectId === subjectId ? reportState : undefined;
  const reports = state?.reports ?? [];

  if (subjectLoading || (subjectId && !state))
    return <Spin fullscreen description="正在加载优化策略" />;

  return (
    <main className="geo-dashboard">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">GEO OPTIMIZATION</Text>
          <Title level={2}>优化策略</Title>
          <Paragraph type="secondary">
            优化建议必须来自真实 GEO 报告。先确定问题，再生成优先级、行动计划和内容选题。
          </Paragraph>
        </div>
        <Button href="/workspace">返回 GEO 总览</Button>
      </section>

      {state?.error && <Alert type="error" showIcon message={state.error} />}

      {!subject ? (
        <Card>
          <Empty description="请先创建并选择当前主体">
            <Button type="primary" href="/subjects">
              进入主体与知识
            </Button>
          </Empty>
        </Card>
      ) : reports.length === 0 ? (
        <Card>
          <Empty description="当前主体还没有 GEO 报告，暂时无法生成有依据的优化策略。">
            <Button type="primary" href="/geo/detections" icon={<RadarChartOutlined />}>
              先完成 AI 可见度检测
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
            <Tag>可用报告 {reports.length}</Tag>
          </section>

          <Card title="选择 GEO 报告生成或查看策略">
            <div className="geo-report-list">
              {reports.slice(0, 8).map((report, index) => (
                <a key={report.id} href={`/geo/strategy/${report.id}`} className="geo-report-card">
                  <div>
                    <Space wrap>
                      <FundProjectionScreenOutlined />
                      <Text strong>{index === 0 ? "基于最新报告" : "基于历史报告"}</Text>
                      {index === 0 && <Tag color="blue">推荐</Tag>}
                    </Space>
                    <Title level={4}>GEO Score {report.summary.geo.score ?? "—"}</Title>
                    <Text type="secondary">
                      报告时间 {new Date(report.generated_at).toLocaleString("zh-CN")}
                    </Text>
                  </div>
                  <Space>
                    <Text type="secondary">进入策略工作台</Text>
                    <ArrowRightOutlined />
                  </Space>
                </a>
              ))}
            </div>
          </Card>
        </>
      )}
    </main>
  );
}
