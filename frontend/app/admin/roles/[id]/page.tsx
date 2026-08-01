"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Typography,
} from "antd";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  disableRole,
  getPermissions,
  getRole,
  updateRole,
  type CatalogPermission,
  type Role,
} from "@/lib/admin-rbac-client";
import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";

export default function AdminRoleDetailPage() {
  const capabilities = useAdminCapabilities();
  const { id } = useParams<{ id: string }>();
  const [role, setRole] = useState<Role | null>(null);
  const [permissions, setPermissions] = useState<CatalogPermission[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    void Promise.all([getRole(id), getPermissions()])
      .then(([nextRole, catalog]) => {
        setRole(nextRole);
        setPermissions(catalog);
      })
      .catch((reason) => setError(userMessage(reason)));
  }, [id]);
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
          {capabilities?.permission_keys.includes("roles.update") && (
            <Form
              layout="vertical"
              initialValues={{
                name: role.name,
                description: role.description,
                data_scope: role.data_scope,
                permission_keys: role.permission_keys,
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
              <Form.Item name="permission_keys" label="菜单与动作权限">
                <Checkbox.Group>
                  <Space direction="vertical">
                    {assignable.map((item) => (
                      <Checkbox key={item.key} value={item.key}>
                        [{item.permission_type === "menu" ? "菜单" : "动作"}] {item.name}
                      </Checkbox>
                    ))}
                  </Space>
                </Checkbox.Group>
              </Form.Item>
              <Button type="primary" htmlType="submit">
                保存权限
              </Button>
            </Form>
          )}
          {capabilities?.permission_keys.includes("roles.disable") && (
            <Popconfirm
              title="使用中的角色不能停用，确认继续？"
              onConfirm={async () => {
                try {
                  setRole(await disableRole(role.id, role.version));
                } catch (reason) {
                  setError(userMessage(reason));
                }
              }}
            >
              <Button danger>停用角色</Button>
            </Popconfirm>
          )}
        </Space>
      </Card>
    </main>
  );
}
