"use client";

import { Alert, Button, Card, Descriptions, Input, Modal, Spin, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { SubscriptionChangeAction } from "@/components/admin/subscription-change-action";
import { userMessage } from "@/lib/auth-client";
import { getAdminSubscription, terminateSubscription, type Subscription } from "@/lib/plans-client";
import type { ApprovalCreated } from "@/lib/risk-client";

export default function AdminSubscriptionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const capabilities = useAdminCapabilities();
  const [item, setItem] = useState<Subscription | null>(null);
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const [approval, setApproval] = useState<ApprovalCreated | null>(null);
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
      const result = await terminateSubscription(item.id, item.version, reason);
      if ("approval_required" in result) setApproval(result as ApprovalCreated);
      setOpen(false);
    } catch (value) {
      setError(userMessage(value));
    }
  };
  return (
    <main className="admin-page">
      <Typography.Title>订阅详情</Typography.Title>
      {approval && (
        <Alert
          type="warning"
          showIcon
          message="已发起双人审批"
          description={"审批编号：" + approval.approval_id}
        />
      )}
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
        <SubscriptionChangeAction subscription={item} onApproval={setApproval} onError={setError} />
      </Card>
      <Modal
        title="终止订阅（需要双人审批）"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => void submit()}
        okText="发起审批"
      >
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
