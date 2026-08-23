"use client";

import { Alert, Card, Select, Space, Typography } from "antd";
import { useMemo, useState } from "react";

import {
  changeCustomerAssignment,
  type AdminProfile,
  type CustomerAssignment,
} from "@/lib/admin-rbac-client";
import type { ApprovalCreated, RiskMode } from "@/lib/risk-client";

import { RiskActionButton } from "./risk-action-button";

type Props = Readonly<{
  assignment: CustomerAssignment;
  admins: AdminProfile[];
  mode: RiskMode;
  onChanged: (assignment: CustomerAssignment) => void;
  onApproval: (approval: ApprovalCreated) => void;
}>;

export function CustomerAssignmentActions({
  assignment,
  admins,
  mode,
  onChanged,
  onApproval,
}: Props) {
  const [ownerId, setOwnerId] = useState(assignment.owner_admin_id);
  const options = useMemo(
    () =>
      admins
        .filter((admin) => admin.admin_status === "active" && !admin.is_superuser)
        .map((admin) => ({
          value: admin.id,
          label: `${admin.nickname}（${admin.phone_masked}）`,
        })),
    [admins],
  );
  const actionName = "转交客户负责人";

  return (
    <Card size="small" title="客户负责人">
      <Space direction="vertical" style={{ width: "100%" }}>
        <Typography.Text>
          当前负责人：
          {`${assignment.owner_nickname}（${assignment.owner_phone_masked}）`}
        </Typography.Text>
        <Select
          aria-label="选择客户负责人"
          value={ownerId}
          options={options}
          style={{ width: "100%" }}
          onChange={setOwnerId}
        />
        {options.length === 0 && (
          <Alert
            type="info"
            showIcon
            message="当前权限无法读取管理员候选列表，请联系具备管理员列表权限的超级管理员。"
          />
        )}
        <RiskActionButton
          actionName={actionName}
          mode={mode}
          reasonRequired
          disabled={ownerId === assignment.owner_admin_id}
          execute={(credentials) =>
            changeCustomerAssignment(
              assignment.customer_id,
              ownerId,
              assignment.version,
              credentials.reason,
              credentials,
            )
          }
          onExecuted={onChanged}
          onApproval={onApproval}
        >
          {actionName}
        </RiskActionButton>
      </Space>
    </Card>
  );
}
