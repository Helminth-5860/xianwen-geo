"use client";

import { Alert, Form, Input, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthShell, SubmitButton } from "@/components/auth/auth-shell";
import { phoneRules, SmsCodeField } from "@/components/auth/sms-code-field";
import { useSmsCode } from "@/hooks/use-sms-code";
import { resetPassword, userMessage } from "@/lib/auth-client";
import { focusFirstInvalidField } from "@/lib/form-focus";
import { validateConfirmation, validatePassword } from "@/lib/auth-validation";

const { Text } = Typography;
type ResetValues = {
  phone: string;
  smsCode: string;
  newPassword: string;
  passwordConfirmation: string;
};

export default function ForgotPasswordPage() {
  const [form] = Form.useForm<ResetValues>();
  const router = useRouter();
  const sms = useSmsCode("password_reset");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (values: ResetValues) => {
    setError("");
    setSubmitting(true);
    try {
      await resetPassword({
        phone: values.phone,
        smsCode: values.smsCode,
        newPassword: values.newPassword,
      });
      router.push("/login?reset=success");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      eyebrow="找回账号"
      title="重置登录密码"
      description="验证手机号后设置新密码。重置完成后，其他设备需要使用新密码重新登录。"
      footer={
        <Text>
          已想起密码？<Link href="/login">返回登录</Link>
        </Text>
      }
    >
      {error && <Alert type="error" showIcon message={error} role="alert" />}
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
        <SmsCodeField
          form={form}
          send={sms.send}
          sending={sms.sending}
          remaining={sms.remaining}
          onError={setError}
        />
        <Form.Item
          name="newPassword"
          label="新密码"
          rules={[
            { required: true, message: "请输入新密码" },
            { validator: (_, value: string) => validatePassword(value || "") },
          ]}
        >
          <Input.Password autoComplete="new-password" placeholder="至少 10 个字符" size="large" />
        </Form.Item>
        <Form.Item
          name="passwordConfirmation"
          label="确认新密码"
          dependencies={["newPassword"]}
          rules={[
            { required: true, message: "请再次输入新密码" },
            {
              validator: (_, value: string) =>
                validateConfirmation(form.getFieldValue("newPassword") || "", value || ""),
            },
          ]}
        >
          <Input.Password autoComplete="new-password" placeholder="再次输入新密码" size="large" />
        </Form.Item>
        <SubmitButton loading={submitting}>重置密码</SubmitButton>
      </Form>
    </AuthShell>
  );
}
