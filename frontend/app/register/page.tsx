"use client";

import { Alert, Form, Input, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthShell, SubmitButton } from "@/components/auth/auth-shell";
import { phoneRules, SmsCodeField } from "@/components/auth/sms-code-field";
import { useSmsCode } from "@/hooks/use-sms-code";
import { registerAccount, userMessage } from "@/lib/auth-client";
import { focusFirstInvalidField } from "@/lib/form-focus";
import { validateConfirmation, validatePassword } from "@/lib/auth-validation";

const { Text } = Typography;

type RegistrationValues = {
  phone: string;
  nickname: string;
  smsCode: string;
  password: string;
  passwordConfirmation: string;
};

export default function RegisterPage() {
  const [form] = Form.useForm<RegistrationValues>();
  const router = useRouter();
  const sms = useSmsCode("register");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (values: RegistrationValues) => {
    setError("");
    setSubmitting(true);
    try {
      const user = await registerAccount({
        phone: values.phone,
        nickname: values.nickname.trim(),
        smsCode: values.smsCode,
        password: values.password,
      });
      router.push(user.home_route);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      eyebrow="创建账号"
      title="开始建立你的 GEO 工作台"
      description="完成短信验证后，账号立即启用并进入 GEO 工作台。"
      footer={
        <Text>
          已有账号？<Link href="/login">立即登录</Link>
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
        autoComplete="on"
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
        <Form.Item
          name="nickname"
          label="昵称"
          rules={[
            { required: true, whitespace: true, message: "请输入昵称" },
            { max: 50, message: "昵称不能超过 50 个字符" },
            { pattern: /^[^\u0000-\u001f\u007f-\u009f]+$/, message: "昵称不能包含控制字符" },
          ]}
        >
          <Input autoComplete="nickname" maxLength={50} placeholder="用于工作台展示" size="large" />
        </Form.Item>
        <SmsCodeField
          form={form}
          send={sms.send}
          sending={sms.sending}
          remaining={sms.remaining}
          onError={setError}
        />
        <Form.Item
          name="password"
          label="设置密码"
          rules={[
            { required: true, message: "请输入密码" },
            { validator: (_, value: string) => validatePassword(value || "") },
          ]}
        >
          <Input.Password autoComplete="new-password" placeholder="至少 10 个字符" size="large" />
        </Form.Item>
        <Form.Item
          name="passwordConfirmation"
          label="确认密码"
          dependencies={["password"]}
          rules={[
            { required: true, message: "请再次输入密码" },
            {
              validator: (_, value: string) =>
                validateConfirmation(form.getFieldValue("password") || "", value || ""),
            },
          ]}
        >
          <Input.Password autoComplete="new-password" placeholder="再次输入密码" size="large" />
        </Form.Item>
        <SubmitButton loading={submitting}>注册并登录</SubmitButton>
      </Form>
    </AuthShell>
  );
}
