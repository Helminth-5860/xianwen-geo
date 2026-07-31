"use client";

import { Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  createAdmin,
  getAdmins,
  getRoles,
  type AdminProfile,
  type Role,
} from "@/lib/admin-rbac-client";
import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";

export default function AdminAccountsPage() {
  const capabilities = useAdminCapabilities();
  const [admins, setAdmins] = useState<AdminProfile[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [adminPage, rolePage] = await Promise.all([getAdmins(), getRoles()]);
      setAdmins(adminPage.results);
      setRoles(rolePage.results.filter((item) => item.status === "active"));
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  return (
    <main className="auth-shell">
      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Typography.Title level={2}>管理员账号</Typography.Title>
          {error && <Typography.Text type="danger">{error}</Typography.Text>}
          <Button type="primary" onClick={() => setOpen(true)}>
            创建普通管理员
          </Button>
          <Table
            rowKey="id"
            dataSource={admins}
            columns={[
              { title: "昵称", dataIndex: "nickname" },
              { title: "手机号", dataIndex: "phone_masked" },
              { title: "角色", render: (_, item) => item.role?.name || "超级管理员" },
              {
                title: "状态",
                render: (_, item) => <Tag>{item.admin_status}</Tag>,
              },
              {
                title: "操作",
                render: (_, item) => (
                  <Button type="link" href={`/admin/admins/${item.id}`}>
                    查看
                  </Button>
                ),
              },
            ]}
          />
        </Space>
      </Card>
      <Modal
        title="创建普通管理员"
        open={open && Boolean(capabilities?.permission_keys.includes("admins.create"))}
        footer={null}
        onCancel={() => setOpen(false)}
      >
        <Form
          layout="vertical"
          onFinish={async (values) => {
            try {
              await createAdmin(values);
              setOpen(false);
              await load();
            } catch (reason) {
              setError(userMessage(reason));
            }
          }}
        >
          <Form.Item name="phone" label="手机号" rules={[{ required: true }]}>
            <Input autoComplete="tel" />
          </Form.Item>
          <Form.Item name="nickname" label="昵称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="role_id" label="角色" rules={[{ required: true }]}>
            <Select options={roles.map((item) => ({ value: item.id, label: item.name }))} />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            确认创建
          </Button>
        </Form>
      </Modal>
    </main>
  );
}
