"use client";

import {
  Alert,
  Button,
  Card,
  Input,
  Pagination,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
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
  type DistillationSourceKeyword,
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

const DISTILLATION_PAGE_SIZE = 20;

type Props = Readonly<{
  subjectId: string;
  keywordDirty: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  onConfirmed?: () => void | Promise<void>;
}>;

function editableItem(item: DistillationDraftItem): DistillationDraftItem {
  return { ...item };
}

export default function DistillationPanel({
  subjectId,
  keywordDirty,
  onDirtyChange,
  onConfirmed,
}: Props) {
  const [draft, setDraft] = useState<DistillationDraftState>();
  const [pendingItems, setPendingItems] = useState<DistillationSourceKeyword[]>([]);
  const [items, setItems] = useState<DistillationDraftItem[]>([]);
  const [job, setJob] = useState<DistillationJob>();
  const [pendingPage, setPendingPage] = useState(1);
  const [resultPage, setResultPage] = useState(1);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmRegeneration, setConfirmRegeneration] = useState(false);
  const active = Boolean(job && ["queued", "running", "retry_wait"].includes(job.status));

  const reload = useCallback(async () => {
    const next = await getDistillationDraft(subjectId);
    setDraft(next);
    setPendingItems(next.pending_items);
    setItems(next.has_unconfirmed_result ? next.items.map(editableItem) : []);
    setPendingPage(1);
    setResultPage(1);
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
            setError(
              keywordJobErrorMessage(next.stable_error_code, "关键词蒸馏未完成，请重新尝试。"),
            );
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
    if (!draft?.current_keyword_set_version || draft.pending_item_count === 0) {
      setError("当前没有待蒸馏关键词，请先添加或生成新关键词");
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
          ? "已开始首次免费蒸馏"
          : "已开始再次蒸馏，并暂时预留额度",
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
      await onConfirmed?.();
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
  const pendingPageCount = Math.max(1, Math.ceil(pendingItems.length / DISTILLATION_PAGE_SIZE));
  const effectivePendingPage = Math.min(pendingPage, pendingPageCount);
  const pendingPageStart = (effectivePendingPage - 1) * DISTILLATION_PAGE_SIZE;
  const visiblePendingItems = pendingItems.slice(
    pendingPageStart,
    pendingPageStart + DISTILLATION_PAGE_SIZE,
  );
  const resultPageCount = Math.max(1, Math.ceil(items.length / DISTILLATION_PAGE_SIZE));
  const effectiveResultPage = Math.min(resultPage, resultPageCount);
  const resultPageStart = (effectiveResultPage - 1) * DISTILLATION_PAGE_SIZE;
  const visibleItems = items.slice(resultPageStart, resultPageStart + DISTILLATION_PAGE_SIZE);

  return (
    <Card title="关键词蒸馏" style={{ marginTop: 20 }}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        {error && <Alert type="error" showIcon message={error} />}
        {notice && <Alert type="success" showIcon message={notice} />}
        <Typography.Text type="secondary">
          蒸馏只读取当前主体的待蒸馏关键词；确认后才会进入关键词资产。
        </Typography.Text>
        <Space wrap>
          <Tag color={draft?.pending_item_count ? "blue" : "default"}>
            待蒸馏关键词 {draft?.pending_item_count ?? 0}
          </Tag>
          {draft?.current_distillation_version_no ? <Tag color="green">已有关键词资产</Tag> : null}
          {dirty && <Tag color="orange">有未保存蒸馏调整</Tag>}
          {job ? (
            <Tag color={job.status === "succeeded" ? "green" : "blue"}>
              {job.status === "superseded"
                ? "已有更新结果"
                : distillationJobStatusLabel[job.status]}
            </Tag>
          ) : null}
        </Space>
        <Space wrap>
          <Button
            type={draft?.has_unconfirmed_result ? "default" : "primary"}
            disabled={
              disabled ||
              dirty ||
              keywordDirty ||
              !draft?.current_keyword_set_version ||
              draft.pending_item_count === 0 ||
              draft.has_unconfirmed_result
            }
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
          {draft?.has_unconfirmed_result && items.length > 0 ? (
            <>
              <Button disabled={disabled || !dirty} onClick={() => void save()}>
                保存蒸馏调整
              </Button>
              <Popconfirm
                title="确认蒸馏结果"
                description="确认后，保留和合并后的关键词会进入关键词资产。"
                okText="确认结果"
                cancelText="取消"
                onConfirm={() => void confirm()}
              >
                <Button type="primary" disabled={disabled || dirty}>
                  确认蒸馏结果
                </Button>
              </Popconfirm>
            </>
          ) : null}
        </Space>

        {pendingItems.length > 0 && !draft?.has_unconfirmed_result ? (
          <Card size="small" title="待蒸馏关键词">
            <Space direction="vertical" size="small" style={{ width: "100%" }}>
              {visiblePendingItems.map((item) => (
                <Card key={item.id} size="small">
                  <Space wrap>
                    <Typography.Text strong>{item.text}</Typography.Text>
                    <Tag>{item.structure_type === "long_tail" ? "长尾关键词" : "短关键词"}</Tag>
                    {item.region_text ? <Tag color="cyan">{item.region_text}</Tag> : null}
                  </Space>
                </Card>
              ))}
              {pendingItems.length > DISTILLATION_PAGE_SIZE ? (
                <Pagination
                  aria-label="待蒸馏关键词分页"
                  current={effectivePendingPage}
                  pageSize={DISTILLATION_PAGE_SIZE}
                  total={pendingItems.length}
                  showSizeChanger={false}
                  showTotal={(total, range) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`}
                  onChange={setPendingPage}
                />
              ) : null}
            </Space>
          </Card>
        ) : !draft?.has_unconfirmed_result ? (
          <Space wrap align="center">
            <Typography.Text type="secondary">
              当前没有待蒸馏关键词，请先添加或生成关键词。
            </Typography.Text>
            <Button href={`/subjects/${subjectId}/keywords/custom`}>去添加关键词</Button>
          </Space>
        ) : null}

        {draft?.has_unconfirmed_result && mergeGroups.length ? (
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

        {visibleItems.map((item, index) => {
          const itemNumber = resultPageStart + index + 1;
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
                    aria-label={`蒸馏动作-${itemNumber}`}
                    value={item.action}
                    options={actionOptions}
                    disabled={disabled}
                    style={{ width: 140 }}
                    onChange={(value: DistillationAction) => setAction(item, value)}
                  />
                  {item.action === "merge" && (
                    <>
                      <Select
                        aria-label={`合并代表词-${itemNumber}`}
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
                        aria-label={`合并组-${itemNumber}`}
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
                    aria-label={`人工说明-${itemNumber}`}
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

        {items.length > DISTILLATION_PAGE_SIZE ? (
          <Pagination
            aria-label="蒸馏结果分页"
            current={effectiveResultPage}
            pageSize={DISTILLATION_PAGE_SIZE}
            total={items.length}
            showSizeChanger={false}
            showTotal={(total, range) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`}
            onChange={setResultPage}
          />
        ) : null}
      </Space>
    </Card>
  );
}
