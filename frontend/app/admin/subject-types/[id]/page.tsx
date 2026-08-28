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
  Table,
  Tag,
  Typography,
} from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  changeSubjectTypeStatus,
  createSubjectField,
  createSubjectFieldOption,
  getAdminSubjectType,
  reorderSubjectFields,
  updateSubjectField,
  updateSubjectFieldOption,
  updateSubjectType,
  type SubjectFieldConfig,
  type SubjectFieldType,
  type SubjectType,
} from "@/lib/subjects-client";

const FIELD_TYPES: { value: SubjectFieldType; label: string }[] = [
  { value: "text", label: "单行文本" },
  { value: "textarea", label: "多行文本" },
  { value: "number", label: "数字" },
  { value: "date", label: "日期" },
  { value: "url", label: "HTTP/HTTPS 链接" },
  { value: "single", label: "单选" },
  { value: "multi", label: "多选" },
  { value: "select", label: "下拉选择" },
  { value: "image", label: "图片（仅 Schema）" },
  { value: "file", label: "文件（仅 Schema）" },
];

const isChoice = (field: SubjectFieldConfig) =>
  ["single", "multi", "select"].includes(field.field_type);

type NewFieldValues = {
  field_key: string;
  field_type: SubjectFieldType;
  label: string;
  description?: string;
};

