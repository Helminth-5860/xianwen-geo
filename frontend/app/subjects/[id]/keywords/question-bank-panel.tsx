"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Pagination,
  Popconfirm,
  Space,
  Tag,
  Typography,
} from "antd";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  confirmQuestionBank,
  createQuestionGeneration,
  getCurrentQuestionBank,
  getQuestionBankDraft,
  getQuestionGenerationJob,
  questionGenerationErrorMessage,
  type QuestionBankDraft,
  type QuestionBankVersion,
  type QuestionDraftItem,
  type QuestionGenerationJob,
} from "@/lib/question-bank-client";
import { getKeywordAssets, updateKeywordAsset, type KeywordAsset } from "@/lib/keywords-client";

const QUESTION_PAGE_SIZE = 20;

const jobStatusLabels: Readonly<Record<string, string>> = {
  queued: "等待生成",
  running: "正在生成",
  retry_wait: "等待再次处理",
  succeeded: "生成完成",
  failed: "生成失败",
  conflict: "内容已更新",
  superseded: "已有更新结果",
};

function questionGenerationMessage(code: string | null | undefined) {
  if (code === "QUESTION_GENERATION_IN_PROGRESS") return "问题正在生成，请稍候。";
  return questionGenerationErrorMessage(code);
}

type Props = Readonly<{
  subjectId: string;
  upstreamDirty: boolean;
}>;

