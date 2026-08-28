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
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  createAdminImageSize,
  createAdminImageStyle,
  getAdminImageSizes,
  getAdminImageStyles,
  getImageCapabilityRuntimes,
  getImageCredentialBindings,
  setImageCredentialBinding,
  updateAdminImageSize,
  updateAdminImageStyle,
  updateImageCapabilityRuntime,
  type AdminImageSize,
  type AdminImageStyle,
  type ImageCapabilityRuntime,
  type ImageCredentialBinding,
} from "@/lib/image-admin-client";

type PresetForm = {
  key: string;
  name: string;
  aspect_ratio: string;
  width: number;
  height: number;
  provider_size: string;
  description: string;
  prompt_template: string;
  status: "active" | "disabled";
  sort_order: number;
};

export default function AdminImagesPage() {
  const capabilities = useAdminCapabilities();
  const canManage = capabilities?.permission_keys.includes("models.manage") ?? false;
  const canBind = Boolean(capabilities?.is_superuser);
  const [sizes, setSizes] = useState<AdminImageSize[]>([]);
  const [styles, setStyles] = useState<AdminImageStyle[]>([]);
  const [runtime, setRuntime] = useState<ImageCapabilityRuntime>();
  const [bindings, setBindings] = useState<ImageCredentialBinding[]>([]);
  const [editingSize, setEditingSize] = useState<AdminImageSize>();
  const [editingStyle, setEditingStyle] = useState<AdminImageStyle>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sizeForm] = Form.useForm<PresetForm>();
  const [styleForm] = Form.useForm<PresetForm>();
  const [runtimeForm] = Form.useForm();

  const load = useCallback(async () => {
    try {
      const [sizeRows, styleRows, runtimeRows] = await Promise.all([
        getAdminImageSizes(),
        getAdminImageStyles(),
        getImageCapabilityRuntimes(),
      ]);
      setSizes(sizeRows);
      setStyles(styleRows);
      const imageRuntime = runtimeRows.find(
        (row) => row.provider_key === "doubao" && row.capability === "image_generation",
      );
      setRuntime(imageRuntime);
      if (imageRuntime) runtimeForm.setFieldsValue(imageRuntime);
      if (canBind) setBindings(await getImageCredentialBindings());
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [canBind, runtimeForm]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const run = async (operation: () => Promise<unknown>, message: string) => {
    try {
      setError("");
      await operation();
      setNotice(message);
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    }
  };

  const saveSize = async () => {
    const value = await sizeForm.validateFields();
    const input = {
      key: value.key,
      name: value.name,
      aspect_ratio: value.aspect_ratio,
      width: value.width,
      height: value.height,
      provider_params: { size: value.provider_size },
      applicable_channels: [],
      applicable_roles: [],
      status: value.status,
      sort_order: value.sort_order,
    };
    await run(
      () => (editingSize ? updateAdminImageSize(editingSize, input) : createAdminImageSize(input)),
      "尺寸预设已版本化保存",
    );
    setEditingSize(undefined);
    sizeForm.resetFields();
  };

  const saveStyle = async () => {
    const value = await styleForm.validateFields();
    const input = {
      key: value.key,
      name: value.name,
      description: value.description,
      prompt_template: value.prompt_template,
      applicable_roles: [],
      status: value.status,
      sort_order: value.sort_order,
    };
    await run(
      () =>
        editingStyle ? updateAdminImageStyle(editingStyle, input) : createAdminImageStyle(input),
      "风格预设已版本化保存",
    );
    setEditingStyle(undefined);
    styleForm.resetFields();
  };

  return (
    <main className="admin-page">
      <Typography.Title level={2}>图片能力、尺寸与风格后台</Typography.Title>
      <Alert
        type="info"
        showIcon
        title="图片 runtime 与 credential capability binding 独立于 GEO detection"
        description="生产 provider model 不硬编码；缺少已启用 runtime、显式 image_generation binding 或私有存储时 fail closed。"
      />
      {error && <Alert type="error" showIcon title={error} />}
      {notice && <Alert type="success" showIcon title={notice} />}
      <Card title="Doubao ImageGenerations runtime">
        <Form
          form={runtimeForm}
          layout="vertical"
          disabled={!canManage}
          onFinish={(values) =>
            runtime &&
            run(() => updateImageCapabilityRuntime(runtime, values), "图片 runtime 已更新")
          }
        >
          <Space wrap align="start">
            <Form.Item
              label="Provider model / endpoint id"
              name="provider_model_id"
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item label="API reference" name="api_version">
              <Input />
            </Form.Item>
            <Form.Item label="超时秒" name="timeout_seconds">
              <InputNumber min={1} max={600} />
            </Form.Item>
            <Form.Item label="最大重试" name="max_retries">
              <InputNumber min={0} max={10} />
            </Form.Item>
            <Form.Item label="重试基数秒" name="retry_base_seconds">
              <InputNumber min={1} max={3600} />
            </Form.Item>
            <Form.Item label="启用" name="enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Button htmlType="submit" type="primary">
              保存 runtime
            </Button>
          </Space>
        </Form>
        {canBind &&
          (["staging", "production"] as const).map((environment) => {
            const binding = bindings.find(
              (row) => row.environment === environment && row.capability === "image_generation",
            );
            return (
              <Space key={environment}>
                <Tag>{environment}</Tag>
                <Switch
                  aria-label={`${environment} 图片凭据绑定`}
                  checked={binding?.enabled ?? false}
                  onChange={(enabled) =>
                    void run(
                      () => setImageCredentialBinding(environment, enabled, binding),
                      `${environment} 图片凭据绑定已更新`,
                    )
                  }
                />
                <Typography.Text type="secondary">
                  必须先在密钥后台 provision 该环境的有效 Doubao Ark Key
                </Typography.Text>
              </Space>
            );
          })}
      </Card>
      <Card title="尺寸预设">
        <Table
          rowKey="id"
          dataSource={sizes}
          pagination={false}
          columns={[
            { title: "键", dataIndex: "key" },
            { title: "名称", dataIndex: "name" },
            { title: "比例", dataIndex: "aspect_ratio" },
            { title: "尺寸", render: (_, row) => `${row.width}×${row.height}` },
            { title: "状态", dataIndex: "status" },
            {
              title: "操作",
              render: (_, row) => (
                <Button
                  disabled={!canManage}
                  onClick={() => {
                    setEditingSize(row);
                    sizeForm.setFieldsValue({
                      ...row,
                      provider_size: String(row.provider_params.size ?? ""),
                    });
                  }}
                >
                  编辑
                </Button>
              ),
            },
          ]}
        />
        <Form
          form={sizeForm}
          layout="inline"
          initialValues={{ status: "active", sort_order: 0 }}
          onFinish={saveSize}
          disabled={!canManage}
        >
          <Form.Item name="key" rules={[{ required: true }]}>
            <Input placeholder="stable key" />
          </Form.Item>
          <Form.Item name="name" rules={[{ required: true }]}>
            <Input placeholder="名称" />
          </Form.Item>
          <Form.Item name="aspect_ratio" rules={[{ required: true }]}>
            <Input placeholder="16:9" />
          </Form.Item>
          <Form.Item name="width" rules={[{ required: true }]}>
            <InputNumber placeholder="宽" />
          </Form.Item>
          <Form.Item name="height" rules={[{ required: true }]}>
            <InputNumber placeholder="高" />
          </Form.Item>
          <Form.Item name="provider_size" rules={[{ required: true }]}>
            <Input placeholder="provider size" />
          </Form.Item>
          <Form.Item name="status">
            <Select options={[{ value: "active" }, { value: "disabled" }]} />
          </Form.Item>
          <Form.Item name="sort_order">
            <InputNumber min={0} />
          </Form.Item>
          <Button htmlType="submit">{editingSize ? "保存" : "新增"}</Button>
        </Form>
      </Card>
      <Card title="风格预设">
        <Table
          rowKey="id"
          dataSource={styles}
          pagination={false}
          columns={[
            { title: "键", dataIndex: "key" },
            { title: "名称", dataIndex: "name" },
            { title: "状态", dataIndex: "status" },
            {
              title: "操作",
              render: (_, row) => (
                <Button
                  disabled={!canManage}
                  onClick={() => {
                    setEditingStyle(row);
                    styleForm.setFieldsValue(row);
                  }}
                >
                  编辑
                </Button>
              ),
            },
          ]}
        />
        <Form
          form={styleForm}
          layout="vertical"
          initialValues={{ status: "active", sort_order: 0 }}
          onFinish={saveStyle}
          disabled={!canManage}
        >
          <Space wrap align="start">
            <Form.Item name="key" rules={[{ required: true }]}>
              <Input placeholder="stable key" />
            </Form.Item>
            <Form.Item name="name" rules={[{ required: true }]}>
              <Input placeholder="名称" />
            </Form.Item>
            <Form.Item name="description">
              <Input placeholder="说明" />
            </Form.Item>
            <Form.Item name="status">
              <Select options={[{ value: "active" }, { value: "disabled" }]} />
            </Form.Item>
            <Form.Item name="sort_order">
              <InputNumber min={0} />
            </Form.Item>
          </Space>
          <Form.Item
            name="prompt_template"
            rules={[{ required: true, message: "必须包含 {prompt}" }]}
          >
            <Input.TextArea rows={3} placeholder="自然专业风格。{prompt}" />
          </Form.Item>
          <Button htmlType="submit">{editingStyle ? "保存" : "新增"}</Button>
        </Form>
      </Card>
    </main>
  );
}
