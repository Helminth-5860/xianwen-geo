"use client";

import { PlusOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  createSubjectCompetitor,
  getSubjectCompetitors,
  removeSubjectCompetitor,
  updateSubjectCompetitor,
  type Competitor,
  type CompetitorList,
} from "@/lib/competitors-client";

import styles from "./competitor-management.module.css";

type CompetitorFormValues = Readonly<{
  name: string;
  website?: string;
}>;

type CompetitorManagementWorkspaceProps = Readonly<{
  subjectId: string;
}>;

function wasAborted(reason: unknown) {
  return reason instanceof DOMException && reason.name === "AbortError";
}

function externalWebsite(value: string) {
  return /^https?:\/\//i.test(value) ? value : `https://${value}`;
}

export function CompetitorManagementWorkspace({ subjectId }: CompetitorManagementWorkspaceProps) {
  const { currentSubject, subjects } = useSubjectWorkspace();
  const [form] = Form.useForm<CompetitorFormValues>();
  const [data, setData] = useState<CompetitorList | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [removingId, setRemovingId] = useState("");
  const [editing, setEditing] = useState<Competitor | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const requestSequence = useRef(0);

  const routeSubject = subjects.find((item) => item.id === subjectId);
  const fallbackSubjectName =
    routeSubject?.official_name ||
    routeSubject?.subject_type.name ||
    (currentSubject?.id === subjectId
      ? currentSubject.official_name || currentSubject.subject_type.name
      : "当前主体");

  const load = useCallback(async (targetSubjectId: string, signal?: AbortSignal) => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError("");
    try {
      const result = await getSubjectCompetitors(targetSubjectId, signal);
      if (sequence !== requestSequence.current || result.subject.id !== targetSubjectId) return;
      setData(result);
    } catch (reason: unknown) {
      if (sequence === requestSequence.current && !wasAborted(reason)) {
        setError(userMessage(reason));
      }
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setData(null);
      setError("");
      setNotice("");
      setDialogOpen(false);
      setEditing(null);
      form.resetFields();
      void load(subjectId, controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      requestSequence.current += 1;
    };
  }, [form, load, subjectId]);

  const competitors = useMemo(
    () => [...(data?.items ?? [])].sort((left, right) => left.position - right.position),
    [data?.items],
  );
  const maximum = Math.min(3, Math.max(1, data?.max_count ?? 3));
  const isFull = (data?.count ?? competitors.length) >= maximum;
  const subjectName = data?.subject.name || fallbackSubjectName;
  const initialLoadFailed = Boolean(error) && !data && !loading;

  const openAdd = () => {
    setEditing(null);
    setError("");
    form.setFieldsValue({ name: "", website: "" });
    setDialogOpen(true);
  };

  const openEdit = (competitor: Competitor) => {
    setEditing(competitor);
    setError("");
    form.setFieldsValue({ name: competitor.name, website: competitor.website });
    setDialogOpen(true);
  };

  const save = async (values: CompetitorFormValues) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const input = {
        name: values.name.trim(),
        website: values.website?.trim() ?? "",
      };
      if (editing) {
        await updateSubjectCompetitor(subjectId, editing, input);
        setNotice("竞品信息已更新。");
      } else {
        await createSubjectCompetitor(subjectId, input);
        setNotice("竞品已添加。");
      }
      setDialogOpen(false);
      setEditing(null);
      form.resetFields();
      await load(subjectId);
    } catch (reason: unknown) {
      setError(userMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  const removeCompetitor = async (competitor: Competitor) => {
    setRemovingId(competitor.id);
    setError("");
    setNotice("");
    try {
      await removeSubjectCompetitor(subjectId, competitor.id);
      setNotice("竞品已移除。");
      await load(subjectId);
    } catch (reason: unknown) {
      setError(userMessage(reason));
    } finally {
      setRemovingId("");
    }
  };

  return (
    <main className="page-shell subject-profile-page" data-subject-id={subjectId}>
      <Link href={`/subjects/${subjectId}`}>返回主体档案</Link>
      <header className="subject-profile-header">
        <div>
          <Typography.Text className="subject-profile-eyebrow">主体档案</Typography.Text>
          <Typography.Title>竞品管理</Typography.Title>
          <Typography.Paragraph type="secondary">
            为当前主体设置最多 3 家核心竞品，后续用于竞品对比分析。
          </Typography.Paragraph>
        </div>
        {data && !isFull && !loading ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
            添加竞品
          </Button>
        ) : null}
      </header>

      {error && !initialLoadFailed ? <Alert type="error" showIcon message={error} /> : null}
      {notice ? <Alert type="success" showIcon message={notice} /> : null}

      {data ? (
        <Card>
          <div className={styles.summary}>
            <div>
              <Typography.Text type="secondary">当前主体</Typography.Text>
              <Typography.Title level={3} className={styles.summaryName}>
                {subjectName}
              </Typography.Title>
            </div>
            <Tag color={isFull ? "green" : "blue"}>
              已设置：{data.count} / {maximum}
            </Tag>
          </div>
        </Card>
      ) : null}

      {loading && !data ? (
        <Card>
          <Skeleton active paragraph={{ rows: 5 }} />
        </Card>
      ) : initialLoadFailed ? (
        <Card>
          <Empty description="竞品信息暂时无法读取">
            <Button type="primary" onClick={() => void load(subjectId)}>
              重新加载
            </Button>
          </Empty>
        </Card>
      ) : competitors.length === 0 ? (
        <Card>
          <Empty description="暂无竞品">
            <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
              添加竞品
            </Button>
          </Empty>
        </Card>
      ) : (
        <section className={styles.slotGrid} aria-label="核心竞品列表">
          {Array.from({ length: maximum }, (_, index) => {
            const competitor = competitors[index];
            return (
              <Card
                key={competitor?.id ?? `empty-${index}`}
                title={`竞品 ${String(index + 1).padStart(2, "0")}`}
                className={styles.slotCard}
              >
                {competitor ? (
                  <div className={styles.slotBody}>
                    <Space orientation="vertical" size={8}>
                      <Typography.Title level={4} style={{ margin: 0 }}>
                        {competitor.name}
                      </Typography.Title>
                      {competitor.website ? (
                        <Typography.Link
                          className={styles.website}
                          href={externalWebsite(competitor.website)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {competitor.domain || competitor.website}
                        </Typography.Link>
                      ) : (
                        <Typography.Text type="secondary">未填写官方网站</Typography.Text>
                      )}
                    </Space>
                    <Space wrap>
                      <Button onClick={() => openEdit(competitor)}>编辑</Button>
                      <Popconfirm
                        title="确认移除这家竞品？"
                        description="移除后会释放一个竞品位置，之后可以重新添加。"
                        okText="确认移除"
                        cancelText="取消"
                        onConfirm={() => void removeCompetitor(competitor)}
                      >
                        <Button danger loading={removingId === competitor.id}>
                          移除
                        </Button>
                      </Popconfirm>
                    </Space>
                  </div>
                ) : (
                  <div className={styles.emptySlot}>
                    <Typography.Text type="secondary">尚未设置</Typography.Text>
                    <Button icon={<PlusOutlined />} onClick={openAdd}>
                      添加竞品
                    </Button>
                  </div>
                )}
              </Card>
            );
          })}
        </section>
      )}

      <Modal
        title={editing ? "编辑竞品" : "添加竞品"}
        open={dialogOpen}
        okText={editing ? "保存修改" : "确认添加"}
        cancelText="取消"
        confirmLoading={saving}
        forceRender
        onOk={() => form.submit()}
        onCancel={() => {
          if (saving) return;
          setDialogOpen(false);
          setEditing(null);
          form.resetFields();
        }}
      >
        <Form form={form} layout="vertical" onFinish={(values) => void save(values)}>
          <Form.Item
            label="竞品名称"
            name="name"
            rules={[
              { required: true, whitespace: true, message: "请输入竞品名称" },
              { max: 200, message: "竞品名称不能超过 200 个字符" },
            ]}
          >
            <Input placeholder="请输入竞品名称" autoComplete="off" />
          </Form.Item>
          <Form.Item
            label="官方网站（选填）"
            name="website"
            rules={[{ max: 500, message: "官方网站不能超过 500 个字符" }]}
          >
            <Input placeholder="请输入竞品官方网站" inputMode="url" autoComplete="url" />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