export default function AdminSubjectTypeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const capabilities = useAdminCapabilities();
  const [subjectType, setSubjectType] = useState<SubjectType | null>(null);
  const [fields, setFields] = useState<SubjectFieldConfig[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [newFieldForm] = Form.useForm<NewFieldValues>();
  const [typeForm] = Form.useForm();
  const [optionKey, setOptionKey] = useState("");
  const [optionLabel, setOptionLabel] = useState("");
  const [optionFieldId, setOptionFieldId] = useState("");
  const canUpdate = capabilities?.permission_keys.includes("subject_types.update") ?? false;
  const canDisable = capabilities?.permission_keys.includes("subject_types.disable") ?? false;
  const canCreateField = capabilities?.permission_keys.includes("subject_fields.create") ?? false;
  const canUpdateField = capabilities?.permission_keys.includes("subject_fields.update") ?? false;

  const load = useCallback(
    () =>
      getAdminSubjectType(id)
        .then((result) => {
          setSubjectType(result);
          setFields(result.fields);
          typeForm.setFieldsValue({
            name: result.name,
            description: result.description,
            icon_key: result.icon_key,
            sort_order: result.sort_order,
          });
        })
        .catch((reason) => setError(userMessage(reason))),
    [id, typeForm],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const ordered = useMemo(() => [...fields].sort((a, b) => a.sort_order - b.sort_order), [fields]);

  if (!subjectType) {
    return (
      <main className="admin-page">
        {error ? <Alert type="error" message={error} /> : "加载中…"}
      </main>
    );
  }

  const mutate = async (operation: () => Promise<unknown>, success: string) => {
    setError("");
    try {
      await operation();
      setMessage(success);
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    }
  };

  const move = (fieldId: string, direction: -1 | 1) => {
    const current = ordered.findIndex((field) => field.id === fieldId);
    const target = current + direction;
    if (target < 0 || target >= ordered.length) return;
    const next = [...ordered];
    [next[current], next[target]] = [next[target], next[current]];
    setFields(next.map((field, index) => ({ ...field, sort_order: index * 10 })));
  };

  return (
    <main className="admin-page">
      <Typography.Title>{subjectType.name}</Typography.Title>
      <Typography.Paragraph>
        类型 key：{subjectType.key}；Schema 版本：{subjectType.schema_version}
      </Typography.Paragraph>
      {message && <Alert type="success" showIcon message={message} />}
      {error && <Alert type="error" showIcon message={error} />}

      <Card title="类型展示信息">
        <Form
          form={typeForm}
          layout="vertical"
          onFinish={(values) =>
            void mutate(
              () =>
                updateSubjectType(
                  subjectType.id,
                  subjectType.version ?? 1,
                  subjectType.schema_version,
                  values,
                ),
              "类型信息已更新",
            )
          }
        >
          <Space wrap align="start">
            <Form.Item label="类型名称" name="name">
              <Input disabled={!canUpdate} />
            </Form.Item>
            <Form.Item label="纯文本说明" name="description">
              <Input disabled={!canUpdate} />
            </Form.Item>
            <Form.Item label="图标 key" name="icon_key">
              <Input disabled={!canUpdate} />
            </Form.Item>
            <Form.Item label="排序" name="sort_order">
              <InputNumber min={0} disabled={!canUpdate} />
            </Form.Item>
            <Form.Item label=" ">
              <Button htmlType="submit" disabled={!canUpdate}>
                保存展示信息
              </Button>
            </Form.Item>
          </Space>
        </Form>
        <Button
          danger={subjectType.status === "active"}
          disabled={!canDisable}
          onClick={() =>
            void mutate(
              () =>
                changeSubjectTypeStatus(
                  subjectType.id,
                  subjectType.status === "active" ? "disable" : "enable",
                  subjectType.version ?? 1,
                  subjectType.schema_version,
                ),
              subjectType.status === "active" ? "主体类型已停用" : "主体类型已启用",
            )
          }
        >
          {subjectType.status === "active" ? "停用主体类型" : "启用主体类型"}
        </Button>
      </Card>

      <Card title="创建自定义字段">
        <Alert
          type="info"
          showIcon
          message="字段 key、类型、scope 和 owner 创建后不可切换；建错时停用旧字段并创建新 key。"
        />
        <Form
          form={newFieldForm}
          layout="vertical"
          onFinish={(values) =>
            void mutate(
              () =>
                createSubjectField(subjectType.id, subjectType.schema_version, {
                  ...values,
                  description: values.description ?? "",
                  enabled: false,
                }),
              "自定义字段已创建",
            ).then(() => newFieldForm.resetFields())
          }
        >
          <Space wrap align="start">
            <Form.Item label="字段 key" name="field_key" rules={[{ required: true }]}>
              <Input disabled={!canCreateField} />
            </Form.Item>
            <Form.Item
              label="字段类型（仅创建时选择）"
              name="field_type"
              rules={[{ required: true }]}
            >
              <Select style={{ width: 220 }} options={FIELD_TYPES} disabled={!canCreateField} />
            </Form.Item>
            <Form.Item label="字段名称" name="label" rules={[{ required: true }]}>
              <Input disabled={!canCreateField} />
            </Form.Item>
            <Form.Item label="纯文本说明" name="description">
              <Input disabled={!canCreateField} />
            </Form.Item>
            <Form.Item label=" ">
              <Button type="primary" htmlType="submit" disabled={!canCreateField}>
                创建字段
              </Button>
            </Form.Item>
          </Space>
        </Form>
      </Card>

      <Card title="字段配置与完整排序">
        <Table
          rowKey="id"
          dataSource={ordered}
          pagination={false}
          columns={[
            {
              title: "字段",
              render: (_, field) => (
                <Space direction="vertical" size={0}>
                  <span>{field.label}</span>
                  <Typography.Text type="secondary">
                    {field.field_key} · {field.field_type}
                  </Typography.Text>
                  {field.scope === "common" && <Tag>公共字段</Tag>}
                  {["image", "file"].includes(field.field_type) && (
                    <Alert type="warning" message="仅声明 Schema，上传能力尚未启用" />
                  )}
                </Space>
              ),
            },
            {
              title: "业务配置",
              render: (_, field) => (
                <Space wrap>
                  <Checkbox
                    checked={field.enabled}
                    disabled={!canUpdateField}
                    onChange={(event) =>
                      void mutate(
                        () =>
                          updateSubjectField(field, subjectType.schema_version, {
                            enabled: event.target.checked,
                            required: event.target.checked ? field.required : false,
                          }),
                        "字段启停状态已更新",
                      )
                    }
                  >
                    启用
                  </Checkbox>
                  <Checkbox
                    checked={field.required}
                    disabled={!canUpdateField || !field.enabled}
                    onChange={(event) =>
                      void mutate(
                        () =>
                          updateSubjectField(field, subjectType.schema_version, {
                            required: event.target.checked,
                          }),
                        "必填配置已更新",
                      )
                    }
                  >
                    必填
                  </Checkbox>
                  <Checkbox
                    checked={field.used_for_ai}
                    disabled={!canUpdateField}
                    onChange={(event) =>
                      void mutate(
                        () =>
                          updateSubjectField(field, subjectType.schema_version, {
                            used_for_ai: event.target.checked,
                          }),
                        "AI 使用标记已更新",
                      )
                    }
                  >
                    用于 AI
                  </Checkbox>
                </Space>
              ),
            },
            {
              title: "选项",
              render: (_, field) =>
                isChoice(field) ? (
                  <Space direction="vertical">
                    {field.options.map((option) => (
                      <Space key={option.id}>
                        <span>
                          {option.option_key}：{option.label}
                        </span>
                        <Switch
                          size="small"
                          checked={option.enabled}
                          disabled={!canUpdateField}
                          onChange={(enabled) =>
                            void mutate(
                              () =>
                                updateSubjectFieldOption(option, subjectType.schema_version, {
                                  enabled,
                                }),
                              "选项状态已更新",
                            )
                          }
                        />
                      </Space>
                    ))}
                    <Button
                      size="small"
                      disabled={!canUpdateField}
                      onClick={() => setOptionFieldId(field.id)}
                    >
                      添加稳定选项
                    </Button>
                  </Space>
                ) : (
                  "不适用"
                ),
            },
            {
              title: "顺序",
              render: (_, field, index) => (
                <Space>
                  <Button
                    aria-label={`上移 ${field.field_key}`}
                    disabled={!canUpdateField || index === 0}
                    onClick={() => move(field.id, -1)}
                  >
                    ↑
                  </Button>
                  <Button
                    aria-label={`下移 ${field.field_key}`}
                    disabled={!canUpdateField || index === ordered.length - 1}
                    onClick={() => move(field.id, 1)}
                  >
                    ↓
                  </Button>
                </Space>
              ),
            },
          ]}
        />
        <Button
          type="primary"
          disabled={!canUpdateField}
          onClick={() =>
            void mutate(
              () => reorderSubjectFields(subjectType.id, subjectType.schema_version, ordered),
              "完整字段顺序已保存",
            )
          }
        >
          保存完整字段顺序
        </Button>
      </Card>

      {optionFieldId && (
        <Card title="新增字段选项">
          <Space wrap>
            <Input
              aria-label="稳定 option key"
              value={optionKey}
              onChange={(event) => setOptionKey(event.target.value)}
            />
            <Input
              aria-label="选项纯文本名称"
              value={optionLabel}
              onChange={(event) => setOptionLabel(event.target.value)}
            />
            <Button
              type="primary"
              onClick={() => {
                const field = fields.find((item) => item.id === optionFieldId);
                if (!field) return;
                void mutate(
                  () =>
                    createSubjectFieldOption(field, subjectType.schema_version, {
                      option_key: optionKey,
                      label: optionLabel,
                    }),
                  "选项已添加",
                ).then(() => {
                  setOptionFieldId("");
                  setOptionKey("");
                  setOptionLabel("");
                });
              }}
            >
              添加选项
            </Button>
            <Button onClick={() => setOptionFieldId("")}>取消</Button>
          </Space>
        </Card>
      )}
    </main>
  );
}
