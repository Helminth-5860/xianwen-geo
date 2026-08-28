"use client";

import { CheckOutlined, EyeOutlined } from "@ant-design/icons";
import { Button, Card, Modal, Space, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  approvePublication,
  getPublishingState,
  type Publication,
  type PublishingState,
} from "@/lib/publishing-client";

function waitingForReview(publication: Publication) {
  return (
    publication.status === "queued" &&
    publication.targets.some((target) => target.status === "paused")
  );
}

export function PublicationReviewPanel() {
  const { currentSubject } = useSubjectWorkspace();
  const [state, setState] = useState<PublishingState | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [messageApi, holder] = message.useMessage();

  const load = useCallback(async () => {
    if (!currentSubject?.id) return;
    try {
      setState(await getPublishingState(currentSubject.id));
    } catch {
      // 主工作区会展示读取错误；这里保持安静，避免重复报错。
    }
  }, [currentSubject?.id]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 6000);
    return () => window.clearInterval(timer);
  }, [load]);

  const pending = useMemo(() => {
    if (state?.preference.mode !== "review") return [];
    return state.recent_publications.filter(waitingForReview);
  }, [state]);

  if (!pending.length) return <>{holder}</>;

  const approve = async (publication: Publication) => {
    setApprovingId(publication.id);
    try {
      await approvePublication(publication.id);
      messageApi.success("已确认，显问将按计划错峰发布");
      await load();
      window.setTimeout(() => window.location.reload(), 500);
    } catch (reason: unknown) {
      messageApi.warning(userMessage(reason));
    } finally {
      setApprovingId(null);
    }
  };

  return (
    <>
      {holder}
      <div
        style={{
          position: "fixed",
          right: 24,
          bottom: 24,
          zIndex: 1000,
          width: 320,
          maxWidth: "calc(100vw - 48px)",
        }}
      >
        <Card size="small" title="待确认发布" extra={<Tag color="warning">{pending.length} 篇</Tag>}>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            内容、配图和平台版本已经准备完成。确认后才会真正提交到外部平台。
          </Typography.Paragraph>
          <Button type="primary" block icon={<EyeOutlined />} onClick={() => setOpen(true)}>
            查看并确认
          </Button>
        </Card>
      </div>

      <Modal
        open={open}
        title="确认待发布内容"
        footer={<Button onClick={() => setOpen(false)}>关闭</Button>}
        onCancel={() => setOpen(false)}
        width={760}
      >
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          {pending.map((publication) => (
            <Card key={publication.id} size="small">
              <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                <Typography.Text strong>{publication.title}</Typography.Text>
                <Space wrap>
                  {publication.targets.map((target) => (
                    <Tag key={target.id}>{target.platform_name}</Tag>
                  ))}
                </Space>
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  loading={approvingId === publication.id}
                  onClick={() => void approve(publication)}
                >
                  确认发布
                </Button>
              </Space>
            </Card>
          ))}
        </Space>
      </Modal>
    </>
  );
}
