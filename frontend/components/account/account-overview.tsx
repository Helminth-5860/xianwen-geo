"use client";

import { BellOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Form, Input, List, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  type AccountNotification,
  type AccountUser,
  AuthApiError,
  getCurrentUser,
  getNotifications,
  markNotificationRead,
  resubmitApproval,
  userMessage,
} from "@/lib/auth-client";

const { Text, Title } = Typography;

export function AccountOverview() {
  const [user, setUser] = useState<AccountUser | null>(null);
  const [notifications, setNotifications] = useState<AccountNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [form] = Form.useForm<{ nickname: string }>();

  const load = useCallback(async () => {
    try {
      const current = await getCurrentUser();
      setUser(current);
      form.setFieldsValue({ nickname: current.nickname });
      const notificationPage = await getNotifications();
      setNotifications(notificationPage.results);
    } catch (error) {
      if (!(error instanceof AuthApiError && error.status === 401)) setMessage(userMessage(error));
    } finally {
      setLoading(false);
    }
  }, [form]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading || !user) return null;

  const resubmit = async ({ nickname }: { nickname: string }) => {
    setSubmitting(true);
    setMessage("");
    try {
      const updated = await resubmitApproval(nickname);
      setUser(updated);
      setMessage("资料已重新提交，请等待管理员审核。");
    } catch (error) {
      setMessage(userMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  const markRead = async (notification: AccountNotification) => {
    if (notification.read_at) return;
    try {
      const updated = await markNotificationRead(notification.id);
      setNotifications((items) => items.map((item) => (item.id === updated.id ? updated : item)));
    } catch (error) {
      setMessage(userMessage(error));
    }
  };

  return (
    <section className="account-overview" aria-label="账号状态与通知">
      {message && <Alert closable message={message} onClose={() => setMessage("")} />}
      <Card>
        <Space direction="vertical" size="middle" className="account-overview-content">
          <Space>
            <SafetyCertificateOutlined />
            <Title level={3}>账号状态</Title>
          </Space>
          <Space wrap>
            <Text>{user.nickname}</Text>
            <Tag color={user.approval_status === "approved" ? "green" : "blue"}>
              {user.approval_status === "approved"
                ? "审核通过"
                : user.approval_status === "rejected"
                  ? "审核未通过"
                  : "等待审核"}
            </Tag>
          </Space>
          {user.approval_status === "pending" && (
            <Alert type="info" message="资料正在审核中，请耐心等待。" showIcon />
          )}
          {user.approval_status === "rejected" && (
            <>
              <Alert
                type="warning"
                showIcon
                message="审核未通过"
                description={user.approval_reason || "请完善资料后重新提交。"}
              />
              <Form form={form} layout="vertical" onFinish={resubmit}>
                <Form.Item
                  name="nickname"
                  label="昵称"
                  rules={[{ required: true, message: "请输入昵称" }, { max: 50 }]}
                >
                  <Input maxLength={50} />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={submitting}>
                  重新提交审核
                </Button>
              </Form>
            </>
          )}
        </Space>
      </Card>
      <Card
        title={
          <Space>
            <BellOutlined />
            站内通知
          </Space>
        }
      >
        {notifications.length ? (
          <List
            dataSource={notifications}
            renderItem={(notification) => (
              <List.Item
                actions={
                  notification.read_at
                    ? []
                    : [
                        <Button key="read" type="link" onClick={() => void markRead(notification)}>
                          标记已读
                        </Button>,
                      ]
                }
              >
                <List.Item.Meta
                  title={
                    <Space>
                      {notification.title}
                      {!notification.read_at && <Tag color="blue">未读</Tag>}
                    </Space>
                  }
                  description={notification.safe_summary}
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />
        )}
      </Card>
    </section>
  );
}
