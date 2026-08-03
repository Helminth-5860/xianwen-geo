"use client";

import { Alert, Button, Checkbox, Input, Modal, Select, Space, Typography } from "antd";
import { useState } from "react";

import { useAdminCapabilities } from "./admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  previewSubscriptionChange,
  requestSubscriptionChange,
  type Subscription,
  type SubscriptionChangePreview,
  type SubscriptionChangeType,
  type SubscriptionQuotaPolicy,
} from "@/lib/plans-client";
import type { ApprovalCreated } from "@/lib/risk-client";

type Props = Readonly<{
  subscription: Subscription;
  onApproval: (approval: ApprovalCreated) => void;
  onError: (message: string) => void;
}>;

export function SubscriptionChangeAction({ subscription, onApproval, onError }: Props) {
  const capabilities = useAdminCapabilities();
  const [open, setOpen] = useState(false);
  const [targetVersionId, setTargetVersionId] = useState("");
  const [changeType, setChangeType] = useState<SubscriptionChangeType>("replacement");
  const [quotaPolicy, setQuotaPolicy] = useState<SubscriptionQuotaPolicy>("overwrite");
  const [reason, setReason] = useState("");
  const [confirmUnavailable, setConfirmUnavailable] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState("");
  const [preview, setPreview] = useState<SubscriptionChangePreview | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const allowed = capabilities?.permission_keys.includes("subscriptions.change") ?? false;

  if (!allowed) {
    return <Alert type="info" showIcon message="当前账号没有变更套餐权限" />;
  }
  if (subscription.status !== "active") return null;

  const loadPreview = async () => {
    setSubmitting(true);
    try {
      const result = await previewSubscriptionChange(subscription.id, {
        expectedVersion: subscription.version,
        targetPlanVersionId: targetVersionId,
        changeType,
        quotaPolicy,
      });
      setPreview(result);
    } catch (value) {
      onError(userMessage(value));
    } finally {
      setSubmitting(false);
    }
  };

  const submit = async () => {
    if (!preview) {
      onError("请先预览套餐变更结果");
      return;
    }
    if (!reason.trim()) {
      onError("请填写套餐变更原因");
      return;
    }
    if (
      preview.unavailable_confirmation_required &&
      (!confirmUnavailable || !unavailableReason.trim())
    ) {
      onError("下架套餐或退役版本需要确认并填写原因");
      return;
    }
    setSubmitting(true);
    try {
      const result = await requestSubscriptionChange(
        subscription.id,
        {
          expectedVersion: subscription.version,
          targetPlanVersionId: targetVersionId,
          changeType,
          quotaPolicy,
          confirmUnavailable,
          unavailableReason,
          reason: reason.trim(),
        },
        crypto.randomUUID(),
      );
      if ("approval_required" in result) onApproval(result as ApprovalCreated);
      setOpen(false);
    } catch (value) {
      onError(userMessage(value));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Button onClick={() => setOpen(true)}>变更套餐</Button>
      <Modal
        title="变更套餐（固定双人审批）"
        open={open}
        onCancel={() => !submitting && setOpen(false)}
        onOk={() => void submit()}
        okText="发起审批"
        confirmLoading={submitting}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            message="提交后由另一名有效超级管理员审批，当前不会直接执行"
          />
          <Input
            aria-label="目标套餐版本 ID"
            value={targetVersionId}
            onChange={(event) => {
              setTargetVersionId(event.target.value);
              setPreview(null);
            }}
          />
          <Select
            aria-label="套餐变更类型"
            value={changeType}
            onChange={(value) => {
              setChangeType(value);
              setPreview(null);
            }}
            options={[
              { value: "renewal", label: "续费" },
              { value: "upgrade", label: "升级" },
              { value: "downgrade", label: "降级" },
              { value: "replacement", label: "替换" },
              { value: "trial_conversion", label: "试用转正式" },
            ]}
          />
          <Select
            aria-label="额度迁移策略"
            value={quotaPolicy}
            onChange={(value) => {
              setQuotaPolicy(value);
              setPreview(null);
            }}
            options={[
              { value: "overwrite", label: "覆盖并清零旧余额" },
              { value: "accumulate", label: "累加至新基础额度" },
              { value: "retain", label: "保留为独立到期批次" },
            ]}
          />
          <Button
            onClick={() => void loadPreview()}
            disabled={!targetVersionId}
            loading={submitting}
          >
            预览变更
          </Button>
          {preview && (
            <Alert
              type="info"
              showIcon
              message={`服务端分类：${preview.change_type}`}
              description={`生效时间：${preview.effective_at}；额度策略：${preview.quota_policy}`}
            />
          )}
          <Input.TextArea
            aria-label="套餐变更原因"
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
          {preview?.unavailable_confirmation_required && (
            <>
              <Checkbox
                checked={confirmUnavailable}
                onChange={(event) => setConfirmUnavailable(event.target.checked)}
              >
                确认使用下架套餐或退役版本
              </Checkbox>
              <label>
                <Typography.Text>额外确认原因</Typography.Text>
                <Input.TextArea
                  aria-label="不可用版本确认原因"
                  value={unavailableReason}
                  maxLength={500}
                  onChange={(event) => setUnavailableReason(event.target.value)}
                />
              </label>
            </>
          )}
        </Space>
      </Modal>
    </>
  );
}
