import { Space, Typography } from "antd";

import { ImageGenerationWorkspace } from "@/components/image-generation-workspace";

type SubjectImagesPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function SubjectImagesPage({ params }: SubjectImagesPageProps) {
  const { id } = await params;

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Typography.Title level={2}>图片生成</Typography.Title>
        <ImageGenerationWorkspace subjectId={id} />
      </Space>
    </main>
  );
}
