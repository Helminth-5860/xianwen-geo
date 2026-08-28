"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { RiskActionButton } from "@/components/admin/risk-action-button";
import { userMessage } from "@/lib/auth-client";
import {
  changeAdminPlanApplication,
  getAdminPlanApplication,
  type AdminPlanApplication,
  openSubscriptionFromApplication,
} from "@/lib/plans-client";
import { getRiskActions, type RiskMode } from "@/lib/risk-client";

export default function AdminPlanApplicationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const capabilities = useAdminCapabilities();
  const [item, setItem] = useState<AdminPlanApplication | null>(null);
  const [modes, setModes] = useState<Record<string, RiskMode>>({});
  const [activateOpen, setActivateOpen] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState("");
  const [overrideVersion, setOverrideVersion] = useState("");
  const [overrideConfirmed, setOverrideConfirmed] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    void Promise.all([getAdminPlanApplication(id), getRiskActions()])
      .then(([application, actions]) => {
        setItem(application);
        setModes(Object.fromEntries(actions.map((action) => [action.key, action.current_mode])));
      })
      .catch((reason) => setError(userMessage(reason)));
  }, [id]);
  if (error) return <Alert type="error" showIcon title={error} />;
  if (!item) return <Spin description="正在加载套餐申请" />;
  const canContact = capabilities?.permission_keys.includes("plan_applications.contact") ?? false;
  const canClose = capabilities?.permission_keys.includes("plan_applications.close") ?? false;
  const canOpen = capabilities?.permission_keys.includes("subscriptions.open") ?? false;
  const canOverride =
    capabilities?.permission_keys.includes("subscriptions.override_version") ?? false;
  return (
    <main className="admin-page">
      <Typography.Title>套餐申请详情</Typography.Title>
      {!canContact && !canClose && (
        <Alert type="info" showIcon title="当前账号没有处理此申请的权限" />
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
            >
              关闭申请
            </RiskActionButton>
          )}
          {canOpen && (item.status === "pending" || item.status === "contacted") && (
            <Button type="primary" onClick={() => setActivateOpen(true)}>
              开通订阅
            </Button>
          )}
        </Space>
      </Card>
      <Modal
        title="确认开通订阅"
        open={activateOpen}
        onCancel={() => setActivateOpen(false)}
        onOk={async () => {
          try {
            await openSubscriptionFromApplication(item.id, item.version, {
              selectedPlanVersionId: overrideVersion || null,
              confirmUnavailable: unavailable,
              unavailableReason,
              confirmVersionOverride: overrideConfirmed,
              overrideReason,
            });
            setItem(await getAdminPlanApplication(id));
            setActivateOpen(false);
          } catch (reason) {
            setError(userMessage(reason));
          }
        }}
        okText="确认开通"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Alert type="warning" showIcon title="确认后将立即开通，并写入操作记录。" />
          <Checkbox
            checked={unavailable}
            onChange={(event) => setUnavailable(event.target.checked)}
          >
            确认离线套餐或退役版本仍需开通
          </Checkbox>
          <Input
            aria-label="特殊状态开通原因"
            value={unavailableReason}
            onChange={(event) => setUnavailableReason(event.target.value)}
          />
          {canOverride && (
            <>
              <Input
                aria-label="替换套餐版本 ID"
                value={overrideVersion}
                onChange={(event) => setOverrideVersion(event.target.value)}
              />
              <Checkbox
                checked={overrideConfirmed}
                onChange={(event) => setOverrideConfirmed(event.target.checked)}
              >
                确认替换申请绑定版本
              </Checkbox>
              <Input
                aria-label="替换版本原因"
                value={overrideReason}
                onChange={(event) => setOverrideReason(event.target.value)}
              />
            </>
          )}
        </Space>
      </Modal>
    </main>
  );
}
