"use client";

import { Alert, Space, Typography } from "antd";

import { SubjectDocuments } from "@/components/subject-documents";

type Props = Readonly<{ subjectId: string }>;

export function CustomLibraryWorkspace({ subjectId }: Props) {
  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={2}>自定义库</Typography.Title>
          <Typography.Text type="secondary">
            上传和管理当前主体自己的 PDF、文档、表格、文本和图片资料
          </Typography.Text>
        </div>
        <Alert
          type="info"
          showIcon
          title="资料仅用于当前主体"
          description="上传并确认的资料可用于补充主体信息和后续内容创作，其他主体不会看到这些资料。"
        />
        <SubjectDocuments subjectId={subjectId} />
      </Space>
    </main>
  );
}
