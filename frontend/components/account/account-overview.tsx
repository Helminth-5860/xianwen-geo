"use client";

import { BellOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, List, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  type AccountNotification,
  type AccountUser,
  AuthApiError,
  getCurrentUser,
  getNotifications,
  markNotificationRead,
  userMessage,
} from "@/lib/auth-client";

const { Text, Title } = Typography;

export function AccountOverview() {
  const [user, setUser] = useState<AccountUser | null>(null);
  const [notifications, setNotifications] = useState<AccountNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const current = await getCurrentUser();
      setUser(current);
      const notificationPage = await getNotifications();
      setNotifications(notificationPage.results);
    } catch (error) {
      if (!(error instanceof AuthApiError && error.status === 401)) setMessage(userMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading || !user) return null;

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
            <Tag color={user.account_status === "active" ? "green" : "orange"}>
              {user.account_status === "active" ? "正常" : "禁用"}
            </Tag>
          </Space>
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
