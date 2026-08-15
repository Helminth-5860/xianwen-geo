"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { SubjectAiEnrichment } from "@/components/subject-ai-enrichment";
import { SubjectDocuments } from "@/components/subject-documents";
import { SubjectWebSources } from "@/components/subject-web-sources";
import { userMessage } from "@/lib/auth-client";
import type { SubjectDocument } from "@/lib/documents-client";
import {
  commitSubject,
  getSubject,
  updateSubjectDraft,
  type PersistedSubjectField,
  type SubjectDetail,
  type SubjectProductConfirmation,
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
  documents,
  onChange,
}: {
  field: PersistedSubjectField;
  value: unknown;
  disabled: boolean;
  documents: SubjectDocument[];
  onChange: (value: unknown) => void;
}) {
  if (field.field_type === "image" || field.field_type === "file") {
    const choices = documents.filter(
      (document) =>
        field.field_type === "file" ||
        ["jpeg", "png", "webp"].includes(document.detected_file_kind),
    );
    return (
      <Select
        aria-label={field.label}
        value={(value as { document_version_id?: string } | null)?.document_version_id}
        disabled={disabled}
        allowClear={!field.required}
        placeholder="选择资料库中已完成安全验证的文件"
        style={{ width: "100%" }}
        options={choices.map((document) => ({
          value: document.document_version_id,
          label: document.display_name,
        }))}
        onChange={(documentVersionId) =>
          onChange(documentVersionId ? { document_version_id: documentVersionId } : null)
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

function defaultProductConfirmations(subject: SubjectDetail) {
  return Object.fromEntries(
    subject.product_candidates.map((candidate) => [
      candidate.candidate_key,
      {
        candidate_key: candidate.candidate_key,
        uniqueness_confirmed: false,
        include_in_mention: false,
      },
    ]),
  ) as Record<string, SubjectProductConfirmation>;
}

export default function SubjectDetailPage() {
  const params = useParams<{ id: string }>();
  const [subject, setSubject] = useState<SubjectDetail>();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [productConfirmations, setProductConfirmations] = useState<
    Record<string, SubjectProductConfirmation>
  >({});
  const [documents, setDocuments] = useState<SubjectDocument[]>([]);

  useEffect(() => {
    let current = true;
    void getSubject(params.id)
      .then((data) => {
        if (!current) return;
        setSubject(data);
        setValues(data.draft_values);
        setProductConfirmations(defaultProductConfirmations(data));
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
      setProductConfirmations(defaultProductConfirmations(updated));
      setNotice("\u8349\u7a3f\u5df2\u4fdd\u5b58");
    } catch (reason) {
      setNotice("");
      setError(userMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  const commit = async () => {
    if (!subject) return;
    if (JSON.stringify(values) !== JSON.stringify(subject.draft_values)) {
      setError(
        "\u8bf7\u5148\u4fdd\u5b58\u8349\u7a3f\uff0c\u518d\u63d0\u4ea4\u6b63\u5f0f\u7248\u672c",
      );
      return;
    }
    const missingRequired = subject.form_schema.fields.some((field) => {
      if (!field.required) return false;
      const value = subject.draft_values[field.field_key];
      if (value === null || value === undefined) return true;
      if (typeof value === "string") return value.trim().length === 0;
      if (Array.isArray(value)) return value.length === 0;
      return false;
    });
    if (missingRequired) {
      setError("\u8bf7\u5148\u5b8c\u6574\u586b\u5199\u6240\u6709\u5fc5\u586b\u5b57\u6bb5");
      return;
    }
    setCommitting(true);
    try {
      const result = await commitSubject(
        subject,
        subject.product_candidates.map(
          (candidate) =>
            productConfirmations[candidate.candidate_key] ?? {
              candidate_key: candidate.candidate_key,
              uniqueness_confirmed: false,
              include_in_mention: false,
            },
        ),
      );
      setSubject(result.subject);
      setValues(result.subject.draft_values);
      setProductConfirmations(defaultProductConfirmations(result.subject));
      setError("");
      setNotice(`\u6b63\u5f0f\u7248\u672c v${result.version.version_no} \u5df2\u63d0\u4ea4`);
    } catch (reason) {
      setNotice("");
      setError(userMessage(reason));
    } finally {
      setCommitting(false);
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
            {subject.current_version_no !== null && (
              <Tag color="green">{`\u6b63\u5f0f\u7248\u672c v${subject.current_version_no}`}</Tag>
            )}
            {subject.retest_required && (
              <Tag color="orange">{"\u9700\u91cd\u65b0\u68c0\u6d4b"}</Tag>
            )}
            <Tag
              color={
                subject.risk.status === "approved" || subject.risk.status === "clear"
                  ? "green"
                  : subject.risk.status === "rejected"
                    ? "red"
                    : "orange"
              }
            >
              {`\u98ce\u9669\u72b6\u6001: ${subject.risk.status}`}
            </Tag>
          </Space>
          {subject.risk.public_reason && (
            <Alert
              type="warning"
              showIcon
              message={"\u5ba1\u6838\u539f\u56e0"}
              description={subject.risk.public_reason}
            />
          )}
          <Typography.Paragraph>
            <Link href={`/subjects/${subject.id}/versions`}>
              {"\u67e5\u770b\u6b63\u5f0f\u7248\u672c\u5386\u53f2"}
            </Link>
          </Typography.Paragraph>
          <Typography.Paragraph>
            <Link href={`/subjects/${subject.id}/keywords`}>管理关键词</Link>
          </Typography.Paragraph>
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
          <SubjectDocuments
            subjectId={subject.id}
            disabled={subject.status === "archived"}
            onDocumentsChange={setDocuments}
          />
          <SubjectWebSources subjectId={subject.id} disabled={subject.status === "archived"} />
          <SubjectAiEnrichment
            subject={subject}
            localValues={values}
            disabled={subject.status === "archived"}
            onApplied={(updated) => {
              setSubject(updated);
              setValues(updated.draft_values);
              setProductConfirmations(defaultProductConfirmations(updated));
            }}
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
                    documents={documents}
                    onChange={(value) =>
                      setValues((current) => ({ ...current, [field.field_key]: value }))
                    }
                  />
                </Form.Item>
              ))}
              {subject.product_candidates.length > 0 && (
                <Card
                  size="small"
                  title={"\u4ea7\u54c1\u5019\u9009\u786e\u8ba4"}
                  style={{ marginBottom: 20 }}
                >
                  <Typography.Paragraph type="secondary">
                    {
                      "\u5019\u9009\u4ea7\u54c1\u7531\u670d\u52a1\u7aef\u4ece\u5df2\u4fdd\u5b58\u8349\u7a3f\u6d3e\u751f\uff0c\u4e0d\u80fd\u81ea\u884c\u6dfb\u52a0\u3002"
                    }
                  </Typography.Paragraph>
                  <Space direction="vertical">
                    {subject.product_candidates.map((candidate) => {
                      const confirmation = productConfirmations[candidate.candidate_key];
                      const unique = confirmation?.uniqueness_confirmed ?? false;
                      return (
                        <Space key={candidate.candidate_key} wrap>
                          <Typography.Text>{candidate.display_value}</Typography.Text>
                          <Checkbox
                            aria-label={`${candidate.display_value}\u552f\u4e00\u6027\u5df2\u786e\u8ba4`}
                            checked={unique}
                            disabled={subject.status === "archived"}
                            onChange={(event) =>
                              setProductConfirmations((current) => ({
                                ...current,
                                [candidate.candidate_key]: {
                                  candidate_key: candidate.candidate_key,
                                  uniqueness_confirmed: event.target.checked,
                                  include_in_mention: event.target.checked
                                    ? (current[candidate.candidate_key]?.include_in_mention ??
                                      false)
                                    : false,
                                },
                              }))
                            }
                          >
                            {"\u5df2\u786e\u8ba4\u552f\u4e00\u6027"}
                          </Checkbox>
                          <Checkbox
                            aria-label={`${candidate.display_value}\u52a0\u5165\u63d0\u53ca\u8bcd`}
                            checked={confirmation?.include_in_mention ?? false}
                            disabled={subject.status === "archived" || !unique}
                            onChange={(event) =>
                              setProductConfirmations((current) => ({
                                ...current,
                                [candidate.candidate_key]: {
                                  candidate_key: candidate.candidate_key,
                                  uniqueness_confirmed: true,
                                  include_in_mention: event.target.checked,
                                },
                              }))
                            }
                          >
                            {"\u52a0\u5165\u63d0\u53ca\u8bcd"}
                          </Checkbox>
                        </Space>
                      );
                    })}
                  </Space>
                </Card>
              )}
              <Space>
                <Button
                  htmlType="submit"
                  type="primary"
                  loading={saving}
                  disabled={subject.status === "archived"}
                >
                  {"\u4fdd\u5b58\u8349\u7a3f"}
                </Button>
                <Popconfirm
                  title={"\u63d0\u4ea4\u6b63\u5f0f\u7248\u672c"}
                  description={
                    "\u6b63\u5f0f\u7248\u672c\u5c06\u4f5c\u4e3a\u4e0d\u53ef\u53d8\u5386\u53f2\u4fdd\u5b58\u3002"
                  }
                  okText={"\u786e\u8ba4\u63d0\u4ea4"}
                  cancelText={"\u53d6\u6d88"}
                  onConfirm={() => void commit()}
                >
                  <Button loading={committing} disabled={subject.status === "archived"}>
                    {"\u63d0\u4ea4\u6b63\u5f0f\u7248\u672c"}
                  </Button>
                </Popconfirm>
              </Space>
            </Form>
          </Card>
        </>
      )}
    </main>
  );
}
