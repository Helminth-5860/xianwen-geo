"use client";
import { Alert, Button, Form, Input, InputNumber, Select, Switch, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { userMessage } from "@/lib/auth-client";
import { createPlan } from "@/lib/plans-client";

type Values = {
  code: string;
  name: string;
  description: string;
  price_display_mode: "fixed" | "contact";
  display_price?: string;
  is_trial: boolean;
  sort_order: number;
};
export default function NewPlanPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"fixed" | "contact">("fixed");
  return (
    <main className="admin-page">
      <Typography.Title>创建套餐</Typography.Title>
      {error && <Alert type="error" message={error} />}
      <Form<Values>
        layout="vertical"
        initialValues={{ price_display_mode: "fixed", is_trial: false, sort_order: 0 }}
        onFinish={async (values) => {
          try {
            const result = await createPlan({
              ...values,
              display_price: values.price_display_mode === "fixed" ? values.display_price : null,
              confirmed: true,
            });
            router.push(`/admin/plans/${result.id}`);
          } catch (reason) {
            setError(userMessage(reason));
          }
        }}
      >
        <Form.Item
          name="code"
          label="稳定编码"
          rules={[
            { required: true },
            { pattern: /^[a-z][a-z0-9_-]{1,63}$/, message: "请输入小写 ASCII 稳定编码" },
          ]}
        >
          <Input />
        </Form.Item>
        <Form.Item name="name" label="套餐名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="description" label="展示说明">
          <Input.TextArea />
        </Form.Item>
        <Form.Item name="price_display_mode" label="展示价格模式">
          <Select
            onChange={setMode}
            options={[
              { value: "fixed", label: "固定展示价格" },
              { value: "contact", label: "联系开通" },
            ]}
          />
        </Form.Item>
        {mode === "fixed" && (
          <Form.Item
            name="display_price"
            label="展示价格（CNY）"
            rules={[{ required: true }, { pattern: /^\d+(\.\d{1,2})?$/, message: "最多两位小数" }]}
          >
            <Input inputMode="decimal" />
          </Form.Item>
        )}
        <Form.Item name="sort_order" label="排序">
          <InputNumber min={0} />
        </Form.Item>
        <Form.Item name="is_trial" label="试用展示" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Alert type="info" message="展示价格不是交易价格；本任务不会创建订单或收款。" />
        <Button type="primary" htmlType="submit">
          确认创建
        </Button>
      </Form>
    </main>
  );
}
