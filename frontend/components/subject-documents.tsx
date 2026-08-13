"use client";

import { Alert, Button, Card, Input, List, Progress, Space, Typography, Upload } from "antd";
import type { UploadFile } from "antd";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  completeUploadIntent,
  confirmDocumentParse,
  createUploadIntent,
  getDocumentParseResult,
  getSubjectDocuments,
  getUploadIntent,
  newParseIdempotencyKey,
  newUploadIdempotencyKey,
  openDocumentDownload,
  requestDocumentParse,
  uploadDirect,
  type DocumentParseResult,
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
  const [activeDocumentId, setActiveDocumentId] = useState("");
  const [parseResult, setParseResult] = useState<DocumentParseResult>();
  const [confirmedText, setConfirmedText] = useState("");
  const [parsing, setParsing] = useState(false);

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

  const parse = async (document: SubjectDocument) => {
    setParsing(true);
    setError("");
    setMessage("");
    setActiveDocumentId(document.id);
    setParseResult(undefined);
    try {
      await requestDocumentParse(document, newParseIdempotencyKey());
      setMessage("\u6587\u4ef6\u89e3\u6790\u4efb\u52a1\u5df2\u53d7\u7406");
      let result = await getDocumentParseResult(document.id);
      for (
        let attempt = 0;
        attempt < 30 && ["queued", "running"].includes(result.status);
        attempt += 1
      ) {
        await new Promise((resolve) => window.setTimeout(resolve, 800));
        result = await getDocumentParseResult(document.id);
      }
      setParseResult(result);
      setConfirmedText(result.canonical_text);
      if (result.status === "retry_wait") {
        setMessage(
          "\u89e3\u6790\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u7cfb\u7edf\u4f1a\u5b89\u5168\u91cd\u8bd5",
        );
      } else if (result.status === "failed") {
        setError("\u6587\u4ef6\u5185\u5bb9\u65e0\u6cd5\u5b89\u5168\u89e3\u6790");
      } else if (result.status === "succeeded") {
        setMessage(
          "\u89e3\u6790\u5b8c\u6210\uff0c\u8bf7\u68c0\u67e5\u5e76\u786e\u8ba4\u6587\u672c",
        );
      }
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setParsing(false);
    }
  };

  const confirm = async () => {
    if (!parseResult || !activeDocumentId) return;
    setParsing(true);
    try {
      await confirmDocumentParse(activeDocumentId, parseResult, confirmedText);
      const refreshed = await getDocumentParseResult(activeDocumentId);
      setParseResult(refreshed);
      setConfirmedText(refreshed.canonical_text);
      setMessage("\u89e3\u6790\u6587\u672c\u5df2\u786e\u8ba4");
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setParsing(false);
    }
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
              <Button
                key="parse"
                type="link"
                disabled={disabled || parsing}
                onClick={() => void parse(document)}
              >
                {"\u89e3\u6790\u4e0e\u786e\u8ba4"}
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
      {parseResult && activeDocumentId && (
        <Card title={"\u89e3\u6790\u7ed3\u679c\u786e\u8ba4"} style={{ marginTop: 16 }}>
          <Alert
            type="warning"
            showIcon
            message={
              "\u672a\u786e\u8ba4\u7684\u89e3\u6790\u5185\u5bb9\u4e0d\u4f1a\u8fdb\u5165\u540e\u7eed AI\u3001\u6587\u7ae0\u6216\u5176\u4ed6\u4e1a\u52a1\u80fd\u529b"
            }
          />
          <Typography.Paragraph type="secondary">
            {
              "\u8868\u683c\u548c\u89e3\u6790\u8b66\u544a\u4e3a\u673a\u5668\u53ea\u8bfb\u4e8b\u5b9e\uff1b\u7528\u6237\u4ec5\u53ef\u4fee\u8ba2\u4e0b\u65b9\u89c4\u8303\u6587\u672c\u3002"
            }
          </Typography.Paragraph>
          <Input.TextArea
            aria-label={"\u786e\u8ba4\u89e3\u6790\u6587\u672c"}
            rows={10}
            value={confirmedText}
            disabled={disabled || parsing || parseResult.status !== "succeeded"}
            onChange={(event) => setConfirmedText(event.target.value)}
          />
          <Typography.Paragraph type="secondary">
            {`${parseResult.tables.length} \u4e2a\u8868\u683c\uff1b\u8b66\u544a\uff1a`}
            {parseResult.warning_codes.length > 0
              ? parseResult.warning_codes.join("\u3001")
              : "\u65e0"}
          </Typography.Paragraph>
          <Button
            type="primary"
            loading={parsing}
            disabled={disabled || parseResult.status !== "succeeded"}
            onClick={() => void confirm()}
          >
            {"\u786e\u8ba4\u89e3\u6790\u6587\u672c"}
          </Button>
        </Card>
      )}
    </Card>
  );
}
