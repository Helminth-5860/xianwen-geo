"use client";

import { Alert, Card, Descriptions, Space, Spin, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { RiskActionButton } from "@/components/admin/risk-action-button";
import { userMessage } from "@/lib/auth-client";
import {
  changeAdminPlanApplication,
  getAdminPlanApplication,
  type AdminPlanApplication,
} from "@/lib/plans-client";
import { getRiskActions, type ApprovalCreated, type RiskMode } from "@/lib/risk-client";

export default function AdminPlanApplicationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const capabilities = useAdminCapabilities();
  const [item, setItem] = useState<AdminPlanApplication | null>(null);
  const [modes, setModes] = useState<Record<string, RiskMode>>({});
  const [approval, setApproval] = useState<ApprovalCreated | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void Promise.all([getAdminPlanApplication(id), getRiskActions()])
      .then(([application, actions]) => {
        setItem(application);
        setModes(Object.fromEntries(actions.map((action) => [action.key, action.current_mode])));
      })
      .catch((reason) => setError(userMessage(reason)));
  }, [id]);
  if (error) return <Alert type="error" showIcon message={error} />;
  if (!item) return <Spin description="正在加载套餐申请" />;
  const canContact = capabilities?.permission_keys.includes("plan_applications.contact") ?? false;
  const canClose = capabilities?.permission_keys.includes("plan_applications.close") ?? false;
  return (
    <main className="admin-page">
      <Typography.Title>套餐申请详情</Typography.Title>
      {approval && (
        <Alert
          type="warning"
          showIcon
          message="已发起双人审批"
          description={`审批编号：${approval.approval_id}`}
        />
      )}
      {!canContact && !canClose && (
        <Alert type="info" showIcon message="当前账号没有处理此申请的权限" />
      )}
      <Card>
        <Descriptions column={1}>
          <Descriptions.Item label="申请编号">{item.id}</Descriptions.Item>
          <Descriptions.Item label="用户">{item.applicant_nickname}</Descriptions.Item>
          <Descriptions.Item label="联系电话">{item.applicant_phone}</Descriptions.Item>
          <Descriptions.Item label="绑定版本">第 {item.requested_version_no} 版</Descriptions.Item>
          <Descriptions.Item label="公开快照">
            {String(item.public_plan_snapshot.name)}
          </Descriptions.Item>
          <Descriptions.Item label="当前负责人">
            {item.current_owner?.nickname ?? "未分配"}
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag>{item.status}</Tag>
          </Descriptions.Item>
        </Descriptions>
        <Space>
          {canContact && item.status === "pending" && (
            <RiskActionButton
              actionName="标记已联系"
              mode={modes["plan_application.contact"] ?? "confirm"}
              execute={(credentials) =>
                changeAdminPlanApplication(item.id, "contact", item.version, credentials)
              }
              onExecuted={setItem}
              onApproval={setApproval}
            >
              标记已联系
            </RiskActionButton>
          )}
          {canClose && (item.status === "pending" || item.status === "contacted") && (
            <RiskActionButton
              actionName="关闭申请"
              danger
              mode={modes["plan_application.close"] ?? "confirm"}
              execute={(credentials) =>
                changeAdminPlanApplication(item.id, "close", item.version, credentials)
              }
              onExecuted={setItem}
              onApproval={setApproval}
            >
              关闭申请
            </RiskActionButton>
          )}
        </Space>
      </Card>
    </main>
  );
}
