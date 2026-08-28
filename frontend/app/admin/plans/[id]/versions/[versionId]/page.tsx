"use client";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Typography,
} from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { RiskActionButton } from "@/components/admin/risk-action-button";
import { userMessage } from "@/lib/auth-client";
import {
  getLimitDefinitions,
  getPlanVersion,
  publishPlanVersion,
  retirePlanVersion,
  updatePlanVersion,
  type LimitDefinition,
  type ModelKey,
  type PlanVersion,
} from "@/lib/plans-client";
import { getRiskActions, type RiskMode } from "@/lib/risk-client";
const MODELS: ModelKey[] = [
  "deepseek",
  "doubao",
  "qwen",
  "hunyuan",
  "wenxin",
  "kimi",
  "glm",
  "spark",
];
export default function PlanVersionPage() {
  const { versionId } = useParams<{ id: string; versionId: string }>();
  const [version, setVersion] = useState<PlanVersion | null>(null);
  const [definitions, setDefinitions] = useState<LimitDefinition[]>([]);
  const [modes, setModes] = useState<Record<string, RiskMode>>({});
  const [error, setError] = useState("");
  const [form] = Form.useForm();
  const load = useCallback(
    () =>
      getPlanVersion(versionId)
        .then((item) => {
          setVersion(item);
          form.setFieldsValue({
            valid_days: item.valid_days,
            queue_priority: item.queue_priority,
            limits: Object.fromEntries(
              item.limits.map((limit) => [
                limit.key,
                limit.value_type === "json" ? JSON.stringify(limit.value, null, 2) : limit.value,
              ]),
            ),
            models: item.model_permissions
              .filter((model) => model.selected_by_default)
              .map((model) => model.model_key),
          });
        })
        .catch((reason) => setError(userMessage(reason))),
    [form, versionId],
  );
  useEffect(() => {
    void load();
    void getLimitDefinitions().then(setDefinitions);
    void getRiskActions().then((items) =>
      setModes(Object.fromEntries(items.map((item) => [item.key, item.current_mode]))),
    );
  }, [load]);
  if (!version) return <main className="admin-page">加载中…</main>;
  return (
    <main className="admin-page">
      <Typography.Title>版本 V{version.version_no}</Typography.Title>
      {error && <Alert type="error" message={error} />}
      <Alert
        type={version.supports_formal_composite ? "success" : "warning"}
        message={
          version.supports_formal_composite
            ? "支持正式综合分"
            : "无法形成正式综合分，发布时必须显式确认"
        }
      />
      <Card>
        <Form
          form={form}
          layout="vertical"
          disabled={version.status !== "draft"}
          onFinish={async (values) => {
            try {
              const limits = definitions
                .filter((item) => item.storage_kind === "plan_limit" && item.status === "active")
                .map((item) => {
                  const rawValue = values.limits[item.key];
                  return {
                    key: item.key,
                    value:
                      item.value_type === "json" && typeof rawValue === "string"
                        ? JSON.parse(rawValue)
                        : rawValue,
                  };
                });
              const selected = new Set<ModelKey>(values.models);
              const model_permissions = MODELS.map((key, index) => ({
                model_key: key,
                sort_order: index,
                selected_by_default: selected.has(key),
              }));
              await updatePlanVersion(version.id, {
                expected_version: version.version,
                valid_days: values.valid_days,
                queue_priority: values.queue_priority,
                limits,
                model_permissions,
                confirmed: true,
              });
              await load();
            } catch (reason) {
              setError(userMessage(reason));
            }
          }}
        >
          <Form.Item name="valid_days" label="有效天数" rules={[{ required: true }]}>
            <InputNumber min={1} max={3650} />
          </Form.Item>
          <Form.Item name="queue_priority" label="队列优先级">
            <InputNumber min={0} max={1000} />
          </Form.Item>
          {definitions
            .filter((item) => item.storage_kind === "plan_limit" && item.status === "active")
            .map((item) => (
              <Form.Item
                key={item.key}
                name={["limits", item.key]}
                label={item.name + " (" + item.key + ")"}
                extra={item.description}
                rules={[{ required: item.required }]}
                valuePropName={item.value_type === "boolean" ? "checked" : "value"}
              >
                {item.value_type === "boolean" ? (
                  <Switch />
                ) : item.value_type === "integer" ? (
                  <InputNumber min={item.minimum ?? undefined} max={item.maximum ?? undefined} />
                ) : item.value_type === "enum" ? (
                  <Select
                    options={item.enum_values.map((value) => ({ value, label: value }))}
                    allowClear={!item.required}
                  />
                ) : item.value_type === "json" ? (
                  <Input.TextArea rows={5} aria-label={item.name + " JSON"} />
                ) : (
                  <Input />
                )}
              </Form.Item>
            ))}
          <Form.Item name="models" label="默认模型组合" rules={[{ required: true }]}>
            <Checkbox.Group options={MODELS.map((key) => ({ value: key, label: key }))} />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            保存草稿
          </Button>
        </Form>
      </Card>
      <Space>
        <RiskActionButton
          actionName="发布套餐版本"
          mode={modes["plan.version.publish"] ?? "password"}
          disabled={version.status !== "draft"}
          execute={(credentials) =>
            publishPlanVersion(
              version.id,
              version.version,
              !version.supports_formal_composite,
              credentials,
            )
          }
          onExecuted={() => void load()}
        >
          发布
        </RiskActionButton>
        <RiskActionButton
          actionName="退役套餐版本"
          mode={modes["plan.version.retire"] ?? "password"}
          disabled={version.status === "retired"}
          execute={(credentials) => retirePlanVersion(version.id, version.version, credentials)}
          onExecuted={() => void load()}
        >
          退役
        </RiskActionButton>
      </Space>
      {version.status !== "draft" && (
        <Card title="不可变快照预览">
          <pre>
            {JSON.stringify(
              {
                valid_days: version.valid_days,
                queue_priority: version.queue_priority,
                limits: version.limits,
                model_permissions: version.model_permissions,
              },
              null,
              2,
            )}
          </pre>
        </Card>
      )}
    </main>
  );
}