export default function QuestionBankPanel({ subjectId, upstreamDirty }: Props) {
  const router = useRouter();
  const [draft, setDraft] = useState<QuestionBankDraft>();
  const [items, setItems] = useState<QuestionDraftItem[]>([]);
  const [currentVersion, setCurrentVersion] = useState<QuestionBankVersion>();
  const [keywordAssets, setKeywordAssets] = useState<KeywordAsset[]>([]);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [questionPage, setQuestionPage] = useState(1);
  const [keywordPage, setKeywordPage] = useState(1);
  const [job, setJob] = useState<QuestionGenerationJob>();
  const [busy, setBusy] = useState(false);
  const [confirmRegeneration, setConfirmRegeneration] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const active = Boolean(job && ["queued", "running", "retry_wait"].includes(job.status));

  const reload = useCallback(async () => {
    const currentVersionRequest = getCurrentQuestionBank(subjectId).catch((reason) => {
      if (reason instanceof AuthApiError && reason.status === 404) return undefined;
      throw reason;
    });
    const [nextDraft, assets, nextCurrentVersion] = await Promise.all([
      getQuestionBankDraft(subjectId),
      getKeywordAssets(subjectId),
      currentVersionRequest,
    ]);
    const nextAssets = assets.items.filter((asset) => !asset.deleted);
    setDraft(nextDraft);
    setItems(nextDraft.items.map((item) => ({ ...item })));
    setCurrentVersion(nextCurrentVersion);
    setKeywordAssets(nextAssets);
    setSelectedAssetIds(
      nextAssets
        .filter((asset) => asset.enabled && asset.usable_for_questions)
        .map((asset) => asset.id),
    );
    setQuestionPage(1);
    setKeywordPage(1);
  }, [subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(
      () => void reload().catch((reason) => setError(userMessage(reason))),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [reload]);

  useEffect(() => {
    if (!active || !job) return;
    const timer = window.setTimeout(() => {
      void getQuestionGenerationJob(job.id)
        .then(async (next) => {
          setJob(next);
          if (next.status === "succeeded") {
            await reload();
            setNotice("问题已生成，请确认后保存到问题管理");
            setError("");
          } else if (["failed", "conflict", "superseded"].includes(next.status)) {
            setError(questionGenerationMessage(next.stable_error_code));
            setNotice("");
          }
        })
        .catch((reason) => setError(userMessage(reason)));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [active, job, reload]);

  const toggleKeywordAsset = (assetId: string, selected: boolean) => {
    setSelectedAssetIds((current) =>
      selected
        ? Array.from(new Set([...current, assetId]))
        : current.filter((id) => id !== assetId),
    );
  };

  const syncKeywordSelection = async () => {
    const selected = new Set(selectedAssetIds);
    const changed = keywordAssets.filter(
      (asset) => asset.enabled && asset.usable_for_questions !== selected.has(asset.id),
    );
    if (!changed.length) return;
    const updated = await Promise.all(
      changed.map((asset) =>
        updateKeywordAsset(subjectId, asset.id, {
          usableForQuestions: selected.has(asset.id),
        }),
      ),
    );
    const updatedById = new Map(updated.map((asset) => [asset.id, asset]));
    setKeywordAssets((current) => current.map((asset) => updatedById.get(asset.id) ?? asset));
  };

  const generate = async (regenerate: boolean) => {
    if (!draft?.current_distillation_set) {
      setError("请先确认关键词蒸馏结果");
      return;
    }
    if (!selectedAssetIds.length) {
      setError("请至少选择一个用于问题生成的关键词资产");
      return;
    }
    if (upstreamDirty) {
      setError("请先保存上游修改，再生成问题");
      return;
    }
    setBusy(true);
    try {
      await syncKeywordSelection();
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
          ? "已开始首次免费生成问题"
          : "已开始重新生成问题，并暂时预留额度",
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
        setError(questionGenerationMessage(reason.code));
        setNotice("");
      } else {
        setError(userMessage(reason));
        setNotice("");
      }
    } finally {
      setBusy(false);
    }
  };

  const saveToManagement = async () => {
    if (!draft || !items.length) return;
    setBusy(true);
    try {
      await confirmQuestionBank(subjectId, draft.version);
      setError("");
      setNotice("问题已保存到问题管理");
      router.push(`/subjects/${subjectId}/questions/manage`);
    } catch (reason) {
      setError(userMessage(reason));
      setNotice("");
    } finally {
      setBusy(false);
    }
  };

  const disabled = !draft?.can_write || busy || active;
  const questionPageCount = Math.max(1, Math.ceil(items.length / QUESTION_PAGE_SIZE));
  const effectiveQuestionPage = Math.min(questionPage, questionPageCount);
  const questionPageStart = (effectiveQuestionPage - 1) * QUESTION_PAGE_SIZE;
  const visibleQuestions = items.slice(questionPageStart, questionPageStart + QUESTION_PAGE_SIZE);
  const keywordPageCount = Math.max(1, Math.ceil(keywordAssets.length / QUESTION_PAGE_SIZE));
  const effectiveKeywordPage = Math.min(keywordPage, keywordPageCount);
  const keywordPageStart = (effectiveKeywordPage - 1) * QUESTION_PAGE_SIZE;
  const visibleKeywordAssets = keywordAssets.slice(
    keywordPageStart,
    keywordPageStart + QUESTION_PAGE_SIZE,
  );
  const hasUnconfirmedGeneratedResult = Boolean(
    draft?.source_result_id && draft.source_result_id !== currentVersion?.source_result_id,
  );

  return (
    <Card title="问题生成" style={{ marginTop: 20 }}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {notice ? <Alert type="success" showIcon message={notice} /> : null}
        <Typography.Text type="secondary">
          选择当前主体已确认的关键词资产，生成结果确认后保存到问题管理。
        </Typography.Text>
        <Space wrap>
          {draft?.current_distillation_set ? <Tag color="blue">已使用当前关键词资产</Tag> : null}
          {draft?.question_limit ? <Tag>问题上限 {draft.question_limit}</Tag> : null}
          {job ? (
            <Tag color={job.status === "succeeded" ? "green" : "blue"}>
              {jobStatusLabels[job.status] ?? "处理中"}
            </Tag>
          ) : null}
        </Space>

        <Card size="small" title="选择关键词资产">
          <Space direction="vertical" size="small" style={{ width: "100%" }}>
            <Typography.Text type="secondary">
              已选择 {selectedAssetIds.length} 个；点击生成时会同步本次选择。
            </Typography.Text>
            {visibleKeywordAssets.map((asset) => (
              <Card key={asset.id} size="small">
                <Space wrap>
                  <Checkbox
                    aria-label={`选择关键词：${asset.text}`}
                    checked={selectedAssetIds.includes(asset.id)}
                    disabled={disabled || !asset.enabled}
                    onChange={(event) => toggleKeywordAsset(asset.id, event.target.checked)}
                  >
                    {asset.text}
                  </Checkbox>
                  <Tag color={asset.enabled ? "green" : "default"}>
                    {asset.enabled ? "已启用" : "已停用"}
                  </Tag>
                </Space>
              </Card>
            ))}
            {!keywordAssets.length ? (
              <Space wrap>
                <Typography.Text type="secondary">
                  暂无可用关键词资产，请先完成关键词蒸馏。
                </Typography.Text>
                <Button size="small" href={`/subjects/${subjectId}/keywords/distill`}>
                  去关键词蒸馏
                </Button>
              </Space>
            ) : null}
            {keywordAssets.length > QUESTION_PAGE_SIZE ? (
              <Pagination
                aria-label="问题生成关键词分页"
                current={effectiveKeywordPage}
                pageSize={QUESTION_PAGE_SIZE}
                total={keywordAssets.length}
                showSizeChanger={false}
                showTotal={(total, range) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`}
                onChange={setKeywordPage}
              />
            ) : null}
          </Space>
        </Card>

        <Space wrap>
          <Button
            type="primary"
            disabled={
              disabled ||
              upstreamDirty ||
              !draft?.current_distillation_set ||
              selectedAssetIds.length === 0
            }
            loading={busy}
            onClick={() => void generate(false)}
          >
            AI 生成问题
          </Button>
          {confirmRegeneration ? (
            <Popconfirm
              title="确认消耗一次问题重生成额度？"
              description="成功生成后扣除；失败、冲突或过期会释放。"
              okText="确认重生成"
              cancelText="取消"
              onConfirm={() => void generate(true)}
            >
              <Button danger disabled={disabled || upstreamDirty}>
                确认消耗额度并重生成
              </Button>
            </Popconfirm>
          ) : null}
        </Space>

        <Card size="small" title="生成结果">
          <Space direction="vertical" size="small" style={{ width: "100%" }}>
            {visibleQuestions.map((item) => (
              <Card key={item.id} size="small">
                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                  <Typography.Text strong>{item.text}</Typography.Text>
                  <Space wrap>
                    <Tag>{item.primary_category.name}</Tag>
                    <Tag>
                      {item.priority === "high"
                        ? "高优先级"
                        : item.priority === "low"
                          ? "低优先级"
                          : "中优先级"}
                    </Tag>
                    <Tag>
                      {item.question_type === "brand_directed" ? "品牌指向型" : "自然探索型"}
                    </Tag>
                  </Space>
                  {item.ai_reason ? (
                    <Typography.Text type="secondary">{item.ai_reason}</Typography.Text>
                  ) : null}
                </Space>
              </Card>
            ))}
            {!items.length ? (
              <Typography.Text type="secondary">
                尚未生成问题。请选择关键词资产后，点击上方“AI 生成问题”。
              </Typography.Text>
            ) : null}
            {items.length > QUESTION_PAGE_SIZE ? (
              <Pagination
                aria-label="问题生成结果分页"
                current={effectiveQuestionPage}
                pageSize={QUESTION_PAGE_SIZE}
                total={items.length}
                showSizeChanger={false}
                showTotal={(total, range) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`}
                onChange={setQuestionPage}
              />
            ) : null}
          </Space>
        </Card>

        {items.length > 0 && hasUnconfirmedGeneratedResult ? (
          <Popconfirm
            title="保存到问题管理"
            description="将当前问题草稿确认为正式问题库，并进入问题管理。"
            okText="确认保存"
            cancelText="取消"
            onConfirm={() => void saveToManagement()}
          >
            <Button type="primary" disabled={disabled}>
              保存到问题管理
            </Button>
          </Popconfirm>
        ) : currentVersion ? (
          <Button type="primary" href={`/subjects/${subjectId}/questions/manage`}>
            已保存，进入问题管理
          </Button>
        ) : null}
      </Space>
    </Card>
  );
}
