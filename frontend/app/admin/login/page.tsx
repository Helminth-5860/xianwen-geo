"use client";

import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminLoginWithPassword } from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";

export default function AdminLoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const passwordStep = async (values: { phone: string; password: string }) => {
    setBusy(true);
    setError("");
    try {
      const result = await adminLoginWithPassword(values.phone, values.password);
      router.push(result.user.home_route);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-shell">
      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Typography.Title level={2}>管理员安全登录</Typography.Title>
          <Typography.Text>
            管理员使用独立密码入口；短信验证仅在执行高风险操作时按需触发。
          </Typography.Text>
          {error && <Alert type="error" showIcon role="alert" message={error} />}
          <Form layout="vertical" onFinish={passwordStep} disabled={busy}>
            <Form.Item
              name="phone"
              label="手机号"
              rules={[{ required: true, message: "请输入手机号" }]}
            >
              <Input inputMode="tel" autoComplete="tel" />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={busy}>
              登录后台
            </Button>
          </Form>
          <Alert type="info" showIcon message="高风险操作会在提交时要求短时短信 Step-Up 验证。" />
        </Space>
      </Card>
    </main>
  );
}
