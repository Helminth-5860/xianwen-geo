"use client";

import { BankOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Form, Input, Modal, Select, Spin, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  createSubject,
  getSubjects,
  getSubjectTypes,
  type SubjectSummary,
  type SubjectType,
} from "@/lib/subjects-client";

export default function SubjectsPage() {
  const router = useRouter();
  const [subjects, setSubjects] = useState<SubjectSummary[]>();
  const [types, setTypes] = useState<SubjectType[]>();
  const [selectedTypeId, setSelectedTypeId] = useState("");
  const [subjectName, setSubjectName] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    void getSubjects()
      .then((data) => {
        if (current) setSubjects(data.subjects);
      })
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      });
    return () => {
      current = false;
    };
  }, []);

  const boundSubject = useMemo(
    () => subjects?.find((subject) => subject.status === "active" && subject.identity_bound),
    [subjects],
  );
  const draftSubject = useMemo(
    () => subjects?.find((subject) => subject.status === "draft"),
    [subjects],
  );

  useEffect(() => {
    if (boundSubject) router.replace(`/subjects/${boundSubject.id}`);
  }, [boundSubject, router]);

  const openBinding = async () => {
    if (draftSubject) {
      router.push(`/subjects/${draftSubject.id}`);
      return;
    }
    setCreateOpen(true);
    setError("");
    if (types !== undefined) return;
    try {
      const rows = await getSubjectTypes();
      setTypes(rows);
      setSelectedTypeId(rows[0]?.id ?? "");
    } catch (reason) {
      setError(userMessage(reason));
    }
  };

  const createBindingDraft = async () => {
    const name = subjectName.trim();
    const selectedType = types?.find((item) => item.id === selectedTypeId);
    if (!name) {
      setError("请填写主体正式名称");
      return;
    }
    if (!selectedType) {
      setError("请选择主体类型");
      return;
    }
    setCreating(true);
    setError("");
    try {
      const subject = await createSubject(selectedType.id, selectedType.schema_version, { name });
      router.push(`/subjects/${subject.id}`);
    } catch (reason) {
      setError(userMessage(reason));
      setCreating(false);
    }
  };

  if (subjects === undefined && !error) {
    return <Spin fullscreen description="正在加载主体档案" />;
  }
  if (boundSubject) {
    return <Spin fullscreen description="正在进入主体档案" />;
  }

  return (
    <main className="page-shell">
      <Typography.Title>主体管理</Typography.Title>
      <Typography.Paragraph type="secondary">
        每个工作空间绑定一个主体，绑定后可持续完善经营资料和查看资料更新记录。
      </Typography.Paragraph>
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          closable
          onClose={() => setError("")}
          style={{ marginBottom: 16 }}
        />
      )}
      <Card>
        <div style={{ maxWidth: 640, margin: "32px auto", textAlign: "center" }}>
          <BankOutlined style={{ fontSize: 44, color: "#2f6fff", marginBottom: 18 }} />
          <Typography.Title level={3}>绑定主体</Typography.Title>
          <Typography.Paragraph type="secondary">
            请填写真实、准确的主体身份与经营资料。主体绑定后，关键词、检测、洞察和内容资产都会使用同一个主体档案。
          </Typography.Paragraph>
          <Button type="primary" size="large" onClick={() => void openBinding()}>
            {draftSubject ? "继续绑定主体" : "绑定主体"}
          </Button>
        </div>
      </Card>

      <Modal
        title="绑定主体"
        open={createOpen}
        okText="继续完善资料"
        cancelText="取消"
        confirmLoading={creating}
        okButtonProps={{ disabled: !types?.length }}
        onCancel={() => {
          if (!creating) setCreateOpen(false);
        }}
        onOk={() => void createBindingDraft()}
      >
        <Typography.Paragraph type="secondary">
          先确认正式名称和主体类型，下一步补充完整资料后再正式绑定。
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="主体正式名称" required extra="请填写营业执照或公开资料使用的正式名称。">
            <Input
              aria-label="主体正式名称"
              value={subjectName}
              maxLength={500}
              placeholder="例如：广州显问网络科技有限公司"
              onChange={(event) => {
                setSubjectName(event.target.value);
                setError("");
              }}
            />
          </Form.Item>
          <Form.Item label="主体类型" required extra="绑定后普通用户不能自行修改主体类型。">
            <Select
              aria-label="主体类型"
              value={selectedTypeId || undefined}
              loading={types === undefined}
              placeholder="请选择主体类型"
              options={types?.map((item) => ({ value: item.id, label: item.name }))}
              onChange={(value) => {
                setSelectedTypeId(value);
                setError("");
              }}
            />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
