"use client";

import { Alert, Form, Input, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthShell, SubmitButton } from "@/components/auth/auth-shell";
import { phoneRules, SmsCodeField } from "@/components/auth/sms-code-field";
import { useSmsCode } from "@/hooks/use-sms-code";
import { registerAccount, userMessage, validateRegistrationReference } from "@/lib/auth-client";
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
  const [registrationRef, setRegistrationRef] = useState("");
  const [channelName, setChannelName] = useState("");
  const [channelStatus, setChannelStatus] = useState<"none" | "checking" | "valid" | "invalid">(
    "none",
  );

  useEffect(() => {
    let current = true;
    const timer = window.setTimeout(() => {
      const ref = new URLSearchParams(window.location.search).get("ref") ?? "";
      setRegistrationRef(ref);
      if (!ref) {
        return;
      }
      setChannelStatus("checking");
      void validateRegistrationReference(ref)
        .then((result) => {
          if (!current) return;
          setChannelName(result.channel_name);
          setChannelStatus("valid");
        })
        .catch(() => {
          if (current) setChannelStatus("invalid");
        });
    }, 0);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, []);

  const submit = async (values: RegistrationValues) => {
    setError("");
    setSubmitting(true);
    try {
      const user = await registerAccount({
        phone: values.phone,
        nickname: values.nickname.trim(),
        smsCode: values.smsCode,
        password: values.password,
        ref: registrationRef,
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
      {channelStatus === "none" && (
        <Alert type="info" showIcon message="无需邀请，完成验证即可注册独立用户。" />
      )}
      {channelStatus === "checking" && (
        <Alert type="info" showIcon message="正在验证管理员邀请关系" />
      )}
      {channelStatus === "valid" && (
        <Alert type="success" showIcon message={`注册后将关联管理员：${channelName}`} />
      )}
      {channelStatus === "invalid" && (
        <Alert
          type="warning"
          showIcon
          message="邀请或推荐关系已失效"
          description="你仍可继续注册，账号将作为独立用户使用。"
        />
      )}
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
