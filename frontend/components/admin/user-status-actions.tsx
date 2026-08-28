"use client";

import { Alert, Button, Space } from "antd";
import { LockOutlined, UnlockOutlined } from "@ant-design/icons";

import { RiskActionButton, type RiskCredentials } from "./risk-action-button";
import { useAdminCapabilities } from "./admin-capability";
import type { RiskMode } from "@/lib/risk-client";

export type UserStatusActionTarget = Readonly<{
  account_status: "active" | "frozen" | "cancel_pending" | "cancelled";
}>;

type Props<T extends UserStatusActionTarget> = Readonly<{
  user: T;
  submitting: boolean;
  freezeMode: RiskMode;
  executeFreeze: (credentials: RiskCredentials) => Promise<T>;
  onRiskExecuted: (result: T) => void;
  onUnfreeze: () => void;
}>;

export function UserStatusActions<T extends UserStatusActionTarget>({
  user,
  submitting,
  freezeMode,
  executeFreeze,
  onRiskExecuted,
  onUnfreeze,
}: Props<T>) {
  const capabilities = useAdminCapabilities();
  const canFreeze = Boolean(capabilities?.permission_keys.includes("users.freeze"));

  return (
    <Space orientation="vertical" className="admin-actions">
      {!canFreeze && ["active", "frozen"].includes(user.account_status) && (
        <Alert type="info" showIcon title="没有账号状态管理权限，禁用和恢复操作不可用" />
      )}
      <Space wrap>
        {canFreeze && user.account_status === "active" && (
          <RiskActionButton
            actionName="禁用用户"
            mode={freezeMode}
            danger
            disabled={submitting}
            execute={executeFreeze}
            onExecuted={onRiskExecuted}
          >
            <LockOutlined /> 禁用账号
          </RiskActionButton>
        )}
        {canFreeze && user.account_status === "frozen" && (
          <Button icon={<UnlockOutlined />} disabled={submitting} onClick={onUnfreeze}>
            恢复账号
          </Button>
        )}
      </Space>
    </Space>
  );
}
