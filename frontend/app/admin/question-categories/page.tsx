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
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  changeQuestionCategoryStatus,
  changeQuestionTagStatus,
  createQuestionCategory,
  createQuestionTag,
  getAdminQuestionCategories,
  getAdminQuestionTags,
  type QuestionCategory,
  type QuestionTag,
  updateQuestionCategory,
  updateQuestionTag,
} from "@/lib/question-catalog-client";
import { getSubjectTypes, type SubjectType } from "@/lib/subjects-client";

type CatalogFormValues = {
  key: string;
  name: string;
  description?: string;
  generation_guidance?: string;
  sort_order?: number;
  applicable_subject_type_ids?: string[];
};

type EditingRow =
  { kind: "category"; row: QuestionCategory } | { kind: "tag"; row: QuestionTag } | null;

const applicabilityLabel = (ids: string[], subjectTypes: SubjectType[]) => {
  if (!ids.length) return "全部主体";
  const names = new Map(subjectTypes.map((row) => [row.id, row.name]));
  return ids.map((id) => names.get(id) ?? id).join("、");
};

export default function AdminQuestionCategoriesPage() {
  const capabilities = useAdminCapabilities();
  const [categories, setCategories] = useState<QuestionCategory[]>([]);
  const [tags, setTags] = useState<QuestionTag[]>([]);
  const [subjectTypes, setSubjectTypes] = useState<SubjectType[]>([]);
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<EditingRow>(null);
  const [categoryForm] = Form.useForm<CatalogFormValues>();
  const [tagForm] = Form.useForm<CatalogFormValues>();
  const [editForm] = Form.useForm<CatalogFormValues>();

  const has = (permission: string) => capabilities?.permission_keys.includes(permission) ?? false;
  const subjectOptions = subjectTypes.map((row) => ({ value: row.id, label: row.name }));

  const load = useCallback(async () => {
    setError("");
    try {
      const [nextCategories, nextTags, nextSubjectTypes] = await Promise.all([
        getAdminQuestionCategories(status, keyword),
        getAdminQuestionTags(status, keyword),
        getSubjectTypes(),
      ]);
      setCategories(nextCategories);
      setTags(nextTags);
      setSubjectTypes(nextSubjectTypes);
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [keyword, status]);

  useEffect(() => {
    void Promise.all([getAdminQuestionCategories(), getAdminQuestionTags(), getSubjectTypes()])
      .then(([nextCategories, nextTags, nextSubjectTypes]) => {
        setCategories(nextCategories);
        setTags(nextTags);
        setSubjectTypes(nextSubjectTypes);
      })
      .catch((reason) => setError(userMessage(reason)));
  }, []);

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

  const createCategory = async (values: CatalogFormValues) => {
    await run(
      () =>
        createQuestionCategory({
          key: values.key,
          name: values.name,
          description: values.description ?? "",
          generation_guidance: values.generation_guidance ?? "",
          sort_order: values.sort_order ?? 0,
          applicable_subject_type_ids: values.applicable_subject_type_ids ?? [],
        }),
      "问题分类已创建",
    );
    categoryForm.resetFields();
  };

  const createTag = async (values: CatalogFormValues) => {
    await run(
      () =>
        createQuestionTag({
          key: values.key,
          name: values.name,
          description: values.description ?? "",
          sort_order: values.sort_order ?? 0,
          applicable_subject_type_ids: values.applicable_subject_type_ids ?? [],
        }),
      "辅助标签已创建",
    );
    tagForm.resetFields();
  };

  const beginEdit = (next: Exclude<EditingRow, null>) => {
    setEditing(next);
    editForm.setFieldsValue({
      name: next.row.name,
      description: next.row.description,
      generation_guidance: next.kind === "category" ? next.row.generation_guidance : undefined,
      sort_order: next.row.sort_order,
      applicable_subject_type_ids: next.row.applicable_subject_type_ids,
    });
  };

  const saveEdit = async () => {
    if (!editing) return;
    const values = await editForm.validateFields();
    const common = {
      name: values.name,
      description: values.description ?? "",
      sort_order: values.sort_order ?? 0,
      applicable_subject_type_ids: values.applicable_subject_type_ids ?? [],
    };
    await run(
      () =>
        editing.kind === "category"
          ? updateQuestionCategory(editing.row, {
              ...common,
              generation_guidance: values.generation_guidance ?? "",
            })
          : updateQuestionTag(editing.row, common),
      "目录项已更新",
    );
    setEditing(null);
  };

  const columns = (kind: "category" | "tag") => [
    { title: "key", dataIndex: "key" },
    { title: "名称", dataIndex: "name" },
    { title: "排序", dataIndex: "sort_order" },
    {
      title: "适用主体",
      render: (_: unknown, row: QuestionCategory | QuestionTag) =>
        applicabilityLabel(row.applicable_subject_type_ids, subjectTypes),
    },
    {
      title: "状态",
      render: (_: unknown, row: QuestionCategory | QuestionTag) => (
        <Tag color={row.status === "active" ? "green" : "default"}>
          {row.status === "active" ? "启用" : "停用"}
        </Tag>
      ),
    },
    {
      title: "操作",
      render: (_: unknown, row: QuestionCategory | QuestionTag) => {
        const canUpdate = has(
          kind === "category" ? "question_categories.update" : "question_tags.update",
        );
        const canDisable = has(
          kind === "category" ? "question_categories.disable" : "question_tags.disable",
        );
        const action = row.status === "active" ? "disable" : "enable";
        return (
          <Space>
            <Button
              disabled={!canUpdate}
              onClick={() =>
                beginEdit(
                  kind === "category"
                    ? { kind, row: row as QuestionCategory }
                    : { kind, row: row as QuestionTag },
                )
              }
            >
              编辑
            </Button>
            <Button
              disabled={!canDisable}
              onClick={() =>
                void run(
                  () =>
                    kind === "category"
                      ? changeQuestionCategoryStatus(row as QuestionCategory, action)
                      : changeQuestionTagStatus(row as QuestionTag, action),
                  action === "disable" ? "目录项已停用" : "目录项已启用",
                )
              }
            >
              {action === "disable" ? "停用" : "启用"}
            </Button>
          </Space>
        );
      },
    },
  ];

  const createForm = (kind: "category" | "tag") => {
    const isCategory = kind === "category";
    const form = isCategory ? categoryForm : tagForm;
    const canCreate = has(isCategory ? "question_categories.create" : "question_tags.create");
    return (
      <Card title={isCategory ? "创建问题分类" : "创建辅助标签"}>
        {!canCreate && <Alert type="info" title="当前账号没有创建权限" />}
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => void (isCategory ? createCategory(values) : createTag(values))}
        >
          <Space wrap align="start">
            <Form.Item label="稳定 key" name="key" rules={[{ required: true }]}>
              <Input disabled={!canCreate} />
            </Form.Item>
            <Form.Item label="名称" name="name" rules={[{ required: true }]}>
              <Input disabled={!canCreate} />
            </Form.Item>
            <Form.Item label="说明" name="description">
              <Input disabled={!canCreate} />
            </Form.Item>
            {isCategory && (
              <Form.Item label="生成提示说明" name="generation_guidance">
                <Input.TextArea disabled={!canCreate} />
              </Form.Item>
            )}
            <Form.Item label="适用主体" name="applicable_subject_type_ids">
              <Select
                mode="multiple"
                allowClear
                placeholder="留空表示全部主体"
                options={subjectOptions}
                style={{ minWidth: 220 }}
                disabled={!canCreate}
              />
            </Form.Item>
            <Form.Item label="排序" name="sort_order" initialValue={0}>
              <InputNumber min={0} disabled={!canCreate} />
            </Form.Item>
            <Form.Item label=" ">
              <Button type="primary" htmlType="submit" loading={busy} disabled={!canCreate}>
                {isCategory ? "创建分类" : "创建标签"}
              </Button>
            </Form.Item>
          </Space>
        </Form>
      </Card>
    );
  };

  return (
    <main className="admin-page">
      <Typography.Title>问题分类与辅助标签</Typography.Title>
      <Typography.Paragraph>
        稳定 key 创建后不可修改；留空适用主体表示全局适用。目录项只允许启停，不提供删除。
      </Typography.Paragraph>
      {message && <Alert type="success" showIcon message={message} />}
      {error && <Alert type="error" showIcon message={error} />}
      <Card title="筛选">
        <Space wrap>
          <Input
            aria-label="目录关键字"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <Select
            aria-label="目录状态"
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
      <Tabs
        items={[
          {
            key: "categories",
            label: "问题分类",
            children: (
              <Space orientation="vertical" size="large" style={{ width: "100%" }}>
                {createForm("category")}
                <Table rowKey="id" dataSource={categories} columns={columns("category")} />
              </Space>
            ),
          },
          {
            key: "tags",
            label: "辅助标签",
            children: (
              <Space orientation="vertical" size="large" style={{ width: "100%" }}>
                {createForm("tag")}
                <Table rowKey="id" dataSource={tags} columns={columns("tag")} />
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={editing?.kind === "category" ? "编辑问题分类" : "编辑辅助标签"}
        open={editing !== null}
        confirmLoading={busy}
        onCancel={() => setEditing(null)}
        onOk={() => void saveEdit()}
        okText="保存修改"
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="名称" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="说明" name="description">
            <Input />
          </Form.Item>
          {editing?.kind === "category" && (
            <Form.Item label="生成提示说明" name="generation_guidance">
              <Input.TextArea />
            </Form.Item>
          )}
          <Form.Item label="适用主体" name="applicable_subject_type_ids">
            <Select mode="multiple" allowClear options={subjectOptions} />
          </Form.Item>
          <Form.Item label="排序" name="sort_order">
            <InputNumber min={0} />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
