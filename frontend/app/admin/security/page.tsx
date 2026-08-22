"use client";

import { Alert, Button, Card, Form, Input, Space, Switch, Table, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  createSuperuserIpAllowlistEntry,
  getSuperuserIpAllowlist,
  getSuperuserSecurity,
  updateSuperuserIpAllowlistEntry,
  updateSuperuserSecurity,
  type IpAllowlistEntry,
  type SuperuserSecurity,
} from "@/lib/admin-rbac-client";
import { IpAllowlistStatusAction } from "@/components/admin/ip-allowlist-status-action";
import { AuthApiError, userMessage } from "@/lib/auth-client";

export default function SuperuserSecurityPage() {
  const [security, setSecurity] = useState<SuperuserSecurity | null>(null);
  const [entries, setEntries] = useState<IpAllowlistEntry[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [nextSecurity, nextEntries] = await Promise.all([
        getSuperuserSecurity(),
        getSuperuserIpAllowlist(),
      ]);
      setSecurity(nextSecurity);
      setEntries(nextEntries);
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  const handleError = (reason: unknown) => {
    setError(
      reason instanceof AuthApiError && reason.code === "IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED"
        ? "新白名单会排除当前网络；明确勾选锁出确认后才能继续。"
        : userMessage(reason),
    );
  };
  if (!security)
    return <Alert type={error ? "error" : "info"} message={error || "正在加载安全策略"} />;
  return (
    <main className="auth-shell">
      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Typography.Title level={2}>超级管理员安全策略</Typography.Title>
          <Alert
            type="info"
            showIcon
            message="普通登录只校验密码；高风险操作的短信 Step-Up 永久启用，IP 白名单默认关闭。"
          />
          {error && <Alert type="error" showIcon message={error} />}
          <Form
            layout="vertical"
            initialValues={{
              ip_allowlist_enabled: security.ip_allowlist_enabled,
              confirm_lockout: false,
            }}
            onFinish={async (values) => {
              try {
                setSecurity(
                  await updateSuperuserSecurity({
                    ...values,
                    expected_security_version: security.security_version,
                  }),
                );
              } catch (reason) {
                handleError(reason);
              }
            }}
          >
            <Form.Item
              name="ip_allowlist_enabled"
              label="启用自己的 IP 白名单"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Form.Item name="current_password" label="当前密码" rules={[{ required: true }]}>
              <Input.Password />
            </Form.Item>
            <Form.Item
              name="confirm_lockout"
              label="确认允许当前网络被锁出"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Button type="primary" htmlType="submit">
              保存策略
            </Button>
          </Form>
          <Form
            layout="inline"
            onFinish={async (values) => {
              try {
                await createSuperuserIpAllowlistEntry({
                  ...values,
                  expected_security_version: security.security_version,
                  confirm_lockout: false,
                });
                await load();
              } catch (reason) {
                handleError(reason);
              }
            }}
          >
            <Form.Item name="network_cidr" rules={[{ required: true }]}>
              <Input placeholder="IPv4 / IPv6 CIDR" />
            </Form.Item>
            <Form.Item name="label">
              <Input placeholder="说明" />
            </Form.Item>
            <Form.Item name="current_password" rules={[{ required: true }]}>
              <Input.Password placeholder="当前密码" />
            </Form.Item>
            <Button htmlType="submit">添加或恢复</Button>
          </Form>
          <Table
            rowKey="id"
            pagination={false}
            dataSource={entries}
            columns={[
              { title: "CIDR", dataIndex: "network_cidr" },
              { title: "版本", dataIndex: "ip_version" },
              { title: "状态", dataIndex: "status" },
              {
                title: "操作",
                render: (_, entry: IpAllowlistEntry) => (
                  <IpAllowlistStatusAction
                    active={entry.status === "active"}
                    onSubmit={async (password) => {
                      try {
                        await updateSuperuserIpAllowlistEntry(entry.id, {
                          status: entry.status === "active" ? "inactive" : "active",
                          current_password: password,
                          expected_security_version: security.security_version,
                          confirm_lockout: false,
                        });
                        await load();
                      } catch (reason) {
                        handleError(reason);
                      }
                    }}
                  />
                ),
              },
            ]}
          />
          <Alert
            type="warning"
            showIcon
            message="紧急恢复仅限服务器控制台；不会关闭短信 2FA，也不会生成绕过凭证。"
          />
        </Space>
      </Card>
    </main>
  );
}
