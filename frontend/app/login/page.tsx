"use client";

import { Alert, Form, Input, Segmented, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { AuthShell, SubmitButton } from "@/components/auth/auth-shell";
import { phoneRules, SmsCodeField } from "@/components/auth/sms-code-field";
import { useSmsCode } from "@/hooks/use-sms-code";
import { loginWithPassword, loginWithSms, userMessage } from "@/lib/auth-client";
import { focusFirstInvalidField } from "@/lib/form-focus";

const { Text } = Typography;
type LoginMode = "password" | "sms";
type LoginValues = { phone: string; password?: string; smsCode?: string };

export const LOGIN_MODE_OPTIONS: { label: string; value: LoginMode }[] = [
  { label: "密码登录", value: "password" },
  { label: "短信登录", value: "sms" },
];

export default function LoginPage() {
  const [form] = Form.useForm<LoginValues>();
  const router = useRouter();
  const sms = useSmsCode("login");
  const [mode, setMode] = useState<LoginMode>("password");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const resetComplete = useSyncExternalStore(
    () => () => undefined,
    () => new URLSearchParams(window.location.search).get("reset") === "success",
    () => false,
  );

  const submit = async (values: LoginValues) => {
    setError("");
    setSubmitting(true);
    try {
      const user =
        mode === "password"
          ? await loginWithPassword(values.phone, values.password || "")
          : await loginWithSms(values.phone, values.smsCode || "");
      router.push(user.approval_status === "pending" ? "/?account=pending" : "/");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      eyebrow="欢迎回来"
      title="登录显问工作台"
      description="使用密码或短信验证码登录。登录状态仅保存在安全的 HttpOnly Cookie 中。"
      footer={
        <Text>
          还没有账号？<Link href="/register">立即注册</Link>
        </Text>
      }
    >
      {resetComplete && <Alert type="success" showIcon message="密码已重置，请使用新密码登录" />}
      {error && <Alert type="error" showIcon message={error} role="alert" />}
      <Segmented<LoginMode>
        block
        value={mode}
        options={LOGIN_MODE_OPTIONS}
        onChange={(value) => {
          setMode(value);
          setError("");
        }}
        aria-label="登录方式"
      />
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        onFinish={submit}
        onFinishFailed={focusFirstInvalidField(form)}
        disabled={submitting}
      >
        <Form.Item name="phone" label="手机号" rules={phoneRules}>
          <Input
            inputMode="tel"
            autoComplete="tel"
            placeholder="请输入中国大陆手机号"
            size="large"
          />
        </Form.Item>
        {mode === "password" ? (
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: "请输入密码" }]}
          >
            <Input.Password autoComplete="current-password" placeholder="请输入密码" size="large" />
          </Form.Item>
        ) : (
          <SmsCodeField
            form={form}
            send={sms.send}
            sending={sms.sending}
            remaining={sms.remaining}
            onError={setError}
          />
        )}
        <div className="auth-form-meta">
          <Link href="/forgot-password">忘记密码？</Link>
        </div>
        <SubmitButton loading={submitting}>登录</SubmitButton>
      </Form>
    </AuthShell>
  );
}
