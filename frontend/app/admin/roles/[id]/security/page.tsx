"use client";

import { Alert, Button, Card, Form, Input, Space, Switch, Table, Typography } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  createRoleIpAllowlistEntry,
  getRoleIpAllowlist,
  getRoleSecurity,
  updateRoleIpAllowlistEntry,
  updateRoleSecurity,
  type IpAllowlistEntry,
  type RoleSecurity,
} from "@/lib/admin-rbac-client";
import { IpAllowlistStatusAction } from "@/components/admin/ip-allowlist-status-action";
import { AuthApiError, userMessage } from "@/lib/auth-client";

export default function RoleSecurityPage() {
  const { id } = useParams<{ id: string }>();
  const [security, setSecurity] = useState<RoleSecurity | null>(null);
  const [entries, setEntries] = useState<IpAllowlistEntry[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    try {
      const [nextSecurity, nextEntries] = await Promise.all([
        getRoleSecurity(id),
        getRoleIpAllowlist(id),
      ]);
      setSecurity(nextSecurity);
      setEntries(nextEntries);
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [id]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  const handleError = (reason: unknown) => {
    setError(userMessage(reason));
    if (
      reason instanceof AuthApiError &&
      reason.code === "IP_ALLOWLIST_LOCKOUT_CONFIRMATION_REQUIRED"
    ) {
      setNotice(
        "该配置会排除当前网络；确认风险后可勾选允许锁出并再次提交。当前 IP 不会自动加入。 ",
      );
    }
  };
  if (!security)
    return <Alert type={error ? "error" : "info"} message={error || "正在加载安全策略"} />;
  return (
    <main className="auth-shell">
      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Button href={`/admin/roles/${id}`}>返回角色</Button>
          <Typography.Title level={2}>角色安全与 Step-Up 策略</Typography.Title>
          <Alert
            type="info"
            showIcon
            message="高风险操作统一要求短信 Step-Up；安全策略变化会撤销该角色全部旧管理员会话和未完成验证。"
          />
          {error && <Alert type="error" showIcon message={error} />}
          {notice && <Alert type="warning" showIcon message={notice} />}
          <Form
            layout="vertical"
            initialValues={{
              require_sms_2fa: security.require_sms_2fa,
              ip_allowlist_enabled: security.ip_allowlist_enabled,
              confirm_lockout: false,
            }}
            onFinish={async (values) => {
              try {
                setSecurity(
                  await updateRoleSecurity(id, {
                    ...values,
                    expected_security_version: security.security_version,
                  }),
                );
                setError("");
              } catch (reason) {
                handleError(reason);
              }
            }}
          >
            <Form.Item
              name="require_sms_2fa"
              label="历史短信策略标记（兼容保留，不再作为登录门禁）"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Form.Item name="ip_allowlist_enabled" label="启用 IP 白名单" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item
              name="current_password"
              label="当前超级管理员密码"
              rules={[{ required: true }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Form.Item
              name="confirm_lockout"
              label="确认允许当前网络被锁出"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Button type="primary" htmlType="submit">
              保存安全策略
            </Button>
          </Form>
          <Typography.Title level={3}>IPv4 / IPv6 CIDR</Typography.Title>
          <Form
            layout="inline"
            onFinish={async (values) => {
              try {
                await createRoleIpAllowlistEntry(id, {
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
              <Input placeholder="203.0.113.8 或 2001:db8::/48" />
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
              { title: "IP", dataIndex: "ip_version" },
              { title: "说明", dataIndex: "label" },
              { title: "状态", dataIndex: "status" },
              {
                title: "操作",
                render: (_, entry: IpAllowlistEntry) => (
                  <IpAllowlistStatusAction
                    active={entry.status === "active"}
                    onSubmit={async (password) => {
                      try {
                        await updateRoleIpAllowlistEntry(id, entry.id, {
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
            message="紧急锁出恢复只能由服务器控制台命令执行，不存在网页后门或万能 IP。"
          />
        </Space>
      </Card>
    </main>
  );
}
