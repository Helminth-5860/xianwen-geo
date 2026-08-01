"use client";

import { Alert, Button, Card, Checkbox, Form, Input, Select, Space, Typography } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { RiskActionButton } from "@/components/admin/risk-action-button";
import {
  disableRole,
  getPermissions,
  getRole,
  replaceRolePermissions,
  updateRole,
  type CatalogPermission,
  type Role,
} from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";
import { getRiskActions, type ApprovalCreated, type RiskMode } from "@/lib/risk-client";

export default function AdminRoleDetailPage() {
  const capabilities = useAdminCapabilities();
  const { id } = useParams<{ id: string }>();
  const [role, setRole] = useState<Role | null>(null);
  const [permissions, setPermissions] = useState<CatalogPermission[]>([]);
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([]);
  const [modes, setModes] = useState<Record<string, RiskMode>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [nextRole, catalog, actions] = await Promise.all([
        getRole(id),
        getPermissions(),
        getRiskActions(),
      ]);
      setRole(nextRole);
      setSelectedPermissions(nextRole.permission_keys);
      setPermissions(catalog);
      setModes(Object.fromEntries(actions.map((action) => [action.key, action.current_mode])));
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [id]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  const approvalCreated = (approval: ApprovalCreated) =>
    setMessage(`已创建审批请求 ${approval.approval_id}，当前配置尚未改变。`);
  if (!role) return <Alert type={error ? "error" : "info"} message={error || "正在加载角色"} />;
  const assignable = permissions.filter((item) => item.status === "active" && !item.superuser_only);
  return (
    <main className="auth-shell">
      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Button href="/admin/roles">返回角色列表</Button>
          <Typography.Title level={2}>角色权限配置</Typography.Title>
          {capabilities?.permission_keys.includes("roles.update") && (
            <Button href={`/admin/roles/${id}/security`}>登录安全与 IP 白名单</Button>
          )}
          {error && <Alert type="error" message={error} />}
          {message && <Alert type="success" message={message} />}
          {capabilities?.permission_keys.includes("roles.update") && (
            <>
              <Form
                layout="vertical"
                initialValues={{
                  name: role.name,
                  description: role.description,
                  data_scope: role.data_scope,
                }}
                onFinish={async (values) => {
                  try {
                    setRole(
                      await updateRole(role.id, {
                        ...values,
                        expected_version: role.version,
                      }),
                    );
                  } catch (reason) {
                    setError(`保存失败，可能存在版本冲突：${userMessage(reason)}`);
                  }
                }}
              >
                <Form.Item name="name" label="角色名称">
                  <Input />
                </Form.Item>
                <Form.Item name="description" label="说明">
                  <Input.TextArea />
                </Form.Item>
                <Form.Item name="data_scope" label="客户数据范围">
                  <Select
                    options={[
                      { value: "own", label: "仅本人负责" },
                      { value: "role", label: "当前角色" },
                      { value: "all", label: "全部客户" },
                    ]}
                  />
                </Form.Item>
                <Button htmlType="submit">保存普通资料</Button>
              </Form>
              <Card title="菜单与动作权限（固定双人审批）">
                <Checkbox.Group
                  value={selectedPermissions}
                  onChange={(values) => setSelectedPermissions(values as string[])}
                >
                  <Space direction="vertical">
                    {assignable.map((item) => (
                      <Checkbox key={item.key} value={item.key}>
                        [{item.permission_type === "menu" ? "菜单" : "动作"}] {item.name}
                      </Checkbox>
                    ))}
                  </Space>
                </Checkbox.Group>
                <RiskActionButton
                  actionName="替换角色权限"
                  mode={modes["role.permissions.replace"] ?? "two_person"}
                  execute={(credentials) =>
                    replaceRolePermissions(role.id, selectedPermissions, role.version, credentials)
                  }
                  onExecuted={setRole}
                  onApproval={approvalCreated}
                >
                  提交权限变更
                </RiskActionButton>
              </Card>
            </>
          )}
          {capabilities?.permission_keys.includes("roles.disable") && (
            <RiskActionButton
              actionName="停用角色"
              mode={modes["role.disable"] ?? "password"}
              danger
              execute={(credentials) => disableRole(role.id, role.version, credentials)}
              onExecuted={setRole}
              onApproval={approvalCreated}
            >
              停用角色
            </RiskActionButton>
          )}
        </Space>
      </Card>
    </main>
  );
}
