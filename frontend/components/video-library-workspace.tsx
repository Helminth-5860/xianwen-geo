"use client";

import { Alert, Card, Empty, Space, Typography } from "antd";

type Props = Readonly<{ subjectId: string }>;

export function VideoLibraryWorkspace({ subjectId }: Props) {
  return (
    <main className="page-shell" data-subject-id={subjectId}>
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={2}>视频库</Typography.Title>
          <Typography.Text type="secondary">查看当前主体的视频和视频脚本资产</Typography.Text>
        </div>
        <Alert
          type="info"
          showIcon
          title="视频资产能力尚未接入"
          description="当前系统没有可复用的视频或视频脚本数据接口。页面不会展示示例数据；后端能力接入后，资产将在这里按当前主体隔离展示。"
        />
        <Card>
          <Empty description="当前主体暂无视频或视频脚本资产" />
        </Card>
      </Space>
    </main>
  );
}
