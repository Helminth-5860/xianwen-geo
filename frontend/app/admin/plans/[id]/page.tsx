"use client";

import { Alert, Button, Card, Descriptions, Input, Space, Typography } from "antd";
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

  const approval = (item: { approval_id: string }) =>
    router.push(`/admin/approvals/${item.approval_id}`);

  return (
    <main className="admin-page">
      <Typography.Title>{plan.name}</Typography.Title>
      {message && <Alert type="success" message={message} />}
      {error && <Alert type="error" message={error} />}
      <Card>
        <Descriptions
          items={[
            { key: "code", label: "编码", children: plan.code },
            { key: "status", label: "状态", children: plan.status },
            {
              key: "price",
              label: "展示价格",
              children: plan.price_display_mode === "fixed" ? `¥${plan.display_price}` : "联系开通",
            },
            { key: "version", label: "乐观版本", children: plan.version },
          ]}
        />
      </Card>

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
            onApproval={approval}
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
            onApproval={approval}
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
            actionName={action}
            mode={modes[`plan.${action}`] ?? (action === "archive" ? "two_person" : "password")}
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
            onApproval={approval}
          >
            {action}
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
