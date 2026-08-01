"use client";

import { Button, Form, Input, Space } from "antd";

export function IpAllowlistStatusAction({
  active,
  onSubmit,
}: {
  active: boolean;
  onSubmit: (password: string) => Promise<void>;
}) {
  return (
    <Form<{ current_password: string }>
      layout="inline"
      onFinish={async ({ current_password }) => onSubmit(current_password)}
    >
      <Space.Compact>
        <Form.Item
          name="current_password"
          noStyle
          rules={[{ required: true, message: "请输入当前密码" }]}
        >
          <Input.Password autoComplete="current-password" placeholder="当前密码" />
        </Form.Item>
        <Button htmlType="submit">{active ? "停用" : "恢复"}</Button>
      </Space.Compact>
    </Form>
  );
}
