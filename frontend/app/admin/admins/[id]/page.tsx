"use client";

import { Alert, Button, Card, Form, Input, Space, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { RiskActionButton } from "@/components/admin/risk-action-button";
import {
  changeAdminStatus,
  forceLogoutAdmin,
  getAdmin,
  getAdminRegistrationLink,
  updateAdmin,
  type AdminProfile,
} from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";
import { getRiskActions, type RiskMode } from "@/lib/risk-client";

export default function AdminAccountDetailPage() {
  const capabilities = useAdminCapabilities();
  const { id } = useParams<{ id: string }>();
  const [admin, setAdmin] = useState<AdminProfile | null>(null);
  const [modes, setModes] = useState<Record<string, RiskMode>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [registrationUrl, setRegistrationUrl] = useState("");
  const [registrationLinkUsable, setRegistrationLinkUsable] = useState(true);
  const load = useCallback(async () => {
    try {
      const [profile, actions] = await Promise.all([getAdmin(id), getRiskActions()]);
      setAdmin(profile);
      setModes(Object.fromEntries(actions.map((action) => [action.key, action.current_mode])));
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [id]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const refresh = () => void load();
  const restore = async (action: "enable" | "unlock") => {
    if (!admin) return;
    try {
      setAdmin(await changeAdminStatus(admin.id, action, admin.version));
    } catch (reason) {
      setError(userMessage(reason));
    }
  };

  return (
    <main className="admin-page">
      <AdminPageHeader
        title="管理员详情"
        description="维护管理员基础信息、专属注册链接和账号启停状态。"
        actions={<Button href="/admin/admins">返回管理员列表</Button>}
      />
      <Card className="admin-surface">
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
          {error && <Alert type="error" showIcon title={error} />}
          {message && <Alert type="success" showIcon title={message} />}
          {admin && (
            <>
              <Typography.Text>
                {admin.nickname} · {admin.phone_masked} ·{" "}
                <Tag color={admin.admin_status === "active" ? "green" : "orange"}>
                  {admin.admin_status === "active"
                    ? "正常"
                    : admin.admin_status === "disabled"
                      ? "已停用"
                      : "已锁定"}
                </Tag>
              </Typography.Text>
              {!admin.is_superuser && capabilities?.commercial_identity === "SUPER_ADMIN" && (
                <Card size="small" title="管理员专属注册链接">
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    <Button
                      onClick={async () => {
                        try {
                          const result = await getAdminRegistrationLink(admin.id);
                          setRegistrationUrl(
                            new URL(result.registration_path, window.location.origin).toString(),
                          );
                          setRegistrationLinkUsable(result.usable);
                        } catch (reason) {
                          setError(userMessage(reason));
                        }
                      }}
                    >
                      获取专属注册链接
                    </Button>
                    {registrationUrl && (
                      <Typography.Paragraph copyable={{ text: registrationUrl }}>
                        {registrationUrl}
                      </Typography.Paragraph>
                    )}
                    {!registrationLinkUsable && (
                      <Alert
                        type="warning"
                        showIcon
                        title="该管理员当前不可用，注册链接会拒绝注册"
                      />
                    )}
                  </Space>
                </Card>
              )}
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
                    <Form.Item name="nickname" label="管理员名称">
                      <Input />
                    </Form.Item>
                    <Button htmlType="submit">保存基础信息</Button>
                  </Form>
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
                  >
                    强制退出全部设备
                  </RiskActionButton>
                  {admin.admin_status === "active" ? (
                    <>
                      <RiskActionButton
                        actionName="停用管理员"
                        mode={modes["admin.disable"] ?? "password"}
                        danger
                        execute={(credentials) =>
                          changeAdminStatus(admin.id, "disable", admin.version, credentials)
                        }
                        onExecuted={setAdmin}
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
