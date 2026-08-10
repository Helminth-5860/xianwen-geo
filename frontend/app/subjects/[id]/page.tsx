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
  Spin,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  getSubject,
  updateSubjectDraft,
  type PersistedSubjectField,
  type SubjectDetail,
} from "@/lib/subjects-client";

const statusLabels = {
  draft: "\u8349\u7a3f",
  active: "\u5df2\u6fc0\u6d3b",
  archived: "\u5df2\u5f52\u6863",
} as const;

function normalizedValue(field: PersistedSubjectField, value: unknown): unknown {
  if (field.field_type === "multi") return Array.isArray(value) ? value : [];
  if (field.field_type === "number") return typeof value === "number" ? value : null;
  return value ?? "";
}

function FieldInput({
  field,
  value,
  disabled,
  onChange,
}: {
  field: PersistedSubjectField;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  if (field.field_type === "image" || field.field_type === "file") {
    return (
      <Alert
        type="info"
        showIcon
        title={"\u4e0a\u4f20\u80fd\u529b\u5c1a\u672a\u542f\u7528"}
        description={
          "\u5f53\u524d\u4efb\u52a1\u4ec5\u4fdd\u7559 Schema \u58f0\u660e\uff0c\u4e0d\u63a5\u6536\u6587\u4ef6\u503c\u3002"
        }
      />
    );
  }
  if (field.field_type === "textarea") {
    return (
      <Input.TextArea
        aria-label={field.label}
        value={String(normalizedValue(field, value))}
        disabled={disabled}
        rows={4}
        onChange={(event) => onChange(event.target.value || null)}
      />
    );
  }
  if (field.field_type === "number") {
    return (
      <InputNumber
        aria-label={field.label}
        value={normalizedValue(field, value) as number | null}
        disabled={disabled}
        style={{ width: "100%" }}
        onChange={(next) => onChange(next)}
      />
    );
  }
  if (field.field_type === "single" || field.field_type === "select") {
    return (
      <Select
        aria-label={field.label}
        value={(value as string | null) ?? undefined}
        disabled={disabled}
        allowClear={!field.required}
        style={{ width: "100%" }}
        options={field.options.map((option) => ({
          value: option.option_key,
          label: option.label,
        }))}
        onChange={(next) => onChange(next ?? null)}
      />
    );
  }
  if (field.field_type === "multi") {
    return (
      <Select
        aria-label={field.label}
        mode="multiple"
        value={normalizedValue(field, value) as string[]}
        disabled={disabled}
        style={{ width: "100%" }}
        options={field.options.map((option) => ({
          value: option.option_key,
          label: option.label,
        }))}
        onChange={onChange}
      />
    );
  }
  return (
    <Input
      aria-label={field.label}
      type={field.field_type === "date" ? "date" : "text"}
      inputMode={field.field_type === "url" ? "url" : undefined}
      value={String(normalizedValue(field, value))}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value || null)}
    />
  );
}

export default function SubjectDetailPage() {
  const params = useParams<{ id: string }>();
  const [subject, setSubject] = useState<SubjectDetail>();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let current = true;
    void getSubject(params.id)
      .then((data) => {
        if (!current) return;
        setSubject(data);
        setValues(data.draft_values);
      })
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      });
    return () => {
      current = false;
    };
  }, [params.id]);

  const save = async () => {
    if (!subject) return;
    setSaving(true);
    try {
      const updated = await updateSubjectDraft(subject, values);
      setSubject(updated);
      setValues(updated.draft_values);
      setError("");
      setNotice("\u8349\u7a3f\u5df2\u4fdd\u5b58");
    } catch (reason) {
      setNotice("");
      setError(userMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  if (!subject && !error) {
    return <Spin fullscreen description={"\u6b63\u5728\u52a0\u8f7d\u4e3b\u4f53\u8349\u7a3f"} />;
  }

  return (
    <main className="page-shell">
      <Link href="/subjects">{"\u8fd4\u56de\u4e3b\u4f53\u5217\u8868"}</Link>
      {error && <Alert type="error" showIcon message={error} style={{ marginTop: 20 }} />}
      {notice && <Alert type="success" showIcon message={notice} style={{ marginTop: 20 }} />}
      {subject && (
        <>
          <Space align="baseline">
            <Typography.Title>{subject.form_schema.name}</Typography.Title>
            <Tag>{statusLabels[subject.status]}</Tag>
            {subject.is_current && <Tag color="blue">{"\u5f53\u524d\u4e3b\u4f53"}</Tag>}
          </Space>
          <Typography.Paragraph type="secondary">
            {subject.form_schema.description}
          </Typography.Paragraph>
          <Alert
            type="info"
            showIcon
            message={`\u6b63\u5728\u4f7f\u7528\u521b\u5efa\u65f6\u4fdd\u5b58\u7684 Schema v${subject.schema_version}`}
            description={
              "\u7ba1\u7406\u5458\u540e\u7eed\u4fee\u6539\u5b57\u6bb5\u4e0d\u4f1a\u6539\u53d8\u8be5\u5386\u53f2\u8349\u7a3f\u7684\u8bed\u4e49\u3002"
            }
          />
          <Card style={{ marginTop: 20 }}>
            <Form layout="vertical" onFinish={() => void save()}>
              {subject.form_schema.fields.map((field) => (
                <Form.Item
                  key={field.field_key}
                  label={field.label}
                  required={field.required}
                  extra={field.description}
                >
                  <FieldInput
                    field={field}
                    value={values[field.field_key]}
                    disabled={subject.status === "archived"}
                    onChange={(value) =>
                      setValues((current) => ({ ...current, [field.field_key]: value }))
                    }
                  />
                </Form.Item>
              ))}
              <Button
                htmlType="submit"
                type="primary"
                loading={saving}
                disabled={subject.status === "archived"}
              >
                {"\u4fdd\u5b58\u8349\u7a3f"}
              </Button>
            </Form>
          </Card>
        </>
      )}
    </main>
  );
}
