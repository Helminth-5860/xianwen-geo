"use client";

import { Alert, Button, Card, Form, Input, Popconfirm, Select, Space, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  changeAdminStatus,
  getAdmin,
  forceLogoutAdmin,
  getRoles,
  updateAdmin,
  type AdminProfile,
  type Role,
} from "@/lib/admin-rbac-client";
import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { AuthApiError, userMessage } from "@/lib/auth-client";

export default function AdminAccountDetailPage() {
  const capabilities = useAdminCapabilities();
  const { id } = useParams<{ id: string }>();
  const [admin, setAdmin] = useState<AdminProfile | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [profile, rolePage] = await Promise.all([getAdmin(id), getRoles()]);
      setAdmin(profile);
      setRoles(rolePage.results);
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [id]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  const status = async (action: string) => {
    if (!admin) return;
    try {
      setAdmin(await changeAdminStatus(admin.id, action, admin.version));
    } catch (reason) {
      setError(
        reason instanceof AuthApiError && reason.code === "ADMIN_HAS_ASSIGNED_CUSTOMERS"
          ? "该管理员仍有负责客户，请先转交；紧急情况可使用锁定。"
          : userMessage(reason),
      );
    }
  };
  return (
    <main className="auth-shell">
      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Button href="/admin/admins">返回管理员列表</Button>
          <Typography.Title level={2}>管理员详情</Typography.Title>
          {error && <Alert type="error" message={error} showIcon />}
          {admin && (
            <>
              <Typography.Text>
                {admin.nickname} · {admin.phone_masked} · <Tag>{admin.admin_status}</Tag>
              </Typography.Text>
              {!admin.is_superuser && capabilities?.permission_keys.includes("admins.update") && (
                <Form
                  layout="vertical"
                  initialValues={{ nickname: admin.nickname, role_id: admin.role?.id }}
                  onFinish={async (values) => {
                    try {
                      setAdmin(
                        await updateAdmin(admin.id, {
                          ...values,
                          expected_version: admin.version,
                        }),
                      );
                    } catch (reason) {
                      setError(userMessage(reason));
                    }
                  }}
                >
                  <Form.Item name="nickname" label="昵称">
                    <Input />
                  </Form.Item>
                  <Form.Item name="role_id" label="角色">
                    <Select
                      options={roles
                        .filter((item) => item.status === "active")
                        .map((item) => ({ value: item.id, label: item.name }))}
                    />
                  </Form.Item>
                  <Button htmlType="submit">保存资料与角色</Button>
                </Form>
              )}
              {capabilities?.permission_keys.includes("admins.disable") && (
                <Popconfirm
                  title="确认强制退出该管理员全部设备？"
                  description="操作通过 session_version 撤销全部旧会话，不会修改账号状态。"
                  onConfirm={async () => {
                    try {
                      await forceLogoutAdmin(admin.id);
                      setError(
                        admin.id === capabilities?.id
                          ? "已撤销当前会话；下一次请求将要求重新登录。"
                          : "已撤销该管理员全部旧会话。",
                      );
                    } catch (reason) {
                      setError(userMessage(reason));
                    }
                  }}
                >
                  <Button danger>强制退出全部设备</Button>
                </Popconfirm>
              )}
              {capabilities?.permission_keys.includes("admins.disable") && (
                <Space wrap>
                  {admin.admin_status === "active" ? (
                    <>
                      <Popconfirm
                        title="确认停用？有负责客户时会被拒绝。"
                        onConfirm={() => void status("disable")}
                      >
                        <Button danger>停用</Button>
                      </Popconfirm>
                      <Popconfirm
                        title="确认紧急锁定？旧会话将立即失效。"
                        onConfirm={() => void status("lock")}
                      >
                        <Button danger>紧急锁定</Button>
                      </Popconfirm>
                    </>
                  ) : (
                    <Popconfirm
                      title="确认恢复？旧会话不会恢复。"
                      onConfirm={() =>
                        void status(admin.admin_status === "disabled" ? "enable" : "unlock")
                      }
                    >
                      <Button>恢复启用</Button>
                    </Popconfirm>
                  )}
                </Space>
              )}
            </>
          )}
        </Space>
      </Card>
    </main>
  );
}
