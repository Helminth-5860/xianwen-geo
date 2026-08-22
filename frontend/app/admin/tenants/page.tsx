"use client";

import { Button, Card, Form, Input, Modal, Space, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { createTenant, getTenants, type Tenant } from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";

export default function TenantManagementPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      setTenants(await getTenants());
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
          <Typography.Title level={2}>租户与品牌</Typography.Title>
          <Typography.Text>平台超级管理员管理租户边界、展示名称与品牌引用。</Typography.Text>
          {error && <Typography.Text type="danger">{error}</Typography.Text>}
          <Button type="primary" onClick={() => setOpen(true)}>
            创建租户
          </Button>
          <Table
            rowKey="id"
            dataSource={tenants}
            columns={[
              { title: "租户", dataIndex: "display_name" },
              { title: "标识", dataIndex: "key" },
              { title: "品牌", dataIndex: "brand_name" },
              { title: "用户数", dataIndex: "user_count" },
              { title: "状态", render: (_, item) => <Tag>{item.status}</Tag> },
            ]}
          />
        </Space>
      </Card>
      <Modal title="创建租户" open={open} footer={null} onCancel={() => setOpen(false)}>
        <Form
          layout="vertical"
          onFinish={async (values) => {
            try {
              await createTenant({ ...values, status: "active", logo_reference: "" });
              setOpen(false);
              await load();
            } catch (reason) {
              setError(userMessage(reason));
            }
          }}
        >
          <Form.Item name="key" label="租户标识" rules={[{ required: true }]}>
            <Input placeholder="company-key" />
          </Form.Item>
          <Form.Item name="display_name" label="租户名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="brand_name" label="品牌名称">
            <Input />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            确认创建
          </Button>
        </Form>
      </Modal>
    </main>
  );
}
