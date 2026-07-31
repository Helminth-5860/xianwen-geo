"use client";

import { CheckOutlined, LockOutlined, StopOutlined, UnlockOutlined } from "@ant-design/icons";
import { Alert, Button, Space } from "antd";

import { useAdminCapabilities } from "./admin-capability";

export type UserStatusActionTarget = Readonly<{
  approval_status: "pending" | "approved" | "rejected";
  account_status: "active" | "frozen" | "cancel_pending" | "cancelled";
}>;

type Props = Readonly<{
  user: UserStatusActionTarget;
  submitting: boolean;
  onApprove: () => void;
  onReject: () => void;
  onFreeze: () => void;
  onUnfreeze: () => void;
}>;

export function UserStatusActions({
  user,
  submitting,
  onApprove,
  onReject,
  onFreeze,
  onUnfreeze,
}: Props) {
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
            <Button danger icon={<StopOutlined />} disabled={submitting} onClick={onReject}>
              拒绝审核
            </Button>
          </>
        )}
        {canFreeze && user.account_status === "active" && (
          <Button danger icon={<LockOutlined />} disabled={submitting} onClick={onFreeze}>
            冻结账号
          </Button>
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
