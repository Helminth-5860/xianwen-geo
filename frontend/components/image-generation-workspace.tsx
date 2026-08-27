"use client";

import { Alert, Space, Typography } from "antd";
import { useEffect, useState } from "react";

import { ArticleImagesWorkspace } from "@/components/article-images-workspace";
import { userMessage } from "@/lib/auth-client";
import { getSubjectDocuments } from "@/lib/documents-client";

type Props = Readonly<{ subjectId: string }>;

export function ImageGenerationWorkspace({ subjectId }: Props) {
  const [referenceDocuments, setReferenceDocuments] = useState<
    Array<{ id: string; label: string }>
  >([]);
  const [documentError, setDocumentError] = useState("");

  useEffect(() => {
    let active = true;
    void getSubjectDocuments(subjectId)
      .then(({ documents }) => {
        if (!active) return;
        setReferenceDocuments(
          documents
            .filter((document) =>
              ["jpeg", "jpg", "png", "webp"].includes(document.detected_file_kind),
            )
            .map((document) => ({
              id: document.document_version_id,
              label: `${document.display_name} · ${document.detected_file_kind.toUpperCase()}`,
            })),
        );
        setDocumentError("");
      })
      .catch((reason: unknown) => {
        if (active) setDocumentError(userMessage(reason));
      });
    return () => {
      active = false;
    };
  }, [subjectId]);

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Typography.Title level={2}>图片生成</Typography.Title>
        {documentError && (
          <Alert type="warning" showIcon title={`参考图片资料加载失败：${documentError}`} />
        )}
        <ArticleImagesWorkspace subjectId={subjectId} referenceDocuments={referenceDocuments} />
      </Space>
    </main>
  );
}
