"use client";

import { Alert, Card, Select, Space, Typography } from "antd";
import { useMemo, useState } from "react";

import {
  changeCustomerAssignment,
  type AdminProfile,
  type CustomerAssignment,
} from "@/lib/admin-rbac-client";
import type { RiskMode } from "@/lib/risk-client";

import { RiskActionButton } from "./risk-action-button";

type Props = Readonly<{
  assignment: CustomerAssignment;
  admins: AdminProfile[];
  mode: RiskMode;
  onChanged: (assignment: CustomerAssignment) => void;
}>;

const INDEPENDENT_USER = "__independent_user__";

export function CustomerAssignmentActions({ assignment, admins, mode, onChanged }: Props) {
  const currentSelection = assignment.owner_admin_id ?? INDEPENDENT_USER;
  const [ownerId, setOwnerId] = useState(currentSelection);
  const options = useMemo(
    () => [
      { value: INDEPENDENT_USER, label: "独立用户（不关联管理员）" },
      ...admins
        .filter((admin) => admin.admin_status === "active" && !admin.is_superuser)
        .map((admin) => ({
          value: admin.id,
          label: `${admin.nickname}（${admin.phone_masked}）`,
        })),
    ],
    [admins],
  );
  const actionName =
    ownerId === INDEPENDENT_USER
      ? "解除管理员关联"
      : assignment.owner_admin_id
        ? "更换所属管理员"
        : "分配管理员";

  return (
    <Card size="small" title="所属管理员">
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Typography.Text>
          当前管理员：
          {assignment.owner_admin_id
            ? `${assignment.owner_nickname}（${assignment.owner_phone_masked}）`
            : "无（独立用户）"}
        </Typography.Text>
        <Select
          aria-label="选择所属管理员"
          value={ownerId}
          options={options}
          style={{ width: "100%" }}
          onChange={setOwnerId}
        />
        {options.length === 1 && (
          <Alert
            type="info"
            showIcon
            title="当前权限无法读取管理员候选列表，请联系具备管理员列表权限的超级管理员。"
          />
        )}
        <RiskActionButton
          actionName={actionName}
          mode={mode}
          reasonRequired
          disabled={ownerId === currentSelection}
          execute={(credentials) =>
            changeCustomerAssignment(
              assignment.customer_id,
              ownerId === INDEPENDENT_USER ? null : ownerId,
              assignment.version,
              credentials.reason,
              credentials,
            )
          }
          onExecuted={onChanged}
        >
          {actionName}
        </RiskActionButton>
      </Space>
    </Card>
  );
}
