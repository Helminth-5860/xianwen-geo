"use client";

import { PlusOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  deleteSubject,
  createSubject,
  getSubjects,
  getSubjectTypes,
  notifySubjectContextUpdated,
  setCurrentSubject,
  type SubjectContext,
  type SubjectSummary,
  type SubjectType,
} from "@/lib/subjects-client";

function formatUpdatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function serviceAreaLabel(value: string) {
  if (!value) return "待完善";
  try {
    const parsed = JSON.parse(value) as {
      nationwide?: boolean;
      areas?: Array<{ name?: string; path?: Array<{ name?: string }> }>;
    };
    if (parsed.nationwide) return "全国";
    const areas = Array.isArray(parsed.areas) ? parsed.areas : [];
    const names = areas.map((area) => {
      const path = Array.isArray(area.path) ? area.path : [];
      return (
        path
          .map((item) => item.name)
          .filter(Boolean)
          .join(" / ") ||
        area.name ||
        ""
      );
    });
    return names.filter(Boolean).join("；") || "待完善";
  } catch {
    return value;
  }
}

export default function SubjectsPage() {
  const router = useRouter();
  const [subjects, setSubjects] = useState<SubjectSummary[]>();
  const [context, setContext] = useState<SubjectContext>({
    current_subject_id: null,
    version: 0,
  });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [types, setTypes] = useState<SubjectType[]>();
  const [selectedTypeId, setSelectedTypeId] = useState("");
  const [subjectName, setSubjectName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const load = useCallback(async () => {
    const subjectData = await getSubjects();
    setSubjects(subjectData.subjects);
    setContext(subjectData.context);
  }, []);

  useEffect(() => {
    let current = true;
    const loadInitial = async () => {
      try {
        const subjectData = await getSubjects();
        if (!current) return;
        setSubjects(subjectData.subjects);
        setContext(subjectData.context);
      } catch (reason) {
        if (current) setError(userMessage(reason));
      }
    };

    void loadInitial();

    return () => {
      current = false;
    };
  }, []);

  const openCreate = async () => {
    setCreateOpen(true);
    setCreateError("");
    if (types !== undefined) return;
    try {
      const rows = await getSubjectTypes();
      setTypes(rows);
      setSelectedTypeId((current) => current || rows[0]?.id || "");
    } catch (reason) {
      setCreateError(userMessage(reason));
    }
  };

  const submitCreate = async () => {
    const name = subjectName.trim();
    const selectedType = types?.find((item) => item.id === selectedTypeId);
    if (!name) {
      setCreateError("请填写主体名称");
      return;
    }
    if (!selectedType) {
      setCreateError("请选择主体类型");
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      const subject = await createSubject(selectedType.id, selectedType.schema_version, { name });
      notifySubjectContextUpdated();
      router.push(`/subjects/${subject.id}`);
    } catch (reason) {
      setCreateError(userMessage(reason));
      setCreating(false);
    }
  };

  const execute = async (operation: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await operation();
      await load();
      notifySubjectContextUpdated();
      setError("");
      setNotice(message);
    } catch (reason) {
      setNotice("");
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  if (subjects === undefined && !error) {
    return <Spin fullscreen description="正在加载主体档案" />;
  }

  return (
    <main className="page-shell">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <Space wrap align="baseline">
          <Typography.Title>主体管理</Typography.Title>
          <Button href="/assistant">显问 AI 助手</Button>
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => void openCreate()}>
          新增主体
        </Button>
      </div>
      <Typography.Paragraph type="secondary">
        统一管理主体档案。保存后的主体立即可用，可随时查看、编辑、切换或删除。
      </Typography.Paragraph>
      {error && (
        <Alert type="error" showIcon message={error} closable onClose={() => setError("")} />
      )}
      {notice && (
        <Alert type="success" showIcon message={notice} closable onClose={() => setNotice("")} />
      )}
      <Table
        rowKey="id"
        dataSource={subjects ?? []}
        pagination={false}
        locale={{ emptyText: "还没有主体，请点击右上角“新增主体”开始创建" }}
        columns={[
          {
            title: "主体名称",
            render: (_, item) => (
              <Space>
                <Link href={`/subjects/${item.id}?mode=view`}>
                  {item.official_name || item.subject_type.name}
                </Link>
                {item.is_current && <Tag color="blue">当前</Tag>}
              </Space>
            ),
          },
          { title: "主体类型", render: (_, item) => item.subject_type.name },
          {
            title: "服务区域",
            render: (_, item) => serviceAreaLabel(item.service_regions),
          },
          {
            title: "资料完整度",
            width: 180,
            render: (_, item) => (
              <Progress
                percent={item.profile_completeness?.percentage ?? 0}
                size="small"
                status="normal"
              />
            ),
          },
          {
            title: "更新时间",
            render: (_, item) => formatUpdatedAt(item.updated_at),
          },
          {
            title: "当前状态",
            render: (_, item) =>
              item.is_current ? (
                <Tag color="blue">当前</Tag>
              ) : item.current_version_no !== null ? (
                <Tag color="green">可用</Tag>
              ) : (
                <Tag color="orange">待完善</Tag>
              ),
          },
          {
            title: "操作",
            render: (_, item) => (
              <Space wrap>
                <Link href={`/subjects/${item.id}?mode=view`}>查看</Link>
                <Link href={`/subjects/${item.id}`}>编辑</Link>
                {!item.is_current && item.current_version_no !== null && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void execute(
                        () => setCurrentSubject(item.id, context.version),
                        "当前主体已更新",
                      )
                    }
                  >
                    设为当前
                  </Button>
                )}
                <Popconfirm
                  title={item.is_current ? "确认删除当前主体？" : "确认删除这个主体？"}
                  description={
                    item.is_current
                      ? "删除后会自动切换到其他可用主体；如无其他主体，将清空当前主体。"
                      : "删除后将从主体管理中移除，相关历史报告仍会保留。"
                  }
                  okText="确认删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => void execute(() => deleteSubject(item), "主体已删除")}
                >
                  <Button danger disabled={busy}>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title="新增主体"
        open={createOpen}
        okText="创建并完善资料"
        cancelText="取消"
        confirmLoading={creating}
        okButtonProps={{ disabled: !types?.length }}
        onCancel={() => {
          if (creating) return;
          setCreateOpen(false);
          setCreateError("");
        }}
        onOk={() => void submitCreate()}
      >
        <Typography.Paragraph type="secondary">
          先填写主体名称并选择类型，创建后继续完善行业、业务、地址和覆盖区域。
        </Typography.Paragraph>
        {createError && (
          <Alert type="error" showIcon message={createError} style={{ marginBottom: 16 }} />
        )}
        <Form layout="vertical">
          <Form.Item label="主体名称" required extra="填写对外使用的正式名称。">
            <Input
              aria-label="新增主体名称"
              value={subjectName}
              maxLength={500}
              placeholder="例如：广州显问网络科技有限公司"
              onChange={(event) => {
                setSubjectName(event.target.value);
                setCreateError("");
              }}
            />
          </Form.Item>
          <Form.Item label="主体类型" required extra="请选择最符合当前主体身份的类型。">
            <Select
              aria-label="新增主体类型"
              value={selectedTypeId || undefined}
              loading={types === undefined && !createError}
              placeholder="请选择主体类型"
              options={types?.map((item) => ({ value: item.id, label: item.name }))}
              onChange={(value) => {
                setSelectedTypeId(value);
                setCreateError("");
              }}
            />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
