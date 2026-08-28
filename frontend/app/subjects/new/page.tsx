"use client";

import { Alert, Button, Card, Select, Space, Spin, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  createSubject,
  getSubjectTypes,
  notifySubjectContextUpdated,
  type SubjectType,
} from "@/lib/subjects-client";

const { Paragraph, Text, Title } = Typography;

export default function NewSubjectPage() {
  const [types, setTypes] = useState<SubjectType[]>();
  const [selectedTypeId, setSelectedTypeId] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void getSubjectTypes()
      .then((rows) => {
        if (!active) return;
        setTypes(rows);
        setSelectedTypeId((current) => current || rows[0]?.id || "");
      })
      .catch((reason) => {
        if (active) setError(userMessage(reason));
      });
    return () => {
      active = false;
    };
  }, []);

  const selectedType = useMemo(
    () => types?.find((item) => item.id === selectedTypeId) ?? null,
    [selectedTypeId, types],
  );

  const submit = async () => {
    if (!selectedType || creating) return;
    setCreating(true);
    setError("");
    try {
      const subject = await createSubject(selectedType.id, selectedType.schema_version, {});
      notifySubjectContextUpdated();
      window.location.assign(`/subjects/${subject.id}`);
    } catch (reason) {
      setError(userMessage(reason));
      setCreating(false);
    }
  };

  if (types === undefined && !error) {
    return <Spin fullscreen description="正在加载主体类型" />;
  }

  return (
    <main className="page-shell">
      <Title level={2}>创建主体</Title>
      <Paragraph type="secondary">选择主体类型后，进入主体资料填写。</Paragraph>

      {error && <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} />}

      <Card title="主体类型" style={{ maxWidth: 720 }}>
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          {types?.length ? (
            <>
              <Select
                aria-label="主体类型"
                value={selectedTypeId || undefined}
                placeholder="请选择主体类型"
                style={{ width: "100%" }}
                options={types.map((item) => ({ value: item.id, label: item.name }))}
                onChange={setSelectedTypeId}
              />
              {selectedType?.description && (
                <Text type="secondary">{selectedType.description}</Text>
              )}
              <Space wrap>
                <Button href="/subjects">返回主体管理</Button>
                <Button
                  type="primary"
                  loading={creating}
                  disabled={!selectedType}
                  onClick={() => void submit()}
                >
                  创建并填写资料
                </Button>
              </Space>
            </>
          ) : (
            <Alert type="warning" showIcon title="当前没有可选的主体类型，请联系管理员。" />
          )}
        </Space>
      </Card>
    </main>
  );
}
