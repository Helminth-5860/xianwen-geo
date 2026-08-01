"use client";

import { Alert, Button, Card, Form, Input, Select, Space, Table, Typography } from "antd";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  getRiskPolicies,
  updateRiskPolicy,
  type RiskMode,
  type RiskPolicy,
} from "@/lib/risk-client";

const labels: Record<RiskMode, string> = {
  confirm: "显式确认",
  password: "密码再验证",
  two_person: "双人审批",
};

export default function RiskPoliciesPage() {
  const [policies, setPolicies] = useState<RiskPolicy[]>([]);
  const [editing, setEditing] = useState<RiskPolicy | null>(null);
  const [error, setError] = useState("");
  const [form] = Form.useForm<{ current_mode: RiskMode; current_password: string }>();
  const load = () =>
    getRiskPolicies()
      .then(setPolicies)
      .catch((reason) => setError(userMessage(reason)));
  useEffect(() => void load(), []);
  return (
    <main className="admin-page">
      <Typography.Title>高风险策略</Typography.Title>
      <Alert
        type="warning"
        showIcon
        message="risk.policy.update 使用固定保护"
        description="策略修改始终要求有效超级管理员、当前密码、真实 CSRF、确认和乐观版本；不能递归降级。"
      />
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Table
          rowKey="action_key"
          pagination={false}
          dataSource={policies}
          columns={[
            { title: "动作", dataIndex: "action_key" },
            {
              title: "支持模式",
              dataIndex: "supported_modes",
              render: (values: RiskMode[]) => values.map((value) => labels[value]).join(" / "),
            },
            {
              title: "默认",
              dataIndex: "default_mode",
              render: (value) => labels[value as RiskMode],
            },
            {
              title: "最低",
              dataIndex: "minimum_mode",
              render: (value) => labels[value as RiskMode],
            },
            {
              title: "当前",
              dataIndex: "current_mode",
              render: (value) => labels[value as RiskMode],
            },
            {
              title: "操作",
              render: (_, item) => (
                <Button
                  onClick={() => {
                    setEditing(item);
                    form.setFieldsValue({
                      current_mode: item.current_mode,
                      current_password: "",
                    });
                  }}
                >
                  调整
                </Button>
              ),
            },
          ]}
        />
      </Card>
      {editing && (
        <Card title={`调整 ${editing.action_key}`}>
          <Form
            form={form}
            layout="vertical"
            onFinish={async (values) => {
              try {
                await updateRiskPolicy(editing.action_key, {
                  ...values,
                  expected_version: editing.version,
                  confirmed: true,
                });
                setEditing(null);
                form.resetFields();
                await load();
              } catch (reason) {
                setError(userMessage(reason));
              }
            }}
          >
            <Form.Item name="current_mode" label="当前保护模式" rules={[{ required: true }]}>
              <Select
                options={editing.supported_modes.map((mode) => ({
                  value: mode,
                  label: labels[mode],
                  disabled:
                    { confirm: 1, password: 2, two_person: 3 }[mode] <
                    { confirm: 1, password: 2, two_person: 3 }[editing.minimum_mode],
                }))}
              />
            </Form.Item>
            <Form.Item
              name="current_password"
              label="当前登录密码"
              rules={[{ required: true, message: "请输入当前登录密码" }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                确认修改
              </Button>
              <Button onClick={() => setEditing(null)}>取消</Button>
            </Space>
          </Form>
        </Card>
      )}
    </main>
  );
}
