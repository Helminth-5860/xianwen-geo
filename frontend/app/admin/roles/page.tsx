"use client";

import { Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { createRole, getRoles, type Role } from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";

export default function AdminRolesPage() {
  const capabilities = useAdminCapabilities();
  const [roles, setRoles] = useState<Role[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const load = () =>
    getRoles()
      .then((page) => setRoles(page.results))
      .catch((e) => setError(userMessage(e)));
  useEffect(() => void load(), []);
  return (
    <main className="auth-shell">
      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Typography.Title level={2}>角色与数据范围</Typography.Title>
          {error && <Typography.Text type="danger">{error}</Typography.Text>}
          <Button type="primary" onClick={() => setOpen(true)}>
            创建角色
          </Button>
          <Table
            rowKey="id"
            dataSource={roles}
            columns={[
              { title: "名称", dataIndex: "name" },
              { title: "数据范围", dataIndex: "data_scope" },
              { title: "状态", render: (_, item) => <Tag>{item.status}</Tag> },
              {
                title: "操作",
                render: (_, item) => (
                  <Button type="link" href={`/admin/roles/${item.id}`}>
                    配置
                  </Button>
                ),
              },
            ]}
          />
        </Space>
      </Card>
      <Modal
        title="创建角色"
        open={open && Boolean(capabilities?.permission_keys.includes("roles.create"))}
        footer={null}
        onCancel={() => setOpen(false)}
      >
        <Form
          layout="vertical"
          onFinish={async (values) => {
            try {
              await createRole(values);
              setOpen(false);
              await load();
            } catch (reason) {
              setError(userMessage(reason));
            }
          }}
        >
          <Form.Item name="name" label="角色名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea />
          </Form.Item>
          <Form.Item name="data_scope" label="客户数据范围" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "own", label: "仅本人负责" },
                { value: "role", label: "当前角色" },
                { value: "all", label: "全部客户" },
              ]}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            确认创建
          </Button>
        </Form>
      </Modal>
    </main>
  );
}
