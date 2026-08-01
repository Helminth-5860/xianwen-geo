"use client";

import { ArrowLeftOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Descriptions, List, Space, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { UserStatusActions } from "@/components/admin/user-status-actions";
import { getRiskActions, type RiskMode } from "@/lib/risk-client";

import {
  type AdminUser,
  type StatusEvent,
  freezeAdminUser,
  getAdminUser,
  getAdminUserHistory,
  reviewAdminUser,
  unfreezeAdminUser,
  userMessage,
} from "@/lib/auth-client";

const { Text, Title } = Typography;

const eventLabels: Record<StatusEvent["event_type"], string> = {
  approved: "审核通过",
  rejected: "审核拒绝",
  resubmitted: "用户重新提交",
  frozen: "账号冻结",
  unfrozen: "账号解冻",
};

export default function AdminUserDetailPage() {
  const params = useParams<{ id: string }>();
  const userId = params.id;
  const [user, setUser] = useState<AdminUser | null>(null);
  const [history, setHistory] = useState<StatusEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [riskModes, setRiskModes] = useState<Record<string, RiskMode>>({});

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError("");
    try {
      const [current, events, actions] = await Promise.all([
        getAdminUser(userId),
        getAdminUserHistory(userId),
        getRiskActions(),
      ]);
      setUser(current);
      setHistory(events.results);
      setRiskModes(Object.fromEntries(actions.map((action) => [action.key, action.current_mode])));
    } catch (loadError) {
      setError(userMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [userId]);

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
      <Button type="link" href="/admin/users" icon={<ArrowLeftOutlined />}>
        返回审核列表
      </Button>
      <Title>用户审核详情</Title>
      {error && (
        <Alert type="error" showIcon message={error} closable onClose={() => setError("")} />
      )}
      <Card loading={loading}>
        {user && (
          <>
            <Descriptions bordered column={{ xs: 1, sm: 2 }}>
              <Descriptions.Item label="用户 ID">{user.id}</Descriptions.Item>
              <Descriptions.Item label="昵称">{user.nickname}</Descriptions.Item>
              <Descriptions.Item label="手机号">{user.phone_masked}</Descriptions.Item>
              <Descriptions.Item label="审核状态">
                <Tag>{user.approval_status}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="账号状态">
                <Tag>{user.account_status}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="注册时间">
                {new Date(user.created_at).toLocaleString("zh-CN")}
              </Descriptions.Item>
              {user.approval_status === "rejected" && (
                <Descriptions.Item label="当前拒绝原因" span={2}>
                  <Text>{user.approval_reason}</Text>
                </Descriptions.Item>
              )}
            </Descriptions>
            <UserStatusActions
              user={user}
              submitting={submitting}
              rejectMode={riskModes["user.review.reject"] ?? "confirm"}
              freezeMode={riskModes["user.freeze"] ?? "confirm"}
              onApprove={() =>
                void act(() => reviewAdminUser(userId, "approve") as Promise<AdminUser>)
              }
              executeReject={(credentials) =>
                reviewAdminUser(
                  userId,
                  "reject",
                  credentials.reason,
                  user.status_version,
                  credentials,
                )
              }
              executeFreeze={(credentials) =>
                freezeAdminUser(userId, user.status_version, credentials)
              }
              onRiskExecuted={(result) => {
                setUser(result);
                void load();
              }}
              onApproval={(approval) =>
                setError(`已创建审批请求 ${approval.approval_id}，当前尚未执行。`)
              }
              onUnfreeze={() => void act(() => unfreezeAdminUser(userId))}
            />
          </>
        )}
      </Card>
      <Card title="审核与账号状态历史">
        <List
          dataSource={history}
          locale={{ emptyText: "暂无状态历史" }}
          renderItem={(event) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <Space>
                    <Tag>{event.status_domain}</Tag>
                    {eventLabels[event.event_type]}
                  </Space>
                }
                description={
                  <Space direction="vertical" size={2}>
                    <Text>
                      {event.from_value} → {event.to_value}
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
