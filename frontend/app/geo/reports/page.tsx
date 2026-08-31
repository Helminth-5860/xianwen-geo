"use client";

import { RadarChartOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Space, Spin, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import { getReportHistory } from "@/lib/geo-report-client";

const { Paragraph, Text, Title } = Typography;

type Resolution = Readonly<{
  subjectId: string;
  status: "empty" | "error";
  error: string;
}>;

export default function GeoReportsIndexPage() {
  const { replace } = useRouter();
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [resolution, setResolution] = useState<Resolution>();
  const subjectId = subject?.id ?? "";

  useEffect(() => {
    if (subjectLoading || !subjectId) return;
    let current = true;

    void getReportHistory(subjectId)
      .then((result) => {
        if (!current) return;
        const latest = [...result.items].sort(
          (left, right) =>
            new Date(right.generated_at).getTime() - new Date(left.generated_at).getTime(),
        )[0];
        if (latest) {
          replace(`/geo/reports/${latest.id}`);
          return;
        }
        setResolution({ subjectId, status: "empty", error: "" });
      })
      .catch((reason) => {
        if (current) {
          setResolution({ subjectId, status: "error", error: userMessage(reason) });
        }
      });

    return () => {
      current = false;
    };
  }, [replace, subjectId, subjectLoading]);

  if (subjectLoading || (subjectId && resolution?.subjectId !== subjectId)) {
    return <Spin fullscreen description="正在打开最新检测报告" />;
  }

  return (
    <main className="geo-dashboard">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">GEO 报告</Text>
          <Title level={2}>GEO 检测报告</Title>
          <Paragraph type="secondary">
            检测报告按单次检测独立展示，不混入历史对比或曝光洞察。
          </Paragraph>
        </div>
        <Space wrap>
          <Button href="/workspace">返回 GEO 总览</Button>
          <Button type="primary" href="/geo/detections" icon={<RadarChartOutlined />}>
            新建检测
          </Button>
        </Space>
      </section>

      {resolution?.status === "error" && <Alert type="error" showIcon message={resolution.error} />}

      {!subject ? (
        <Card>
          <Empty description="请先绑定主体">
            <Button type="primary" href="/subjects">
              进入主体档案
            </Button>
          </Empty>
        </Card>
      ) : resolution?.status === "empty" ? (
        <Card>
          <Empty description="当前主体还没有 GEO 检测报告">
            <Button type="primary" href="/geo/detections" icon={<RadarChartOutlined />}>
              开始首次检测
            </Button>
          </Empty>
        </Card>
      ) : null}
    </main>
  );
}
