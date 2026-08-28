"use client";

import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import { createSubjectType, getAdminSubjectTypes, type SubjectType } from "@/lib/subjects-client";

type CreateValues = {
  key: string;
  name: string;
  description?: string;
  icon_key?: string;
  sort_order?: number;
};

export default function AdminSubjectTypesPage() {
  const capabilities = useAdminCapabilities();
  const [types, setTypes] = useState<SubjectType[]>([]);
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<CreateValues>();
  const canCreate = capabilities?.permission_keys.includes("subject_types.create") ?? false;

  const load = useCallback(
    () =>
      getAdminSubjectTypes(status, keyword)
        .then(setTypes)
        .catch((reason) => setError(userMessage(reason))),
    [keyword, status],
  );

  useEffect(() => {
    void getAdminSubjectTypes()
      .then(setTypes)
      .catch((reason) => setError(userMessage(reason)));
  }, []);

  const submit = async (values: CreateValues) => {
    setCreating(true);
    setError("");
    try {
      await createSubjectType({
        key: values.key,
        name: values.name,
        description: values.description ?? "",
        icon_key: values.icon_key ?? "subject",
        sort_order: values.sort_order ?? 0,
      });
      form.resetFields();
      setMessage("主体类型已创建，公共字段已自动配置");
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setCreating(false);
    }
  };

  return (
    <main className="admin-page">
      <Typography.Title>主体类型与动态字段</Typography.Title>
      <Typography.Paragraph>
        字段键和字段类型创建后不可修改；配置错误时请停用旧字段并创建新 key。
      </Typography.Paragraph>
      {message && <Alert type="success" showIcon message={message} />}
      {error && <Alert type="error" showIcon message={error} />}
      <Card title="筛选">
        <Space wrap>
          <Input
            aria-label="主体类型关键字"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <Select
            aria-label="主体类型状态"
            value={status}
            onChange={setStatus}
            style={{ width: 140 }}
            options={[
              { value: "", label: "全部" },
              { value: "active", label: "启用" },
              { value: "inactive", label: "停用" },
            ]}
          />
          <Button onClick={() => void load()}>筛选</Button>
        </Space>
      </Card>
      <Card title="创建主体类型">
        {!canCreate && <Alert type="info" message="当前账号没有创建主体类型权限" />}
        <Form form={form} layout="vertical" onFinish={(values) => void submit(values)}>
          <Space wrap align="start">
            <Form.Item label="稳定类型 key" name="key" rules={[{ required: true }]}>
              <Input disabled={!canCreate} />
            </Form.Item>
            <Form.Item label="类型名称" name="name" rules={[{ required: true }]}>
              <Input disabled={!canCreate} />
            </Form.Item>
            <Form.Item label="纯文本说明" name="description">
              <Input disabled={!canCreate} />
            </Form.Item>
            <Form.Item label="图标 key" name="icon_key" initialValue="subject">
              <Input disabled={!canCreate} />
            </Form.Item>
            <Form.Item label="排序" name="sort_order" initialValue={0}>
              <InputNumber min={0} disabled={!canCreate} />
            </Form.Item>
            <Form.Item label=" ">
              <Button type="primary" htmlType="submit" loading={creating} disabled={!canCreate}>
                创建并配置公共字段
              </Button>
            </Form.Item>
          </Space>
        </Form>
      </Card>
      <Table
        rowKey="id"
        dataSource={types}
        pagination={false}
        columns={[
          { title: "key", dataIndex: "key" },
          { title: "名称", dataIndex: "name" },
          {
            title: "状态",
            render: (_, row) => (
              <Tag color={row.status === "active" ? "green" : "default"}>
                {row.status === "active" ? "启用" : "停用"}
              </Tag>
            ),
          },
          { title: "Schema 版本", dataIndex: "schema_version" },
          {
            title: "操作",
            render: (_, row) => <Link href={`/admin/subject-types/${row.id}`}>配置字段</Link>,
          },
        ]}
      />
    </main>
  );
}
