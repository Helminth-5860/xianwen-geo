"use client";

import { Alert, Button, Space } from "antd";
import { CheckOutlined, LockOutlined, StopOutlined, UnlockOutlined } from "@ant-design/icons";

import { RiskActionButton, type RiskCredentials } from "./risk-action-button";
import { useAdminCapabilities } from "./admin-capability";
import type { ApprovalCreated, RiskExecution, RiskMode } from "@/lib/risk-client";

export type UserStatusActionTarget = Readonly<{
  approval_status: "pending" | "approved" | "rejected";
  account_status: "active" | "frozen" | "cancel_pending" | "cancelled";
}>;

type Props<T extends UserStatusActionTarget> = Readonly<{
  user: T;
  submitting: boolean;
  rejectMode: RiskMode;
  freezeMode: RiskMode;
  onApprove: () => void;
  executeReject: (credentials: RiskCredentials) => Promise<RiskExecution<T>>;
  executeFreeze: (credentials: RiskCredentials) => Promise<RiskExecution<T>>;
  onRiskExecuted: (result: T) => void;
  onApproval: (approval: ApprovalCreated) => void;
  onUnfreeze: () => void;
}>;

export function UserStatusActions<T extends UserStatusActionTarget>({
  user,
  submitting,
  rejectMode,
  freezeMode,
  onApprove,
  executeReject,
  executeFreeze,
  onRiskExecuted,
  onApproval,
  onUnfreeze,
}: Props<T>) {
  const capabilities = useAdminCapabilities();
  const canReview = Boolean(capabilities?.permission_keys.includes("users.review"));
  const canFreeze = Boolean(capabilities?.permission_keys.includes("users.freeze"));

  return (
    <Space direction="vertical" className="admin-actions">
      {!canReview && user.approval_status === "pending" && (
        <Alert type="info" showIcon message="没有用户审核权限，审核操作不可用" />
      )}
      {!canFreeze && ["active", "frozen"].includes(user.account_status) && (
        <Alert type="info" showIcon message="没有账号冻结权限，冻结和解冻操作不可用" />
      )}
      <Space wrap>
        {canReview && user.approval_status === "pending" && (
          <>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              loading={submitting}
              onClick={onApprove}
            >
              通过审核
            </Button>
            <RiskActionButton
              actionName="拒绝用户审核"
              mode={rejectMode}
              danger
              disabled={submitting}
              reasonRequired
              execute={executeReject}
              onExecuted={onRiskExecuted}
              onApproval={onApproval}
            >
              <StopOutlined /> 拒绝审核
            </RiskActionButton>
          </>
        )}
        {canFreeze && user.account_status === "active" && (
          <RiskActionButton
            actionName="冻结用户"
            mode={freezeMode}
            danger
            disabled={submitting}
            execute={executeFreeze}
            onExecuted={onRiskExecuted}
            onApproval={onApproval}
          >
            <LockOutlined /> 冻结账号
          </RiskActionButton>
        )}
        {canFreeze && user.account_status === "frozen" && (
          <Button icon={<UnlockOutlined />} disabled={submitting} onClick={onUnfreeze}>
            解冻账号
          </Button>
        )}
      </Space>
    </Space>
  );
}
