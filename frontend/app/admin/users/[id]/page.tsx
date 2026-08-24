"use client";

import { ArrowLeftOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Descriptions, List, Space, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { CustomerAssignmentActions } from "@/components/admin/customer-assignment-actions";
import { TrialGrantAction } from "@/components/admin/trial-grant-action";
import {
  getAdmins,
  getCustomerAssignment,
  type AdminProfile,
  type CustomerAssignment,
} from "@/lib/admin-rbac-client";
import { UserStatusActions } from "@/components/admin/user-status-actions";
import { getRiskActions, type RiskMode } from "@/lib/risk-client";

import {
  type AdminUser,
  type StatusEvent,
  freezeAdminUser,
  getAdminUser,
  getAdminUserHistory,
  unfreezeAdminUser,
  userMessage,
} from "@/lib/auth-client";

const { Text } = Typography;

const eventLabels: Record<StatusEvent["event_type"], string> = {
  frozen: "账号已禁用",
  unfrozen: "账号已恢复",
};

const accountValueLabels: Record<string, string> = {
  active: "正常",
  frozen: "禁用",
  cancel_pending: "禁用",
  cancelled: "禁用",
};

export default function AdminUserDetailPage() {
  const params = useParams<{ id: string }>();
  const userId = params.id;
  const capabilities = useAdminCapabilities();
  const [user, setUser] = useState<AdminUser | null>(null);
  const [history, setHistory] = useState<StatusEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [riskModes, setRiskModes] = useState<Record<string, RiskMode>>({});
  const [assignment, setAssignment] = useState<CustomerAssignment | null>(null);
  const [admins, setAdmins] = useState<AdminProfile[]>([]);

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError("");
    try {
      const canAssign = Boolean(capabilities?.permission_keys.includes("users.assign"));
      const [current, events, actions, assignmentData, adminPage] = await Promise.all([
        getAdminUser(userId),
        getAdminUserHistory(userId),
        getRiskActions(),
        canAssign ? getCustomerAssignment(userId) : Promise.resolve(null),
        canAssign && capabilities?.permission_keys.includes("admins.list")
          ? getAdmins()
          : Promise.resolve(null),
      ]);
      setUser(current);
      setHistory(events.results);
      setAssignment(assignmentData);
      setAdmins(adminPage?.results ?? []);
      setRiskModes(Object.fromEntries(actions.map((action) => [action.key, action.current_mode])));
    } catch (loadError) {
      setError(userMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [capabilities, userId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const act = async (operation: () => Promise<AdminUser>) => {
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      setUser(await operation());
      await load();
    } catch (actionError) {
      setError(userMessage(actionError));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="admin-page">
      <AdminPageHeader
        title="用户详情"
        description="查看用户基础信息、所属管理员、账号状态和可用套餐。"
        actions={
          <Button href="/admin/users" icon={<ArrowLeftOutlined />}>
            返回用户列表
          </Button>
        }
      />
      {error && <Alert type="error" showIcon title={error} closable onClose={() => setError("")} />}
      <Card loading={loading}>
        {user && (
          <>
            <Descriptions bordered column={{ xs: 1, sm: 2 }}>
              <Descriptions.Item label="用户 ID">{user.id}</Descriptions.Item>
              <Descriptions.Item label="昵称">{user.nickname}</Descriptions.Item>
              <Descriptions.Item label="手机号">{user.phone_masked}</Descriptions.Item>
              <Descriptions.Item label="账号状态">
                <Tag color={user.account_status === "active" ? "green" : "orange"}>
                  {user.account_status === "active" ? "正常" : "禁用"}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="注册时间">
                {new Date(user.created_at).toLocaleString("zh-CN")}
              </Descriptions.Item>
            </Descriptions>
            <UserStatusActions
              user={user}
              submitting={submitting}
              freezeMode={riskModes["user.freeze"] ?? "confirm"}
              executeFreeze={(credentials) =>
                freezeAdminUser(userId, user.status_version, credentials)
              }
              onRiskExecuted={(result) => {
                setUser(result);
                void load();
              }}
              onUnfreeze={() => void act(() => unfreezeAdminUser(userId))}
            />
            {user.account_status === "active" && (
              <TrialGrantAction
                userId={user.id}
                expectedVersion={user.status_version}
                onCompleted={() => void load()}
                onError={setError}
              />
            )}
          </>
        )}
      </Card>
      {capabilities?.permission_keys.includes("users.assign") && assignment && (
        <CustomerAssignmentActions
          key={`${assignment.customer_id}:${assignment.version}:${assignment.owner_admin_id}`}
          assignment={assignment}
          admins={admins}
          mode={riskModes["customer.assignment.change"] ?? "password"}
          onChanged={(changed) => {
            setAssignment(changed);
            void load();
          }}
        />
      )}
      <Card title="账号变更记录">
        <List
          dataSource={history}
          locale={{ emptyText: "暂无状态历史" }}
          renderItem={(event) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <Space>
                    <Tag>账号状态</Tag>
                    {eventLabels[event.event_type]}
                  </Space>
                }
                description={
                  <Space orientation="vertical" size={2}>
                    <Text>
                      {accountValueLabels[event.from_value] ?? event.from_value} →{" "}
                      {accountValueLabels[event.to_value] ?? event.to_value}
                    </Text>
                    {event.reason && <Text>原因：{event.reason}</Text>}
                    <Text type="secondary">
                      {new Date(event.created_at).toLocaleString("zh-CN")}
                    </Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      </Card>
    </main>
  );
}
