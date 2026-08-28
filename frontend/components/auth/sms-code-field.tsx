"use client";

import { Button, Form, Input, Space, type FormInstance } from "antd";

import { userMessage } from "@/lib/auth-client";
import { validatePhone } from "@/lib/auth-validation";

export function SmsCodeField({
  form,
  send,
  sending,
  remaining,
  onError,
}: Readonly<{
  form: FormInstance;
  send(phone: string): Promise<void>;
  sending: boolean;
  remaining: number;
  onError(message: string): void;
}>) {
  const handleSend = async () => {
    try {
      await form.validateFields(["phone"]);
      await send(String(form.getFieldValue("phone") || ""));
    } catch (error) {
      if (error instanceof Error && error.message) onError(userMessage(error));
    }
  };

  return (
    <Form.Item label="短信验证码" required>
      <Space.Compact block>
        <Form.Item
          name="smsCode"
          noStyle
          rules={[
            { required: true, message: "请输入短信验证码" },
            { pattern: /^\d{6}$/, message: "请输入 6 位数字验证码" },
          ]}
        >
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            aria-label="短信验证码"
          />
        </Form.Item>
        <Button
          onClick={handleSend}
          loading={sending}
          disabled={sending || remaining > 0}
          aria-label={remaining > 0 ? `${remaining} 秒后重新发送` : "发送短信验证码"}
        >
          {remaining > 0 ? `${remaining} 秒` : "发送验证码"}
        </Button>
      </Space.Compact>
    </Form.Item>
  );
}

export const phoneRules = [
  { required: true, message: "请输入手机号" },
  { validator: (_: unknown, value: string) => validatePhone(value || "") },
];
