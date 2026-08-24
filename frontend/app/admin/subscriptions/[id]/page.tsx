"use client";

import { Alert, Button, Card, Descriptions, Input, Modal, Spin, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { SubscriptionChangeAction } from "@/components/admin/subscription-change-action";
import { userMessage } from "@/lib/auth-client";
import { getAdminSubscription, terminateSubscription, type Subscription } from "@/lib/plans-client";

export default function AdminSubscriptionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const capabilities = useAdminCapabilities();
  const [item, setItem] = useState<Subscription | null>(null);
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    void getAdminSubscription(id)
      .then(setItem)
      .catch((value) => setError(userMessage(value)));
  }, [id]);
  if (error) return <Alert type="error" showIcon message={error} />;
  if (!item) return <Spin description="正在加载订阅" />;
  const canTerminate = capabilities?.permission_keys.includes("subscriptions.terminate") ?? false;
  const submit = async () => {
    try {
      await terminateSubscription(item.id, item.version, reason);
      setItem(await getAdminSubscription(id));
      setOpen(false);
    } catch (value) {
      setError(userMessage(value));
    }
  };
  return (
    <main className="admin-page">
      <Typography.Title>订阅详情</Typography.Title>
      <Card>
        <Descriptions column={1}>
          <Descriptions.Item label="订阅编号">{item.id}</Descriptions.Item>
          <Descriptions.Item label="套餐">{item.plan_name}</Descriptions.Item>
          <Descriptions.Item label="版本">第 {item.plan_version_no} 版</Descriptions.Item>
          <Descriptions.Item label="类型">{item.is_trial ? "试用" : "正式"}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag>{item.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="开始时间">{item.starts_at}</Descriptions.Item>
          <Descriptions.Item label="结束时间">{item.ends_at}</Descriptions.Item>
        </Descriptions>
        {item.status === "active" &&
          (canTerminate ? (
            <Button danger onClick={() => setOpen(true)}>
              终止订阅
            </Button>
          ) : (
            <Alert type="info" showIcon message="当前账号没有终止订阅权限" />
          ))}
        <SubscriptionChangeAction
          subscription={item}
          onCompleted={() => void getAdminSubscription(id).then(setItem)}
          onError={setError}
        />
      </Card>
      <Modal
        title="确认终止订阅"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => void submit()}
        okText="确认终止"
      >
        <Alert type="warning" showIcon message="确认后将立即终止，并写入操作记录。" />
        <Input.TextArea
          aria-label="终止原因"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={500}
        />
      </Modal>
    </main>
  );
}
