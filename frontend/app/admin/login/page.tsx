"use client";

import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  adminLoginWithPassword,
  sendAdminLoginSms,
  verifyAdminLoginSms,
} from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";

export default function AdminLoginPage() {
  const router = useRouter();
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!challengeId || remaining <= 0) return;
    const timer = window.setInterval(() => setRemaining((value) => Math.max(value - 1, 0)), 1000);
    return () => window.clearInterval(timer);
  }, [challengeId, remaining]);

  const passwordStep = async (values: { phone: string; password: string }) => {
    setBusy(true);
    setError("");
    try {
      const result = await adminLoginWithPassword(values.phone, values.password);
      if (!result.requires_2fa) {
        router.push("/admin");
        return;
      }
      setChallengeId(result.challenge_id);
      setRemaining(result.expires_in);
      const sent = await sendAdminLoginSms(result.challenge_id);
      setRemaining(sent.expires_in);
    } catch (reason) {
      setChallengeId(null);
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const smsStep = async (values: { sms_code: string }) => {
    if (!challengeId) return;
    setBusy(true);
    setError("");
    try {
      await verifyAdminLoginSms(challengeId, values.sms_code);
      setChallengeId(null);
      router.push("/admin");
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
            管理员使用独立入口；超级管理员每次必须完成密码和短信验证。
          </Typography.Text>
          {error && <Alert type="error" showIcon role="alert" message={error} />}
          {!challengeId ? (
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
                继续安全验证
              </Button>
            </Form>
          ) : (
            <Form layout="vertical" onFinish={smsStep} disabled={busy || remaining <= 0}>
              <Alert
                type={remaining > 0 ? "info" : "warning"}
                showIcon
                message={
                  remaining > 0 ? `验证码将在 ${remaining} 秒后过期` : "验证已过期，请重新登录"
                }
              />
              <Form.Item
                name="sms_code"
                label="短信验证码"
                rules={[{ required: true, pattern: /^\d{6}$/, message: "请输入 6 位验证码" }]}
              >
                <Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} />
              </Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={busy}>
                  完成登录
                </Button>
                <Button
                  onClick={() => {
                    setChallengeId(null);
                    setRemaining(0);
                    setError("");
                  }}
                >
                  重新开始
                </Button>
              </Space>
            </Form>
          )}
          <Alert type="warning" showIcon message="页面刷新后安全验证会丢失，必须重新输入密码。" />
        </Space>
      </Card>
    </main>
  );
}
