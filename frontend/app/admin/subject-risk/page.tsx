"use client";

import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  createSubjectRiskRule,
  createSubjectRiskType,
  getSubjectRiskCatalog,
  getSubjectRiskRules,
  getSubjectRiskTypes,
  publishSubjectRiskCatalog,
  type SubjectRiskCatalog,
  type SubjectRiskRule,
  type SubjectRiskType,
  updateSubjectRiskRule,
  updateSubjectRiskType,
} from "@/lib/subject-risk-client";

type TypeValues = { key: string; name: string; description?: string };
type RuleValues = {
  key: string;
  risk_type: string;
  field_key?: string;
  operator: "equals_any" | "contains_any";
  pattern: string;
  reason_type: SubjectRiskRule["reason_type"];
};

export default function SubjectRiskCatalogPage() {
  const router = useRouter();
  const capabilities = useAdminCapabilities();
  const [catalog, setCatalog] = useState<SubjectRiskCatalog | null>(null);
  const [types, setTypes] = useState<SubjectRiskType[]>([]);
  const [rules, setRules] = useState<SubjectRiskRule[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [typeForm] = Form.useForm<TypeValues>();
  const [ruleForm] = Form.useForm<RuleValues>();
  const canUpdate = capabilities?.permission_keys.includes("subject_risk.catalog.update") ?? false;
  const canPublish =
    capabilities?.permission_keys.includes("subject_risk.catalog.publish") ?? false;

  const load = useCallback(async () => {
    const [catalogData, typeData, ruleData] = await Promise.all([
      getSubjectRiskCatalog(),
      getSubjectRiskTypes(),
      getSubjectRiskRules(),
    ]);
    setCatalog(catalogData);
    setTypes(typeData.risk_types);
    setRules(ruleData.rules);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(
      () => void load().catch((reason) => setError(userMessage(reason))),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [load]);

  const createType = async (values: TypeValues) => {
    if (!catalog) return;
    setBusy(true);
    setError("");
    try {
      await createSubjectRiskType(catalog.version, {
        key: values.key,
        name: values.name,
        description: values.description ?? "",
        enabled: false,
        manual_review_required: true,
        allow_geo_detection: false,
        allow_article_generation: false,
        allow_image_generation: false,
        require_authoritative_citations: true,
        require_disclaimer: true,
        sort_order: 0,
      });
      typeForm.resetFields();
      setMessage("\u98ce\u9669\u7c7b\u578b\u8349\u7a3f\u5df2\u521b\u5efa");
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const createRule = async (values: RuleValues) => {
    if (!catalog) return;
    setBusy(true);
    setError("");
    try {
      await createSubjectRiskRule(catalog.version, {
        key: values.key,
        risk_type: values.risk_type,
        subject_type: null,
        field_key: values.field_key ?? "",
        operator: values.operator,
        patterns: [values.pattern],
        reason_type: values.reason_type,
        enabled: false,
        priority: 0,
      });
      ruleForm.resetFields();
      setMessage("\u98ce\u9669\u89c4\u5219\u8349\u7a3f\u5df2\u521b\u5efa");
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const toggleType = async (item: SubjectRiskType, enabled: boolean) => {
    if (!catalog) return;
    setBusy(true);
    try {
      await updateSubjectRiskType(item, catalog.version, { enabled });
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const toggleRule = async (item: SubjectRiskRule, enabled: boolean) => {
    if (!catalog) return;
    setBusy(true);
    try {
      await updateSubjectRiskRule(item, catalog.version, { enabled });
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    if (!catalog) return;
    setBusy(true);
    setError("");
    try {
      const result = await publishSubjectRiskCatalog(catalog.version);
      router.push(`/admin/approvals/${result.approval_id}`);
    } catch (reason) {
      setError(userMessage(reason));
      setBusy(false);
    }
  };

  return (
    <main className="admin-page">
      <Typography.Title>{"\u4e3b\u4f53\u98ce\u9669\u76ee\u5f55"}</Typography.Title>
      <Typography.Paragraph>
        {
          "\u7c7b\u578b\u4e0e\u89c4\u5219\u90fd\u662f\u8349\u7a3f\uff1b\u53ea\u6709\u53d1\u5e03\u5b8c\u6210\u53cc\u4eba\u5ba1\u6279\u540e\u624d\u4f1a\u751f\u6548\u3002"
        }
      </Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} />}
      {message && <Alert type="success" showIcon message={message} />}
      <Card title={"\u53d1\u5e03\u72b6\u6001"}>
        <Space>
          <Tag>{`draft v${catalog?.version ?? "-"}`}</Tag>
          <Tag color={catalog?.published_revision ? "green" : "warning"}>
            {catalog?.published_revision
              ? `published r${catalog.published_revision.revision_no}`
              : "\u5c1a\u672a\u53d1\u5e03"}
          </Tag>
          <Button
            type="primary"
            disabled={!canPublish || !catalog}
            loading={busy}
            onClick={() => void publish()}
          >
            {"\u53d1\u8d77\u53cc\u4eba\u53d1\u5e03\u5ba1\u6279"}
          </Button>
        </Space>
        {!canPublish && (
          <Alert type="info" message={"\u5f53\u524d\u8d26\u53f7\u65e0\u53d1\u5e03\u6743\u9650"} />
        )}
      </Card>
      <Card title={"\u65b0\u5efa\u98ce\u9669\u7c7b\u578b\u8349\u7a3f"}>
        <Form form={typeForm} layout="inline" onFinish={(values) => void createType(values)}>
          <Form.Item name="key" rules={[{ required: true }]}>
            <Input placeholder="machine.key" disabled={!canUpdate} />
          </Form.Item>
          <Form.Item name="name" rules={[{ required: true }]}>
            <Input placeholder={"\u540d\u79f0"} disabled={!canUpdate} />
          </Form.Item>
          <Form.Item name="description">
            <Input placeholder={"\u7eaf\u6587\u672c\u8bf4\u660e"} disabled={!canUpdate} />
          </Form.Item>
          <Button htmlType="submit" disabled={!canUpdate} loading={busy}>
            {"\u521b\u5efa"}
          </Button>
        </Form>
      </Card>
      <Table
        rowKey="id"
        dataSource={types}
        pagination={false}
        columns={[
          { title: "key", dataIndex: "key" },
          { title: "\u540d\u79f0", dataIndex: "name" },
          { title: "\u7248\u672c", dataIndex: "version" },
          {
            title: "\u8349\u7a3f\u542f\u7528",
            render: (_, item) => (
              <Switch
                checked={item.enabled}
                disabled={!canUpdate || busy}
                onChange={(checked) => void toggleType(item, checked)}
              />
            ),
          },
        ]}
      />
      <Card title={"\u65b0\u5efa\u98ce\u9669\u89c4\u5219\u8349\u7a3f"}>
        <Form form={ruleForm} layout="inline" onFinish={(values) => void createRule(values)}>
          <Form.Item name="key" rules={[{ required: true }]}>
            <Input placeholder="rule.key" disabled={!canUpdate} />
          </Form.Item>
          <Form.Item name="risk_type" rules={[{ required: true }]}>
            <Select
              style={{ width: 180 }}
              disabled={!canUpdate}
              options={types.map((item) => ({ value: item.id, label: item.key }))}
            />
          </Form.Item>
          <Form.Item name="field_key">
            <Input placeholder="field_key" disabled={!canUpdate} />
          </Form.Item>
          <Form.Item name="operator" initialValue="contains_any">
            <Select
              style={{ width: 150 }}
              disabled={!canUpdate}
              options={[
                { value: "equals_any", label: "equals_any" },
                { value: "contains_any", label: "contains_any" },
              ]}
            />
          </Form.Item>
          <Form.Item name="pattern" rules={[{ required: true }]}>
            <Input placeholder={"\u5339\u914d\u6587\u672c"} disabled={!canUpdate} />
          </Form.Item>
          <Form.Item name="reason_type" initialValue="data_conflict">
            <Select
              style={{ width: 180 }}
              disabled={!canUpdate}
              options={[
                { value: "suspected_violation", label: "\u7591\u4f3c\u8fdd\u89c4" },
                { value: "suspected_impersonation", label: "\u7591\u4f3c\u5192\u7528" },
                { value: "data_conflict", label: "\u8d44\u6599\u51b2\u7a81" },
                { value: "high_risk_industry", label: "\u9ad8\u98ce\u9669\u884c\u4e1a" },
              ]}
            />
          </Form.Item>
          <Button htmlType="submit" disabled={!canUpdate} loading={busy}>
            {"\u521b\u5efa"}
          </Button>
        </Form>
      </Card>
      <Table
        rowKey="id"
        dataSource={rules}
        pagination={false}
        columns={[
          { title: "key", dataIndex: "key" },
          { title: "\u98ce\u9669\u7c7b\u578b", dataIndex: "risk_type_key" },
          { title: "\u64cd\u4f5c\u7b26", dataIndex: "operator" },
          { title: "\u5339\u914d\u503c", render: (_, item) => item.patterns.join(", ") },
          {
            title: "\u8349\u7a3f\u542f\u7528",
            render: (_, item) => (
              <Switch
                checked={item.enabled}
                disabled={!canUpdate || busy}
                onChange={(checked) => void toggleRule(item, checked)}
              />
            ),
          },
        ]}
      />
    </main>
  );
}
