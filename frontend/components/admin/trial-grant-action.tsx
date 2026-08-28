"use client";

import { Alert, Button, Input, Modal, Space } from "antd";
import { useState } from "react";

import { grantTrialSubscription } from "@/lib/plans-client";

import { useAdminCapabilities } from "./admin-capability";

export function TrialGrantAction({
  userId,
  expectedVersion,
  onCompleted,
  onError,
}: {
  userId: string;
  expectedVersion: number;
  onCompleted: () => void;
  onError: (message: string) => void;
}) {
  const capabilities = useAdminCapabilities();
  const [open, setOpen] = useState(false);
  const [planId, setPlanId] = useState("");
  const [note, setNote] = useState("");
  const allowed = capabilities?.permission_keys.includes("subscriptions.grant_trial") ?? false;
  if (!allowed) {
    return <Alert type="info" showIcon title="当前账号没有发放试用套餐权限" />;
  }
  const submit = async () => {
    if (!planId.trim()) {
      onError("请填写试用套餐 ID");
      return;
    }
    try {
      await grantTrialSubscription(userId, expectedVersion, planId.trim(), note);
      onCompleted();
      setOpen(false);
    } catch (error) {
      onError(error instanceof Error ? error.message : "发放试用套餐失败");
    }
  };
  return (
    <>
      <Button onClick={() => setOpen(true)}>发放试用套餐</Button>
      <Modal
        title="发放试用套餐"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => void submit()}
        okText="确认发放"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Input
            aria-label="试用套餐 ID"
            value={planId}
            onChange={(event) => setPlanId(event.target.value)}
          />
          <Input.TextArea
            aria-label="试用发放备注"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={500}
          />
          <Alert
            type="info"
            showIcon
            title="套餐版本和试用标志由服务端校验并选择，客户端不能覆盖"
          />
        </Space>
      </Modal>
    </>
  );
}
