"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Input,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { useSubjectSwitchGuard } from "@/components/subject-workspace-context";
import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  confirmQuestionBank,
  createQuestionGeneration,
  getQuestionBankDraft,
  getQuestionBankVersions,
  getQuestionGenerationJob,
  questionGenerationErrorMessage,
  saveQuestionBankDraft,
  type QuestionBankDraft,
  type QuestionBankVersion,
  type QuestionDraftItem,
  type QuestionGenerationJob,
  type QuestionPriority,
  type QuestionType,
} from "@/lib/question-bank-client";

const priorityOptions = [
  { value: "high", label: "高" },
  { value: "medium", label: "中" },
  { value: "low", label: "低" },
];
const typeOptions = [
  { value: "natural", label: "自然探索型" },
  { value: "brand_directed", label: "品牌指向型" },
];

type Props = Readonly<{
  subjectId: string;
  upstreamDirty: boolean;
}>;

export default function QuestionBankPanel({ subjectId, upstreamDirty }: Props) {
  const [draft, setDraft] = useState<QuestionBankDraft>();
  const [items, setItems] = useState<QuestionDraftItem[]>([]);
  const [versions, setVersions] = useState<QuestionBankVersion[]>([]);
  const [job, setJob] = useState<QuestionGenerationJob>();
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmRegeneration, setConfirmRegeneration] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const active = Boolean(job && ["queued", "running", "retry_wait"].includes(job.status));

  const reload = useCallback(async () => {
    const [next, history] = await Promise.all([
      getQuestionBankDraft(subjectId),
      getQuestionBankVersions(subjectId),
    ]);
    setDraft(next);
    setItems(next.items.map((item) => ({ ...item })));
    setVersions(history.versions);
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
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    if (!active || !job) return;
    const timer = window.setTimeout(() => {
      void getQuestionGenerationJob(job.id)
        .then(async (next) => {
          setJob(next);
          if (next.status === "succeeded") {
            await reload();
            setNotice("问题建议已写入草稿，请审核并确认正式版本");
            setError("");
          } else if (["failed", "conflict", "superseded"].includes(next.status)) {
            setError(questionGenerationErrorMessage(next.stable_error_code));
            setNotice("");
          }
        })
        .catch((reason) => setError(userMessage(reason)));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [active, job, reload]);

  const change = (index: number, patch: Partial<QuestionDraftItem>) => {
    setItems((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)),
    );
    setDirty(true);
  };

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    setItems((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((item, sortOrder) => ({ ...item, sort_order: sortOrder }));
    });
    setDirty(true);
  };

  const generate = async (regenerate: boolean) => {
    if (!draft?.current_distillation_set) {
      setError("请先确认蒸馏正式版本");
      return;
    }
    if (dirty || upstreamDirty) {
      setError("请先保存或确认上游未保存修改，再生成问题库");
      return;
    }
    setBusy(true);
    try {
      const next = await createQuestionGeneration(
        subjectId,
        {
          distillationSetId: draft.current_distillation_set.id,
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
          ? "首次免费问题生成任务已提交"
          : "问题库重生成任务已提交，额度已冻结",
      );
    } catch (reason) {
      if (
        reason instanceof AuthApiError &&
        reason.code === "QUESTION_GENERATION_REGENERATION_CONFIRMATION_REQUIRED"
      ) {
        setConfirmRegeneration(true);
        setError("");
        setNotice("该主体已有成功问题生成，请确认消耗一次重生成额度");
      } else if (reason instanceof AuthApiError && reason.code.startsWith("QUESTION_GENERATION_")) {
        setError(questionGenerationErrorMessage(reason.code));
        setNotice("");
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
      const next = await saveQuestionBankDraft(subjectId, draft.version, items);
      setDraft(next);
      setItems(next.items.map((item) => ({ ...item })));
      setDirty(false);
      setError("");
      setNotice("问题库草稿已保存，人工编辑未消耗 AI 次数");
      return true;
    } catch (reason) {
      setError(userMessage(reason));
      setNotice("");
      return false;
    } finally {
      setBusy(false);
    }
  };

  useSubjectSwitchGuard(`question-bank:${subjectId}`, dirty, save);

  const confirm = async () => {
    if (!draft) return;
    if (dirty) {
      setError("请先保存问题库草稿，再确认正式版本");
      return;
    }
    setBusy(true);
    try {
      const result = await confirmQuestionBank(subjectId, draft.version);
      await reload();
      setError("");
      setNotice(`问题库正式版本 v${result.version.version_no} 已确认`);
    } catch (reason) {
      setError(userMessage(reason));
      setNotice("");
    } finally {
      setBusy(false);
    }
  };

  const disabled = !draft?.can_write || busy || active;
  const categoryOptions = draft?.catalog.categories.map((row) => ({
    value: row.id,
    label: row.name,
  }));
  const tagOptions = draft?.catalog.tags.map((row) => ({ value: row.id, label: row.name }));

  return (
    <Card title="问题库生成与编辑" style={{ marginTop: 20 }}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        {error && <Alert type="error" showIcon message={error} />}
        {notice && <Alert type="success" showIcon message={notice} />}
        <Typography.Text type="secondary">
          仅使用已确认的蒸馏版本生成；AI 结果先进入草稿，确认后才形成不可修改的正式版本。
        </Typography.Text>
        <Space wrap>
          {draft?.current_distillation_set && (
            <Tag color="blue">蒸馏正式版本 v{draft.current_distillation_set.version_no}</Tag>
          )}
          {draft?.question_limit && <Tag>问题上限 {draft.question_limit}</Tag>}
          {draft?.current_question_bank_version_no && (
            <Tag color="green">问题库正式版本 v{draft.current_question_bank_version_no}</Tag>
          )}
          {dirty && <Tag color="orange">有未保存问题修改</Tag>}
          {job && <Tag color={job.status === "succeeded" ? "green" : "blue"}>{job.status}</Tag>}
        </Space>
        <Space wrap>
          <Button
            type="primary"
            disabled={disabled || dirty || upstreamDirty || !draft?.current_distillation_set}
            loading={busy}
            onClick={() => void generate(false)}
          >
            AI 生成问题库
          </Button>
          {confirmRegeneration && (
            <Popconfirm
              title="确认消耗一次问题库重生成额度？"
              description="成功写入完整草稿后扣除；失败、冲突或过期会释放。"
              okText="确认重生成"
              cancelText="取消"
              onConfirm={() => void generate(true)}
            >
              <Button danger disabled={disabled || dirty || upstreamDirty}>
                确认消耗额度并重生成
              </Button>
            </Popconfirm>
          )}
        </Space>

        {items.map((item, index) => (
          <Card key={item.id || index} size="small">
            <Space direction="vertical" style={{ width: "100%" }}>
              <Input.TextArea
                aria-label={`问题文本-${index + 1}`}
                value={item.text}
                disabled={disabled}
                autoSize
                onChange={(event) => change(index, { text: event.target.value })}
              />
              {item.ai_reason && (
                <Typography.Text type="secondary">{item.ai_reason}</Typography.Text>
              )}
              <Space wrap>
                <Select
                  aria-label={`主分类-${index + 1}`}
                  value={item.primary_category.id}
                  options={categoryOptions}
                  disabled={disabled}
                  style={{ width: 180 }}
                  onChange={(value: string) => {
                    const category = draft?.catalog.categories.find((row) => row.id === value);
                    if (category) {
                      change(index, {
                        primary_category: {
                          id: category.id,
                          key: category.key,
                          name: category.name,
                        },
                      });
                    }
                  }}
                />
                <Select
                  mode="multiple"
                  aria-label={`辅助标签-${index + 1}`}
                  value={item.tag_ids}
                  options={tagOptions}
                  disabled={disabled}
                  style={{ minWidth: 200 }}
                  onChange={(value: string[]) => change(index, { tag_ids: value })}
                />
                <Select
                  aria-label={`问题优先级-${index + 1}`}
                  value={item.priority}
                  options={priorityOptions}
                  disabled={disabled}
                  style={{ width: 100 }}
                  onChange={(value: QuestionPriority) => change(index, { priority: value })}
                />
                <Select
                  aria-label={`问题类型-${index + 1}`}
                  value={item.question_type}
                  options={typeOptions}
                  disabled={disabled}
                  style={{ width: 150 }}
                  onChange={(value: QuestionType) => change(index, { question_type: value })}
                />
                <Checkbox
                  checked={item.participates_in_scoring}
                  disabled={disabled}
                  onChange={(event) =>
                    change(index, { participates_in_scoring: event.target.checked })
                  }
                >
                  参与检测
                </Checkbox>
                <Button disabled={disabled || index === 0} onClick={() => move(index, -1)}>
                  上移
                </Button>
                <Button
                  disabled={disabled || index === items.length - 1}
                  onClick={() => move(index, 1)}
                >
                  下移
                </Button>
                <Button
                  danger
                  disabled={disabled}
                  onClick={() => {
                    setItems((current) => current.filter((_, itemIndex) => itemIndex !== index));
                    setDirty(true);
                  }}
                >
                  删除
                </Button>
              </Space>
            </Space>
          </Card>
        ))}
        <Button
          disabled={
            disabled ||
            !draft?.catalog.categories.length ||
            Boolean(draft?.question_limit && items.length >= draft.question_limit)
          }
          onClick={() => {
            const category = draft?.catalog.categories[0];
            if (!category) return;
            setItems((current) => [
              ...current,
              {
                id: crypto.randomUUID(),
                text: "",
                primary_category: {
                  id: category.id,
                  key: category.key,
                  name: category.name,
                },
                tag_ids: [],
                keyword_ids: [],
                priority: "medium",
                question_type: "natural",
                participates_in_scoring: true,
                ai_reason: "",
                sort_order: current.length,
              },
            ]);
            setDirty(true);
          }}
        >
          <span>&#28155;&#21152;&#38382;&#39064;</span>
        </Button>
        {items.length > 0 && (
          <Space>
            <Button type="primary" disabled={disabled || !dirty} onClick={() => void save()}>
              保存问题草稿
            </Button>
            <Popconfirm
              title="确认问题库正式版本"
              description="确认后形成不可修改的历史版本，后续检测才能绑定该版本。"
              okText="确认版本"
              cancelText="取消"
              onConfirm={() => void confirm()}
            >
              <Button disabled={disabled || dirty}>确认问题库</Button>
            </Popconfirm>
          </Space>
        )}
        {versions.length > 0 && (
          <Typography.Text type="secondary">
            历史版本：
            {versions
              .map((version) => `v${version.version_no}（${version.item_count}题）`)
              .join("、")}
          </Typography.Text>
        )}
      </Space>
    </Card>
  );
}
