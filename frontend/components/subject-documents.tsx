"use client";

import { Alert, Button, Card, List, Progress, Space, Typography, Upload } from "antd";
import type { UploadFile } from "antd";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  completeUploadIntent,
  createUploadIntent,
  getSubjectDocuments,
  getUploadIntent,
  newUploadIdempotencyKey,
  openDocumentDownload,
  uploadDirect,
  type SubjectDocument,
} from "@/lib/documents-client";

export function SubjectDocuments({
  subjectId,
  disabled = false,
  onDocumentsChange,
}: {
  subjectId: string;
  disabled?: boolean;
  onDocumentsChange?: (documents: SubjectDocument[]) => void;
}) {
  const [documents, setDocuments] = useState<SubjectDocument[]>([]);
  const [progress, setProgress] = useState<number>();
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = async () => {
    const result = await getSubjectDocuments(subjectId);
    setDocuments(result.documents);
    onDocumentsChange?.(result.documents);
  };

  useEffect(() => {
    let active = true;
    void getSubjectDocuments(subjectId)
      .then((result) => {
        if (!active) return;
        setDocuments(result.documents);
        onDocumentsChange?.(result.documents);
      })
      .catch((reason) => {
        if (active) setError(userMessage(reason));
      });
    return () => {
      active = false;
    };
  }, [subjectId, onDocumentsChange]);

  const upload = async (file: File) => {
    setError("");
    setMessage("");
    setProgress(0);
    try {
      const created = await createUploadIntent(subjectId, file, newUploadIdempotencyKey());
      if (!created.upload) throw new Error("上传凭证不可用，请稍后重试");
      await uploadDirect(created.upload, file, setProgress);
      let intent = await completeUploadIntent(created.intent);
      setMessage("文件正在进行安全验证");
      while (intent.status === "verifying") {
        await new Promise((resolve) => window.setTimeout(resolve, 800));
        intent = await getUploadIntent(intent.id);
      }
      if (intent.status !== "completed") throw new Error("文件未通过安全验证");
      setMessage("文件已安全保存");
      await refresh();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setProgress(undefined);
    }
    return false;
  };

  return (
    <Card title="主体资料库" style={{ marginBottom: 20 }}>
      <Typography.Paragraph type="secondary">
        文件保持私有；上传完成后还需通过结构和安全扫描，才可用于主体字段。
      </Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} />}
      {message && <Alert type="info" showIcon message={message} />}
      {progress !== undefined && <Progress percent={progress} />}
      <Upload
        accept=".pdf,.docx,.xlsx,.txt,.md,.jpg,.jpeg,.png,.webp"
        showUploadList={false}
        beforeUpload={(file: UploadFile) => upload(file as unknown as File)}
        disabled={disabled || progress !== undefined}
      >
        <Button disabled={disabled || progress !== undefined}>上传资料</Button>
      </Upload>
      <List
        dataSource={documents}
        locale={{ emptyText: "暂无已验证文件" }}
        renderItem={(document) => (
          <List.Item
            actions={[
              <Button
                key="download"
                type="link"
                disabled={!document.download_available}
                onClick={() =>
                  void openDocumentDownload(document.id).catch((reason) =>
                    setError(userMessage(reason)),
                  )
                }
              >
                私密下载
              </Button>,
            ]}
          >
            <Space direction="vertical" size={0}>
              <Typography.Text>{document.display_name}</Typography.Text>
              <Typography.Text type="secondary">
                {document.detected_file_kind.toUpperCase()} · {document.size_bytes} bytes
              </Typography.Text>
            </Space>
          </List.Item>
        )}
      />
    </Card>
  );
}
