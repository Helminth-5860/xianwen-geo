"use client";

import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { RiskActionButton } from "@/components/admin/risk-action-button";
import { userMessage } from "@/lib/auth-client";
import {
  changePlanState,
  copyPlan,
  createPlanVersion,
  getPlan,
  updatePlan,
  type Plan,
  type PlanVersion,
} from "@/lib/plans-client";
import { getRiskActions, type RiskMode } from "@/lib/risk-client";

function versionSnapshot(version: PlanVersion | null | undefined) {
  if (!version) return null;
  return {
    version_no: version.version_no,
    valid_days: version.valid_days,
    queue_priority: version.queue_priority,
    limits: Object.fromEntries(version.limits.map((item) => [item.key, item.value])),
    model_permissions: version.model_permissions.map((item) => ({
      model_key: item.model_key,
      sort_order: item.sort_order,
      selected_by_default: item.selected_by_default,
    })),
  };
}

export default function PlanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [modes, setModes] = useState<Record<string, RiskMode>>({});
  const [copyCode, setCopyCode] = useState("");
  const [copyName, setCopyName] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [priceMode, setPriceMode] = useState<"fixed" | "contact">("fixed");
  const [form] = Form.useForm();
  const load = useCallback(
    () =>
      getPlan(id)
        .then(setPlan)
        .catch((reason) => setError(userMessage(reason))),
    [id],
  );

  useEffect(() => {
    void load();
    void getRiskActions().then((items) =>
      setModes(Object.fromEntries(items.map((item) => [item.key, item.current_mode]))),
    );
  }, [load]);

  const versionDiff = useMemo(() => {
    if (!plan?.draft_version || !plan.current_published_version) return null;
    return {
      current: versionSnapshot(plan.current_published_version),
      draft: versionSnapshot(plan.draft_version),
    };
  }, [plan]);

  if (!plan) {
    return (
      <main className="admin-page">
        {error ? <Alert type="error" message={error} /> : "加载中…"}
      </main>
    );
  }

  return (
    <main className="admin-page">
      <Typography.Title>{plan.name}</Typography.Title>
      {message && <Alert type="success" message={message} />}
      {error && <Alert type="error" message={error} />}
      <Card>
        <Descriptions
          items={[
            { key: "code", label: "套餐编号", children: plan.code },
            {
              key: "status",
              label: "销售状态",
              children: {
                draft: "草稿",
                published: "销售中",
                offline: "已停售",
                archived: "已归档",
              }[plan.status],
            },
            {
              key: "price",
              label: "套餐价格",
              children: plan.price_display_mode === "fixed" ? `¥${plan.display_price}` : "联系开通",
            },
            {
              key: "recommended",
              label: "推荐展示",
              children: plan.is_recommended ? <Tag color="purple">推荐</Tag> : "普通",
            },
            {
              key: "version",
              label: "当前版本",
              children: plan.current_published_version
                ? `第 ${plan.current_published_version.version_no} 版`
                : "尚未发布",
            },
            {
              key: "subscriptions",
              label: "订阅客户",
              children: `${plan.current_subscription_count ?? 0} 位`,
            },
          ]}
        />
        {plan.status !== "archived" ? (
          <Button
            style={{ marginTop: 16 }}
            onClick={() => {
              form.setFieldsValue({
                name: plan.name,
                description: plan.description,
                price_display_mode: plan.price_display_mode,
                display_price: plan.display_price,
                is_trial: plan.is_trial,
                is_recommended: plan.is_recommended ?? false,
                sort_order: plan.sort_order,
              });
              setPriceMode(plan.price_display_mode);
              setEditing(true);
            }}
          >
            编辑套餐信息
          </Button>
        ) : null}
      </Card>

      <Modal
        open={editing}
        title="编辑套餐信息"
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        onCancel={() => setEditing(false)}
        onOk={() => form.submit()}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={async (values) => {
            setSaving(true);
            setError("");
            try {
              await updatePlan(plan.id, {
                ...values,
                expected_version: plan.version,
                display_price: values.price_display_mode === "fixed" ? values.display_price : null,
                confirmed: true,
              });
              setEditing(false);
              setMessage("套餐信息已保存");
              await load();
            } catch (reason) {
              setError(userMessage(reason));
            } finally {
              setSaving(false);
            }
          }}
        >
          <Form.Item name="name" label="套餐名称" rules={[{ required: true }]}>
            <Input maxLength={120} />
          </Form.Item>
          <Form.Item name="description" label="套餐说明">
            <Input.TextArea maxLength={500} rows={3} />
          </Form.Item>
          <Form.Item name="price_display_mode" label="价格展示方式">
            <Select
              onChange={setPriceMode}
              options={[
                { value: "fixed", label: "显示固定价格" },
                { value: "contact", label: "联系开通" },
              ]}
            />
          </Form.Item>
          {priceMode === "fixed" ? (
            <Form.Item name="display_price" label="套餐价格" rules={[{ required: true }]}>
              <Input inputMode="decimal" />
            </Form.Item>
          ) : null}
          <Form.Item name="sort_order" label="展示顺序">
            <InputNumber min={0} precision={0} />
          </Form.Item>
          <Form.Item name="is_trial" label="体验套餐" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_recommended" label="推荐套餐" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Card title="复制套餐">
        <Space wrap>
          <Input
            aria-label="新套餐编码"
            placeholder="新套餐编码"
            value={copyCode}
            onChange={(event) => setCopyCode(event.target.value)}
          />
          <Input
            aria-label="新套餐名称"
            placeholder="新套餐名称"
            value={copyName}
            onChange={(event) => setCopyName(event.target.value)}
          />
          <RiskActionButton
            actionName="复制套餐"
            mode={modes["plan.copy"] ?? "confirm"}
            disabled={!copyCode.trim() || !copyName.trim() || plan.status === "archived"}
            execute={(credentials) =>
              copyPlan(plan.id, {
                new_code: copyCode.trim(),
                new_name: copyName.trim(),
                source_version_id: plan.current_published_version_id,
                expected_source_plan_version: plan.version,
                ...credentials,
              })
            }
            onExecuted={(item) => router.push(`/admin/plans/${item.id}`)}
          >
            复制为新套餐
          </RiskActionButton>
        </Space>
      </Card>

      <Space wrap>
        {!plan.draft_version && plan.status !== "archived" && (
          <RiskActionButton
            actionName="创建套餐版本"
            mode={modes["plan.version.create"] ?? "confirm"}
            execute={(credentials) => createPlanVersion(plan.id, plan.version, credentials)}
            onExecuted={(item) => router.push(`/admin/plans/${plan.id}/versions/${item.id}`)}
          >
            创建草稿版本
          </RiskActionButton>
        )}
        {plan.draft_version && (
          <Link href={`/admin/plans/${plan.id}/versions/${plan.draft_version.id}`}>
            <Button>编辑草稿版本</Button>
          </Link>
        )}
        {(["online", "offline", "archive"] as const).map((action) => (
          <RiskActionButton
            key={action}
            actionName={{ online: "恢复销售", offline: "停止销售", archive: "归档套餐" }[action]}
            mode={modes[`plan.${action}`] ?? "password"}
            disabled={
              (action === "online" && plan.status !== "offline") ||
              (action === "offline" && plan.status !== "published") ||
              (action === "archive" && !["draft", "offline"].includes(plan.status))
            }
            execute={(credentials) => changePlanState(plan.id, action, plan.version, credentials)}
            onExecuted={() => {
              setMessage("状态已更新");
              void load();
            }}
          >
            {{ online: "恢复销售", offline: "停止销售", archive: "归档套餐" }[action]}
          </RiskActionButton>
        ))}
      </Space>

      {versionDiff && (
        <Card title="当前发布版本与草稿版本差异">
          <pre aria-label="版本差异">{JSON.stringify(versionDiff, null, 2)}</pre>
        </Card>
      )}
    </main>
  );
}
