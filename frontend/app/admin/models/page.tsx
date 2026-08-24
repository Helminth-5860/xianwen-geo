"use client";

import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { AdminPageHeader } from "@/components/admin/admin-page-header";
import {
  changeAIModelEnabled,
  getAIModels,
  pauseAIModel,
  type AIModelRuntimeConfig,
  type AIModelRuntimeConfigInput,
  unpauseAIModel,
  updateAIModelRuntimeConfig,
} from "@/lib/ai-model-config-client";
import {
  createAPICredential,
  getAPICredentials,
  rotateAPICredential,
  testAPICredential,
  type APICredential,
  type APICredentialEnvironment,
} from "@/lib/api-credential-client";
import { userMessage } from "@/lib/auth-client";

type ConfigForm = AIModelRuntimeConfigInput;
type PauseForm = { reason: string };
type CredentialForm = {
  provider_key: string;
  environment: APICredentialEnvironment;
  api_key: string;
};
type RotateCredentialForm = { api_key: string };

const numericCost = (value: string | null) => (value === null ? null : Number(value));

export default function AdminAIModelsPage() {
  const capabilities = useAdminCapabilities();
  const [rows, setRows] = useState<AIModelRuntimeConfig[]>([]);
  const [editing, setEditing] = useState<AIModelRuntimeConfig | null>(null);
  const [pausing, setPausing] = useState<AIModelRuntimeConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [configForm] = Form.useForm<ConfigForm>();
  const [pauseForm] = Form.useForm<PauseForm>();
  const [credentials, setCredentials] = useState<APICredential[]>([]);
  const [credentialOpen, setCredentialOpen] = useState(false);
  const [rotatingCredential, setRotatingCredential] = useState<APICredential | null>(null);
  const [credentialBusy, setCredentialBusy] = useState(false);
  const [credentialMessage, setCredentialMessage] = useState("");
  const [credentialError, setCredentialError] = useState("");
  const [credentialForm] = Form.useForm<CredentialForm>();
  const [rotateForm] = Form.useForm<RotateCredentialForm>();
  const canManage = capabilities?.permission_keys.includes("models.manage") ?? false;
  const canManageCredentials =
    Boolean(capabilities?.is_superuser) &&
    Boolean(capabilities?.permission_keys.includes("api_credentials.manage"));
  const costUnit = Form.useWatch("cost_unit", configForm);

  const load = useCallback(async () => {
    setError("");
    try {
      setRows(await getAIModels());
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, []);

  useEffect(() => {
    void getAIModels()
      .then(setRows)
      .catch((reason) => setError(userMessage(reason)));
  }, []);

  const loadCredentials = useCallback(async () => {
    if (!canManageCredentials) {
      setCredentials([]);
      return;
    }
    setCredentialError("");
    try {
      setCredentials(await getAPICredentials());
    } catch (reason) {
      setCredentialError(userMessage(reason));
    }
  }, [canManageCredentials]);

  useEffect(() => {
    if (!canManageCredentials) return;

    void getAPICredentials()
      .then(setCredentials)
      .catch((reason) => setCredentialError(userMessage(reason)));
  }, [canManageCredentials]);

  const run = async (operation: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await operation();
      setMessage(success);
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const beginEdit = (row: AIModelRuntimeConfig) => {
    setEditing(row);
    configForm.setFieldsValue({
      display_name_override: row.display_name_override,
      provider_model_id: row.provider_model_id,
      api_version: row.api_version,
      sort_order: row.sort_order,
      network_access_enabled: row.network_access_enabled,
      web_search_failure_policy: row.web_search_failure_policy,
      timeout_seconds: row.timeout_seconds,
      max_retries: row.max_retries,
      retry_base_seconds: row.retry_base_seconds,
      retry_backoff: row.retry_backoff,
      max_concurrency: row.max_concurrency,
      cost_unit: row.cost_unit,
      currency: "CNY",
      input_cost: numericCost(row.input_cost),
      output_cost: numericCost(row.output_cost),
      request_cost: numericCost(row.request_cost),
    });
  };

  const save = async () => {
    if (!editing) return;
    const values = await configForm.validateFields();
    const input = {
      ...values,
      input_cost: values.cost_unit === "per_million_tokens" ? values.input_cost : null,
      output_cost: values.cost_unit === "per_million_tokens" ? values.output_cost : null,
      request_cost: values.cost_unit === "per_request" ? values.request_cost : null,
    };
    await run(() => updateAIModelRuntimeConfig(editing, input), "模型运行配置已保存");
    setEditing(null);
  };

  const submitPause = async () => {
    if (!pausing) return;
    const values = await pauseForm.validateFields();
    await run(() => pauseAIModel(pausing, values.reason), "模型已暂停");
    setPausing(null);
    pauseForm.resetFields();
  };

  const runCredentialOperation = async (operation: () => Promise<unknown>, success: string) => {
    setCredentialBusy(true);
    setCredentialError("");
    setCredentialMessage("");
    try {
      await operation();
      setCredentialMessage(success);
      await loadCredentials();
    } catch (reason) {
      setCredentialError(userMessage(reason));
      throw reason;
    } finally {
      setCredentialBusy(false);
    }
  };

  const submitCredential = async () => {
    const values = await credentialForm.validateFields();
    try {
      await runCredentialOperation(
        () => createAPICredential(values),
        "API 密钥已加密保存；明文不会再次显示",
      );
      credentialForm.resetFields();
      setCredentialOpen(false);
    } catch {
      // Keep the modal open so the superuser can correct the input.
    }
  };

  const submitRotation = async () => {
    if (!rotatingCredential) return;
    const values = await rotateForm.validateFields();
    try {
      await runCredentialOperation(
        () => rotateAPICredential(rotatingCredential, values.api_key),
        "API 密钥已轮换，旧版本密文已擦除",
      );
      rotateForm.resetFields();
      setRotatingCredential(null);
    } catch {
      // Keep the modal open so the superuser can retry safely.
    }
  };

  const runStorageTest = async (credential: APICredential) => {
    setCredentialBusy(true);
    try {
      const result = await testAPICredential(credential);
      setCredentialMessage(
        result.storage_valid && !result.remote_validated
          ? "本地加密存储测试通过；未执行真实 Provider 网络验证"
          : "密钥存储测试完成",
      );
      setCredentialError("");
      await loadCredentials();
    } catch (reason) {
      setCredentialMessage("");
      setCredentialError(userMessage(reason));
    } finally {
      setCredentialBusy(false);
    }
  };

  const providerOptions = Array.from(new Set(rows.map((row) => row.provider_key))).map((value) => ({
    value,
    label: value,
  }));

  const credentialColumns = [
    { title: "接口服务商", dataIndex: "provider_name" },
    {
      title: "环境",
      render: (_: unknown, row: APICredential) => (
        <Tag color={row.environment === "production" ? "red" : "blue"}>
          {row.environment === "production" ? "正式环境" : "测试环境"}
        </Tag>
      ),
    },
    { title: "密钥标识", dataIndex: "secret_mask" },
    { title: "版本", dataIndex: "version_no" },
    {
      title: "状态",
      render: (_: unknown, row: APICredential) => (
        <Tag color={row.status === "active" ? "green" : "default"}>
          {row.status === "active" ? "正常" : "已停用"}
        </Tag>
      ),
    },
    {
      title: "操作",
      render: (_: unknown, row: APICredential) => (
        <Space>
          <Button
            disabled={!canManageCredentials || credentialBusy}
            onClick={() => {
              rotateForm.resetFields();
              setRotatingCredential(row);
            }}
          >
            轮换
          </Button>
          <Button
            disabled={!canManageCredentials || credentialBusy}
            onClick={() => void runStorageTest(row)}
          >
            测试连接
          </Button>
        </Space>
      ),
    },
  ];

  const columns = [
    { title: "模型名称", dataIndex: "display_name" },
    { title: "接口服务商", dataIndex: "provider_key" },
    {
      title: "状态",
      render: (_: unknown, row: AIModelRuntimeConfig) => (
        <Space>
          <Tag color={row.enabled ? "green" : "default"}>{row.enabled ? "启用" : "停用"}</Tag>
          {row.paused && <Tag color="orange">已暂停</Tag>}
        </Space>
      ),
    },
    {
      title: "调用设置",
      render: (_: unknown, row: AIModelRuntimeConfig) =>
        `${row.timeout_seconds}s / 重试 ${row.max_retries} / 并发 ${row.max_concurrency}`,
    },
    {
      title: "网络访问",
      render: (_: unknown, row: AIModelRuntimeConfig) =>
        row.network_access_enabled ? "允许" : "关闭",
    },
    {
      title: "操作",
      render: (_: unknown, row: AIModelRuntimeConfig) => (
        <Space wrap>
          <Button disabled={!canManage} onClick={() => beginEdit(row)}>
            编辑
          </Button>
          <Button
            disabled={!canManage}
            onClick={() =>
              void run(
                () => changeAIModelEnabled(row, row.enabled ? "disable" : "enable"),
                row.enabled ? "模型已停用" : "模型已启用",
              )
            }
          >
            {row.enabled ? "停用" : "启用"}
          </Button>
          <Button
            disabled={!canManage}
            onClick={() =>
              row.paused
                ? void run(() => unpauseAIModel(row), "模型已恢复")
                : (setPausing(row), pauseForm.resetFields())
            }
          >
            {row.paused ? "恢复" : "暂停"}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <main className="admin-page">
      <AdminPageHeader
        title="模型与接口"
        description="查看模型运行状态、配置调用参数、维护接口凭据并测试连接。停用或暂停后，新任务将不再使用该模型。"
      />
      {!canManage && <Alert type="info" showIcon title="当前账号只有查看权限" />}
      {message && <Alert type="success" showIcon title={message} />}
      {error && <Alert type="error" showIcon title={error} />}
      <Card className="admin-surface">
        <Table rowKey="model_id" dataSource={rows} columns={columns} pagination={false} />
      </Card>

      {canManageCredentials && (
        <Card
          title="接口凭据"
          extra={
            <Button
              type="primary"
              onClick={() => {
                credentialForm.resetFields();
                setCredentialOpen(true);
              }}
            >
              新增接口凭据
            </Button>
          }
        >
          <Alert
            type="warning"
            showIcon
            title="保存后仅显示部分内容"
            description="接口密钥会加密保存；测试连接只返回安全结果，不展示完整密钥。"
          />
          {credentialMessage && (
            <Alert type="success" showIcon title={credentialMessage} style={{ marginTop: 12 }} />
          )}
          {credentialError && (
            <Alert type="error" showIcon title={credentialError} style={{ marginTop: 12 }} />
          )}
          <Table
            style={{ marginTop: 16 }}
            rowKey="id"
            dataSource={credentials}
            columns={credentialColumns}
            pagination={false}
          />
        </Card>
      )}

      <Modal
        title={`编辑 ${editing?.display_name ?? "模型"}`}
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={() => void save()}
        confirmLoading={busy}
        okText="保存"
        width={760}
      >
        <Form form={configForm} layout="vertical">
          <Space wrap align="start">
            <Form.Item label="显示名称" name="display_name_override">
              <Input placeholder="留空使用内置名称" />
            </Form.Item>
            <Form.Item label="接口模型标识" name="provider_model_id">
              <Input />
            </Form.Item>
            <Form.Item label="接口版本" name="api_version">
              <Input />
            </Form.Item>
            <Form.Item label="排序" name="sort_order" rules={[{ required: true }]}>
              <InputNumber min={0} max={65535} />
            </Form.Item>
            <Form.Item label="允许联网" name="network_access_enabled" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label="联网失败策略" name="web_search_failure_policy">
              <Select
                style={{ width: 230 }}
                options={[
                  { value: "degrade_formal", label: "降级并参与正式评分" },
                  { value: "degrade_reference", label: "降级仅作参考" },
                  { value: "fail", label: "直接失败" },
                ]}
              />
            </Form.Item>
            <Form.Item label="超时（秒）" name="timeout_seconds" rules={[{ required: true }]}>
              <InputNumber min={1} max={300} />
            </Form.Item>
            <Form.Item label="最大重试" name="max_retries" rules={[{ required: true }]}>
              <InputNumber min={0} max={10} />
            </Form.Item>
            <Form.Item
              label="重试基数（秒）"
              name="retry_base_seconds"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={3600} />
            </Form.Item>
            <Form.Item label="退避策略" name="retry_backoff">
              <Select
                style={{ width: 150 }}
                options={[
                  { value: "fixed", label: "固定" },
                  { value: "exponential", label: "指数" },
                ]}
              />
            </Form.Item>
            <Form.Item label="最大并发" name="max_concurrency" rules={[{ required: true }]}>
              <InputNumber min={1} max={1000} />
            </Form.Item>
            <Form.Item label="成本单位" name="cost_unit">
              <Select
                allowClear
                style={{ width: 180 }}
                options={[
                  { value: "per_million_tokens", label: "每百万 Token" },
                  { value: "per_request", label: "每次请求" },
                ]}
              />
            </Form.Item>
            <Form.Item label="币种" name="currency">
              <Input disabled />
            </Form.Item>
            {costUnit === "per_million_tokens" && (
              <>
                <Form.Item label="输入成本" name="input_cost" rules={[{ required: true }]}>
                  <InputNumber min={0} precision={6} />
                </Form.Item>
                <Form.Item label="输出成本" name="output_cost" rules={[{ required: true }]}>
                  <InputNumber min={0} precision={6} />
                </Form.Item>
              </>
            )}
            {costUnit === "per_request" && (
              <Form.Item label="单次请求成本" name="request_cost" rules={[{ required: true }]}>
                <InputNumber min={0} precision={6} />
              </Form.Item>
            )}
          </Space>
        </Form>
      </Modal>

      <Modal
        title={`暂停 ${pausing?.display_name ?? "模型"}`}
        open={pausing !== null}
        onCancel={() => setPausing(null)}
        onOk={() => void submitPause()}
        confirmLoading={busy}
        okText="确认暂停"
      >
        <Form form={pauseForm} layout="vertical">
          <Form.Item label="暂停原因" name="reason" rules={[{ required: true }]}>
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="新增接口凭据"
        open={credentialOpen}
        onCancel={() => {
          credentialForm.resetFields();
          setCredentialOpen(false);
        }}
        onOk={() => void submitCredential()}
        confirmLoading={credentialBusy}
        okText="加密保存"
      >
        <Form form={credentialForm} layout="vertical">
          <Form.Item label="接口服务商" name="provider_key" rules={[{ required: true }]}>
            <Select options={providerOptions} placeholder="选择接口服务商" />
          </Form.Item>
          <Form.Item
            label="环境"
            name="environment"
            rules={[{ required: true }]}
            initialValue="staging"
          >
            <Select
              options={[
                { value: "staging", label: "Staging" },
                { value: "production", label: "Production" },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="接口密钥"
            name="api_key"
            rules={[{ required: true, min: 8, max: 4096 }]}
          >
            <Input.Password
              autoComplete="new-password"
              placeholder="保存后只显示掩码，不可再次查看明文"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`更新 ${rotatingCredential?.provider_name ?? ""} 接口密钥`}
        open={rotatingCredential !== null}
        onCancel={() => {
          rotateForm.resetFields();
          setRotatingCredential(null);
        }}
        onOk={() => void submitRotation()}
        confirmLoading={credentialBusy}
        okText="确认轮换"
      >
        <Alert
          type="warning"
          showIcon
          title="轮换会创建新版本，并擦除旧版本密文"
          style={{ marginBottom: 12 }}
        />
        <Form form={rotateForm} layout="vertical">
          <Form.Item
            label="新接口密钥"
            name="api_key"
            rules={[{ required: true, min: 8, max: 4096 }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
