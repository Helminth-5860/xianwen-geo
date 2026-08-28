"use client";

import { Alert, Button, Card, Descriptions, Input, Modal, Spin, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  cancelSubscriptionChange,
  getAdminSubscriptionChange,
  type SubscriptionChange,
} from "@/lib/plans-client";

export default function AdminSubscriptionChangeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const capabilities = useAdminCapabilities();
  const [item, setItem] = useState<SubscriptionChange | null>(null);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    void getAdminSubscriptionChange(id)
      .then(setItem)
      .catch((value) => setError(userMessage(value)));
  }, [id]);
  if (!item) return error ? <Alert type="error" showIcon message={error} /> : <Spin />;
  const canChange = capabilities?.permission_keys.includes("subscriptions.change") ?? false;
  const submit = async () => {
    try {
      await cancelSubscriptionChange(item.id, item.version, reason, crypto.randomUUID());
      setItem(await getAdminSubscriptionChange(id));
      setOpen(false);
    } catch (value) {
      setError(userMessage(value));
    }
  };
  return (
    <main className="admin-page">
      <Typography.Title>套餐变更详情</Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Descriptions column={1}>
          <Descriptions.Item label="变更编号">{item.id}</Descriptions.Item>
          <Descriptions.Item label="目标套餐">{item.target_plan_name}</Descriptions.Item>
          <Descriptions.Item label="变更类型">{item.change_type}</Descriptions.Item>
          <Descriptions.Item label="额度策略">{item.quota_policy}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag>{item.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="生效时间">{item.effective_at}</Descriptions.Item>
          {item.stable_error_code && (
            <Descriptions.Item label="????????">{item.stable_error_code}</Descriptions.Item>
          )}
          {item.next_attempt_at && (
            <Descriptions.Item label="??????">{item.next_attempt_at}</Descriptions.Item>
          )}
        </Descriptions>
        {item.status === "scheduled" &&
          (canChange ? (
            <Button danger onClick={() => setOpen(true)}>
              取消排期
            </Button>
          ) : (
            <Alert type="info" showIcon message="当前账号没有取消套餐变更权限" />
          ))}
      </Card>
      <Modal
        title="确认取消续费排期"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => void submit()}
        okText="确认取消"
      >
        <Alert type="warning" showIcon message="确认后将立即取消，并写入操作记录。" />
        <Input.TextArea
          aria-label="取消排期原因"
          value={reason}
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
        />
      </Modal>
    </main>
  );
}
