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

const UNASSIGNED = "__unassigned__";

export function CustomerAssignmentActions({
  assignment,
  admins,
  mode,
  onChanged,
  onApproval,
}: Props) {
  const [ownerId, setOwnerId] = useState(assignment.owner_admin_id ?? UNASSIGNED);
  const options = useMemo(
    () => [
      { value: UNASSIGNED, label: "解除负责人" },
      ...admins
        .filter((admin) => admin.admin_status === "active" && !admin.is_superuser)
        .map((admin) => ({
          value: admin.id,
          label: `${admin.nickname}（${admin.phone_masked}）`,
        })),
    ],
    [admins],
  );
  const selectedOwnerId = ownerId === UNASSIGNED ? null : ownerId;
  const actionName = assignment.owner_admin_id
    ? selectedOwnerId
      ? "转交客户负责人"
      : "解除客户负责人"
    : "分配客户负责人";

  return (
    <Card size="small" title="客户负责人">
      <Space direction="vertical" style={{ width: "100%" }}>
        <Typography.Text>
          当前负责人：
          {assignment.owner_admin_id
            ? `${assignment.owner_nickname ?? "管理员"}（${assignment.owner_phone_masked}）`
            : "未分配"}
        </Typography.Text>
        <Select
          aria-label="选择客户负责人"
          value={ownerId}
          options={options}
          style={{ width: "100%" }}
          onChange={setOwnerId}
        />
        {admins.length === 0 && assignment.owner_admin_id === null && (
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
          disabled={selectedOwnerId === assignment.owner_admin_id}
          execute={(credentials) =>
            changeCustomerAssignment(
              assignment.customer_id,
              selectedOwnerId,
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
