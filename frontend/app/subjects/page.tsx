"use client";

import { Alert, Button, Card, Select, Space, Spin, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  activateSubject,
  archiveSubject,
  createSubject,
  getSubjects,
  getSubjectTypes,
  setCurrentSubject,
  type SubjectContext,
  type SubjectSummary,
  type SubjectType,
} from "@/lib/subjects-client";

const statusLabels = {
  draft: "资料可编辑",
  active: "正常",
  archived: "\u5df2\u5f52\u6863",
} as const;

export default function SubjectsPage() {
  const [subjects, setSubjects] = useState<SubjectSummary[]>();
  const [context, setContext] = useState<SubjectContext>({
    current_subject_id: null,
    version: 0,
  });
  const [types, setTypes] = useState<SubjectType[]>([]);
  const [selectedType, setSelectedType] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [subjectData, typeData] = await Promise.all([getSubjects(), getSubjectTypes()]);
    setSubjects(subjectData.subjects);
    setContext(subjectData.context);
    setTypes(typeData);
  }, []);

  useEffect(() => {
    let current = true;
    const loadInitial = async () => {
      try {
        const [subjectData, typeData] = await Promise.all([getSubjects(), getSubjectTypes()]);
        if (!current) return;
        setSubjects(subjectData.subjects);
        setContext(subjectData.context);
        setTypes(typeData);
      } catch (reason) {
        if (current) setError(userMessage(reason));
      }
    };

    void loadInitial();

    return () => {
      current = false;
    };
  }, []);

  const execute = async (operation: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await operation();
      await load();
      setError("");
      setNotice(message);
    } catch (reason) {
      setNotice("");
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const selected = types.find((item) => item.id === selectedType);

  if (subjects === undefined && !error) {
    return <Spin fullscreen description="\u6b63\u5728\u52a0\u8f7d\u4e3b\u4f53" />;
  }

  return (
    <main className="page-shell">
      <Space wrap align="baseline">
        <Typography.Title>{"\u6211\u7684\u4e3b\u4f53"}</Typography.Title>
        <Button href="/assistant" type="primary">
          显问 AI 助手
        </Button>
      </Space>
      <Typography.Paragraph type="secondary">
        创建后即可完善并保存企业资料；启用状态仅用于管理当前套餐的主体名额。
      </Typography.Paragraph>
      {error && (
        <Alert type="error" showIcon message={error} closable onClose={() => setError("")} />
      )}
      {notice && (
        <Alert type="success" showIcon message={notice} closable onClose={() => setNotice("")} />
      )}
      <Card title="创建企业资料" style={{ marginBottom: 20 }}>
        <Space wrap>
          <Select
            aria-label={"\u4e3b\u4f53\u7c7b\u578b"}
            value={selectedType || undefined}
            placeholder={"\u9009\u62e9\u4e3b\u4f53\u7c7b\u578b"}
            onChange={setSelectedType}
            style={{ minWidth: 240 }}
            options={types.map((item) => ({
              value: item.id,
              label: item.name,
            }))}
          />
          <Button
            type="primary"
            loading={busy}
            disabled={!selected}
            onClick={() => {
              if (!selected) return;
              void execute(
                () => createSubject(selected.id, selected.schema_version),
                "企业资料已创建",
              );
            }}
          >
            创建主体
          </Button>
        </Space>
      </Card>
      <Table
        rowKey="id"
        dataSource={subjects ?? []}
        pagination={false}
        locale={{ emptyText: "暂无企业资料" }}
        columns={[
          {
            title: "\u4e3b\u4f53",
            render: (_, item) => (
              <Space>
                <Link href={`/subjects/${item.id}`}>{item.subject_type.name}</Link>
                {item.is_current && <Tag color="blue">{"\u5f53\u524d"}</Tag>}
              </Space>
            ),
          },
          {
            title: "\u72b6\u6001",
            render: (_, item) => <Tag>{statusLabels[item.status]}</Tag>,
          },
          { title: "\u66f4\u65b0\u65f6\u95f4", dataIndex: "updated_at" },
          {
            title: "\u64cd\u4f5c",
            render: (_, item) => (
              <Space wrap>
                <Link href={`/subjects/${item.id}`}>{"\u7f16\u8f91"}</Link>
                {!item.is_current && item.status !== "archived" && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void execute(
                        () => setCurrentSubject(item.id, context.version),
                        "\u5f53\u524d\u4e3b\u4f53\u5df2\u66f4\u65b0",
                      )
                    }
                  >
                    {"\u8bbe\u4e3a\u5f53\u524d"}
                  </Button>
                )}
                {item.status !== "active" && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void execute(() => activateSubject(item), "\u4e3b\u4f53\u5df2\u6fc0\u6d3b")
                    }
                  >
                    {"\u6fc0\u6d3b"}
                  </Button>
                )}
                {item.status !== "archived" && (
                  <Button
                    danger
                    disabled={busy}
                    onClick={() =>
                      void execute(() => archiveSubject(item), "\u4e3b\u4f53\u5df2\u5f52\u6863")
                    }
                  >
                    {"\u5f52\u6863"}
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
    </main>
  );
}
