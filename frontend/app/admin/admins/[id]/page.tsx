"use client";

import { Alert, Button, Card, Form, Input, Select, Space, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { RiskActionButton } from "@/components/admin/risk-action-button";
import {
  changeAdminRole,
  changeAdminStatus,
  forceLogoutAdmin,
  getAdmin,
  getRoles,
  updateAdmin,
  type AdminProfile,
  type Role,
} from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";
import {
  getRiskActions,
  isApprovalCreated,
  type ApprovalCreated,
  type RiskMode,
} from "@/lib/risk-client";

export default function AdminAccountDetailPage() {
  const capabilities = useAdminCapabilities();
  const { id } = useParams<{ id: string }>();
  const [admin, setAdmin] = useState<AdminProfile | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [roleId, setRoleId] = useState("");
  const [modes, setModes] = useState<Record<string, RiskMode>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [profile, rolePage, actions] = await Promise.all([
        getAdmin(id),
        getRoles(),
        getRiskActions(),
      ]);
      setAdmin(profile);
      setRoleId(profile.role?.id ?? "");
      setRoles(rolePage.results);
      setModes(Object.fromEntries(actions.map((action) => [action.key, action.current_mode])));
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [id]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const approvalCreated = (approval: ApprovalCreated) => {
    setMessage(`已创建审批请求 ${approval.approval_id}，目标状态尚未改变。`);
  };
  const refresh = () => void load();
  const restore = async (action: "enable" | "unlock") => {
    if (!admin) return;
    try {
      const result = await changeAdminStatus(admin.id, action, admin.version);
      if (!isApprovalCreated(result)) setAdmin(result);
    } catch (reason) {
      setError(userMessage(reason));
    }
  };

  return (
    <main className="auth-shell">
      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Button href="/admin/admins">返回管理员列表</Button>
          <Typography.Title level={2}>管理员详情</Typography.Title>
          {error && <Alert type="error" showIcon message={error} />}
          {message && <Alert type="success" showIcon message={message} />}
          {admin && (
            <>
              <Typography.Text>
                {admin.nickname} · {admin.phone_masked} · <Tag>{admin.admin_status}</Tag>
              </Typography.Text>
              {!admin.is_superuser && capabilities?.permission_keys.includes("admins.update") && (
                <>
                  <Form
                    layout="vertical"
                    initialValues={{ nickname: admin.nickname }}
                    onFinish={async ({ nickname }) => {
                      try {
                        setAdmin(
                          await updateAdmin(admin.id, {
                            nickname,
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
                    <Button htmlType="submit">保存普通资料</Button>
                  </Form>
                  <Space>
                    <Select
                      aria-label="管理员角色"
                      value={roleId}
                      style={{ minWidth: 200 }}
                      options={roles
                        .filter((item) => item.status === "active")
                        .map((item) => ({ value: item.id, label: item.name }))}
                      onChange={setRoleId}
                    />
                    <RiskActionButton
                      actionName="变更管理员角色"
                      mode={modes["admin.role.change"] ?? "two_person"}
                      disabled={!roleId}
                      execute={(credentials) =>
                        changeAdminRole(admin.id, roleId, admin.version, credentials)
                      }
                      onExecuted={setAdmin}
                      onApproval={approvalCreated}
                    >
                      保存角色
                    </RiskActionButton>
                  </Space>
                </>
              )}
              {capabilities?.permission_keys.includes("admins.disable") && (
                <Space wrap>
                  <RiskActionButton
                    actionName="强制管理员退出"
                    mode={modes["admin.force_logout"] ?? "confirm"}
                    danger
                    execute={(credentials) =>
                      forceLogoutAdmin(admin.id, admin.logout_version, credentials)
                    }
                    onExecuted={() => {
                      setMessage(
                        admin.user_id === capabilities?.user_id
                          ? "已撤销当前会话；下一次请求将要求重新登录。"
                          : "已撤销目标管理员全部旧会话。",
                      );
                      refresh();
                    }}
                    onApproval={approvalCreated}
                  >
                    强制退出全部设备
                  </RiskActionButton>
                  {admin.admin_status === "active" ? (
                    <>
                      <RiskActionButton
                        actionName="停用管理员"
                        mode={modes["admin.disable"] ?? "two_person"}
                        danger
                        execute={(credentials) =>
                          changeAdminStatus(admin.id, "disable", admin.version, credentials)
                        }
                        onExecuted={setAdmin}
                        onApproval={approvalCreated}
                      >
                        停用
                      </RiskActionButton>
                      <RiskActionButton
                        actionName="紧急锁定管理员"
                        mode={modes["admin.lock"] ?? "password"}
                        danger
                        execute={(credentials) =>
                          changeAdminStatus(admin.id, "lock", admin.version, credentials)
                        }
                        onExecuted={setAdmin}
                        onApproval={approvalCreated}
                      >
                        紧急锁定
                      </RiskActionButton>
                    </>
                  ) : (
                    <Button
                      onClick={() =>
                        void restore(admin.admin_status === "disabled" ? "enable" : "unlock")
                      }
                    >
                      恢复启用（旧会话不恢复）
                    </Button>
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
