"use client";

import { Alert, Button, Card, Empty, Space, Typography } from "antd";

type Props = Readonly<{ subjectId: string }>;

export function VideoLibraryWorkspace({ subjectId }: Props) {
  return (
    <main className="page-shell" data-subject-id={subjectId}>
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={2}>视频库</Typography.Title>
          <Typography.Text type="secondary">查看当前主体的视频内容和脚本</Typography.Text>
        </div>
        <Alert
          type="info"
          showIcon
          title="如何开始"
          description="前往视频脚本生成页创建内容，完成后可复制或保存使用。"
        />
        <Card>
          <Empty description="当前主体还没有视频内容，可先生成视频脚本开始创作。">
            <Button type="primary" href={`/subjects/${subjectId}/video-scripts/new`}>
              生成视频脚本
            </Button>
          </Empty>
        </Card>
      </Space>
    </main>
  );
}
