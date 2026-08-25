"use client";

import { Alert, Button, Card, Input, Popconfirm, Select, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useSubjectSwitchGuard } from "@/components/subject-workspace-context";
import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  confirmDistillation,
  createDistillation,
  distillationJobStatusLabel,
  getDistillationDraft,
  getDistillationJob,
  keywordJobErrorMessage,
  saveDistillationDraft,
  type DistillationAction,
  type DistillationDraftItem,
  type DistillationDraftState,
  type DistillationJob,
} from "@/lib/keywords-client";

const actionOptions = [
  { value: "keep", label: "保留" },
  { value: "merge", label: "合并" },
  { value: "delete", label: "删除建议" },
  { value: "low_value", label: "低价值" },
];

const actionLabels: Record<DistillationAction, string> = {
  keep: "保留",
  merge: "合并",
  delete: "删除建议",
  low_value: "低价值",
};

type Props = Readonly<{
  subjectId: string;
  keywordDirty: boolean;
  onDirtyChange?: (dirty: boolean) => void;
}>;

function editableItem(item: DistillationDraftItem): DistillationDraftItem {
  return { ...item };
}

export default function DistillationPanel({ subjectId, keywordDirty, onDirtyChange }: Props) {
  const [draft, setDraft] = useState<DistillationDraftState>();
  const [items, setItems] = useState<DistillationDraftItem[]>([]);
  const [job, setJob] = useState<DistillationJob>();
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmRegeneration, setConfirmRegeneration] = useState(false);
  const active = Boolean(job && ["queued", "running", "retry_wait"].includes(job.status));

  const reload = useCallback(async () => {
    const next = await getDistillationDraft(subjectId);
    setDraft(next);
    setItems(next.items.map(editableItem));
    setDirty(false);
  }, [subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(
      () => void reload().catch((reason) => setError(userMessage(reason))),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [reload]);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    if (!active || !job) return;
    const timer = window.setTimeout(() => {
      void getDistillationJob(job.id)
        .then(async (next) => {
          setJob(next);
          if (next.status === "succeeded") {
            await reload();
            setNotice("蒸馏建议已生成，请调整并明确确认");
            setError("");
          } else if (["failed", "conflict", "superseded"].includes(next.status)) {
            setError(keywordJobErrorMessage(next.stable_error_code, "蒸馏失败，请重试"));
            setNotice("");
          }
        })
        .catch((reason) => setError(userMessage(reason)));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [active, job, reload]);

  const mergeGroups = useMemo(
    () =>
      Array.from(new Set(items.map((item) => item.merge_group_key).filter(Boolean))).map(
        (value, index) => ({ value: value as string, label: `合并组 ${index + 1}` }),
      ),
    [items],
  );

  const change = (sourceId: string, patch: Partial<DistillationDraftItem>) => {
    setItems((current) =>
      current.map((item) => (item.source_keyword.id === sourceId ? { ...item, ...patch } : item)),
    );
    setDirty(true);
  };

  const setAction = (item: DistillationDraftItem, action: DistillationAction) => {
    change(
      item.source_keyword.id,
      action === "merge"
        ? {
            action,
            canonical_keyword_id: item.canonical_keyword_id ?? item.source_keyword.id,
            merge_group_key: item.merge_group_key ?? crypto.randomUUID(),
          }
        : { action, canonical_keyword_id: null, merge_group_key: null },
    );
  };

  const splitMergeGroup = (groupKey: string) => {
    setItems((current) =>
      current.map((item) =>
        item.merge_group_key === groupKey
          ? {
              ...item,
              action: "keep",
              canonical_keyword_id: null,
              merge_group_key: null,
            }
          : item,
      ),
    );
    setDirty(true);
    setError("");
    setNotice("合并组已拆分，请保存蒸馏调整");
  };

  const start = async (regenerate: boolean) => {
    if (keywordDirty || dirty) {
      setError("请先保存或放弃本地未保存修改，再启动蒸馏");
      return;
    }
    if (!draft?.current_keyword_set_version) {
      setError("请先添加或生成关键词，再启动蒸馏");
      return;
    }
    setBusy(true);
    try {
      const next = await createDistillation(
        subjectId,
        {
          keywordSetVersionId: draft.current_keyword_set_version.id,
          expectedWorkspaceVersion: draft.version,
          regenerate,
        },
        crypto.randomUUID(),
      );
      setJob(next);
      setConfirmRegeneration(false);
      setError("");
      setNotice(
        next.billing.billing_mode === "free_initial"
          ? "首次免费蒸馏任务已提交"
          : "再次蒸馏任务已提交，额度已冻结",
      );
    } catch (reason) {
      if (
        reason instanceof AuthApiError &&
        reason.code === "DISTILLATION_REGENERATION_CONFIRMATION_REQUIRED"
      ) {
        setConfirmRegeneration(true);
        setError("");
        setNotice("该主体已有成功蒸馏，请确认消耗一次再蒸馏额度");
      } else {
        setError(userMessage(reason));
        setNotice("");
      }
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!draft) return true;
    setBusy(true);
    try {
      const next = await saveDistillationDraft(subjectId, draft.version, items);
      setDraft(next);
      setItems(next.items.map(editableItem));
      setDirty(false);
      setError("");
      setNotice("蒸馏调整已保存");
      return true;
    } catch (reason) {
      setError(userMessage(reason));
      setNotice("");
      return false;
    } finally {
      setBusy(false);
    }
  };

  useSubjectSwitchGuard(`keyword-distillation:${subjectId}`, dirty, save);

  const confirm = async () => {
    if (!draft) return;
    if (dirty) {
      setError("请先保存蒸馏调整，再确认结果");
      return;
    }
    setBusy(true);
    try {
      await confirmDistillation(subjectId, draft.version);
      await reload();
      setError("");
      setNotice(`蒸馏结果已确认，关键词资产已更新`);
    } catch (reason) {
      setError(userMessage(reason));
      setNotice("");
    } finally {
      setBusy(false);
    }
  };

  const disabled = !draft?.can_write || busy || active;

  return (
    <Card title="关键词蒸馏" style={{ marginTop: 20 }}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        {error && <Alert type="error" showIcon message={error} />}
        {notice && <Alert type="success" showIcon message={notice} />}
        <Typography.Text type="secondary">
          蒸馏只读取当前主体的待蒸馏关键词；确认后才会进入关键词资产。
        </Typography.Text>
        <Space wrap>
          {draft?.current_keyword_set_version ? <Tag color="blue">待蒸馏关键词已就绪</Tag> : null}
          {draft?.current_distillation_version_no ? <Tag color="green">已有关键词资产</Tag> : null}
          {dirty && <Tag color="orange">有未保存蒸馏调整</Tag>}
          {job ? (
            <Tag color={job.status === "succeeded" ? "green" : "blue"}>
              {distillationJobStatusLabel[job.status]}
            </Tag>
          ) : null}
        </Space>
        <Space wrap>
          <Button
            type="primary"
            disabled={disabled || dirty || keywordDirty || !draft?.current_keyword_set_version}
            loading={busy}
            onClick={() => void start(false)}
          >
            AI 蒸馏关键词
          </Button>
          {confirmRegeneration && (
            <Popconfirm
              title="确认消耗一次再蒸馏额度？"
              description="蒸馏成功后扣除；失败、冲突或过期结果会释放。"
              okText="确认再蒸馏"
              cancelText="取消"
              onConfirm={() => void start(true)}
            >
              <Button danger disabled={disabled || dirty || keywordDirty}>
                确认消耗额度并再蒸馏
              </Button>
            </Popconfirm>
          )}
        </Space>

        {mergeGroups.length ? (
          <Card size="small" title="合并组">
            <Space wrap>
              {mergeGroups.map((group) => (
                <Popconfirm
                  key={group.value}
                  title={`拆分${group.label}？`}
                  description="该组内关键词将全部恢复为保留状态。"
                  okText="确认拆分"
                  cancelText="取消"
                  onConfirm={() => splitMergeGroup(group.value)}
                >
                  <Button disabled={disabled}>拆分{group.label}</Button>
                </Popconfirm>
              ))}
            </Space>
          </Card>
        ) : null}

        {items.map((item, index) => {
          const compatible = items.filter(
            (candidate) =>
              candidate.source_keyword.is_regional === item.source_keyword.is_regional &&
              (candidate.source_keyword.region_text ?? "") ===
                (item.source_keyword.region_text ?? ""),
          );
          return (
            <Card key={item.source_keyword.id} size="small">
              <Space direction="vertical" style={{ width: "100%" }}>
                <Space wrap>
                  <Typography.Text strong>{item.source_keyword.text}</Typography.Text>
                  {item.source_keyword.region_text && <Tag>{item.source_keyword.region_text}</Tag>}
                  <Tag>AI：{actionLabels[item.ai_action]}</Tag>
                  {item.user_overridden && <Tag color="orange">已人工调整</Tag>}
                </Space>
                <Typography.Text type="secondary">{item.ai_reason}</Typography.Text>
                <Space wrap>
                  <Select
                    aria-label={`蒸馏动作-${index + 1}`}
                    value={item.action}
                    options={actionOptions}
                    disabled={disabled}
                    style={{ width: 140 }}
                    onChange={(value: DistillationAction) => setAction(item, value)}
                  />
                  {item.action === "merge" && (
                    <>
                      <Select
                        aria-label={`合并代表词-${index + 1}`}
                        value={item.canonical_keyword_id ?? undefined}
                        disabled={disabled}
                        style={{ width: 220 }}
                        options={compatible.map((candidate) => ({
                          value: candidate.source_keyword.id,
                          label: candidate.source_keyword.text,
                        }))}
                        onChange={(value: string) =>
                          change(item.source_keyword.id, { canonical_keyword_id: value })
                        }
                      />
                      <Select
                        aria-label={`合并组-${index + 1}`}
                        value={item.merge_group_key ?? undefined}
                        disabled={disabled}
                        style={{ width: 160 }}
                        options={mergeGroups}
                        onChange={(value: string) =>
                          change(item.source_keyword.id, { merge_group_key: value })
                        }
                      />
                    </>
                  )}
                  <Input
                    aria-label={`人工说明-${index + 1}`}
                    value={item.user_reason}
                    disabled={disabled}
                    placeholder="人工调整说明（可选）"
                    style={{ width: 300 }}
                    onChange={(event) =>
                      change(item.source_keyword.id, { user_reason: event.target.value })
                    }
                  />
                </Space>
              </Space>
            </Card>
          );
        })}

        {items.length > 0 && (
          <Space>
            <Button type="primary" disabled={disabled || !dirty} onClick={() => void save()}>
              保存蒸馏调整
            </Button>
            <Popconfirm
              title="确认蒸馏结果"
              description="确认后，保留和合并后的关键词会进入关键词资产。"
              okText="确认结果"
              cancelText="取消"
              onConfirm={() => void confirm()}
            >
              <Button disabled={disabled || dirty}>确认蒸馏结果</Button>
            </Popconfirm>
          </Space>
        )}
      </Space>
    </Card>
  );
}
