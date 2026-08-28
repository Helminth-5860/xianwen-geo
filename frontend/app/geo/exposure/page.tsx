"use client";

import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import { getReportHistory, type GeoReport } from "@/lib/geo-report-client";

const { Paragraph, Text, Title } = Typography;

type ExposureState = Readonly<{
  subjectId: string;
  reports: GeoReport[];
  selectedReportId: string;
  error: string;
}>;

function reportOptionLabel(report: GeoReport) {
  return `${new Date(report.generated_at).toLocaleString("zh-CN")} · 曝光 ${report.summary.exposure.exposure_index}`;
}

export default function GeoExposurePage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [exposureState, setExposureState] = useState<ExposureState>();
  const subjectId = subject?.id ?? "";

  useEffect(() => {
    if (subjectLoading || !subjectId) return;
    let current = true;

    void getReportHistory(subjectId)
      .then((result) => {
        if (!current) return;
        const reports = [...result.items].sort(
          (left, right) =>
            new Date(right.generated_at).getTime() - new Date(left.generated_at).getTime(),
        );
        setExposureState({
          subjectId,
          reports,
          selectedReportId: reports[0]?.id ?? "",
          error: "",
        });
      })
      .catch((reason) => {
        if (current) {
          setExposureState({
            subjectId,
            reports: [],
            selectedReportId: "",
            error: userMessage(reason),
          });
        }
      });

    return () => {
      current = false;
    };
  }, [subjectId, subjectLoading]);

  const state = exposureState?.subjectId === subjectId ? exposureState : undefined;
  const report = state?.reports.find((item) => item.id === state.selectedReportId);

  if (subjectLoading || (subject && !state)) {
    return <Spin fullscreen description="正在加载曝光指数" />;
  }

  return (
    <main className="geo-dashboard">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">曝光指数</Text>
          <Title level={2}>曝光指数</Title>
          <Paragraph type="secondary">
            独立查看单份检测报告的曝光潜力、提及、推荐、排名与模型覆盖表现。
          </Paragraph>
        </div>
        <Space wrap>
          <Button href="/geo/reports">查看检测报告</Button>
          <Button href="/geo/reports/history">历史报告对比</Button>
        </Space>
      </section>

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
            <Tag>可用报告 {state?.reports.length ?? 0}</Tag>
          </section>

          {state?.error && <Alert type="error" showIcon message={state.error} />}

          {!state?.error && !report ? (
            <Card>
              <Empty description="当前主体还没有可展示的曝光指数">
                <Button type="primary" href="/geo/detections">
                  开始首次检测
                </Button>
              </Empty>
            </Card>
          ) : report ? (
            <>
              <Card title="选择报告">
                <Select
                  aria-label="曝光指数报告"
                  value={report.id}
                  style={{ width: "100%" }}
                  options={state?.reports.map((item) => ({
                    label: reportOptionLabel(item),
                    value: item.id,
                  }))}
                  onChange={(selectedReportId) =>
                    setExposureState((current) =>
                      current && current.subjectId === subjectId
                        ? { ...current, selectedReportId }
                        : current,
                    )
                  }
                />
              </Card>

              <Card
                title="曝光潜力指数"
                extra={
                  <Space wrap>
                    <Tag color={report.summary.exposure.status === "formal" ? "blue" : "default"}>
                      {report.summary.exposure.status === "formal" ? "正式结果" : "参考结果"}
                    </Tag>
                    <Button size="small" href={`/geo/reports/${report.id}`}>
                      查看来源报告
                    </Button>
                  </Space>
                }
              >
                <Row gutter={[16, 16]}>
                  <Col xs={24} md={8}>
                    <Statistic
                      title="综合曝光指数"
                      value={report.summary.exposure.exposure_index}
                      suffix={report.summary.exposure.grade}
                    />
                  </Col>
                  <Col xs={12} md={4}>
                    <Statistic title="提及率" value={report.summary.exposure.mention_rate_score} />
                  </Col>
                  <Col xs={12} md={4}>
                    <Statistic
                      title="推荐率"
                      value={report.summary.exposure.recommendation_rate_score}
                    />
                  </Col>
                  <Col xs={12} md={4}>
                    <Statistic
                      title="排名表现"
                      value={report.summary.exposure.ranking_performance_score}
                    />
                  </Col>
                  <Col xs={12} md={4}>
                    <Statistic
                      title="模型覆盖率"
                      value={report.summary.exposure.model_coverage_score}
                    />
                  </Col>
                </Row>
              </Card>

              <Alert type="info" showIcon title={report.summary.exposure.disclaimer} />
            </>
          ) : null}
        </>
      )}
    </main>
  );
}
