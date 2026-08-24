"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AuthApiError, userMessage } from "@/lib/auth-client";

import DistillationPanel from "./distillation-panel";
import QuestionBankPanel from "./question-bank-panel";
import {
  commitKeywords,
  createKeywordGeneration,
  getKeywordDraft,
  getKeywordGenerationJob,
  getKeywordVersion,
  getKeywordVersions,
  saveKeywordDraft,
  type KeywordDraftState,
  type KeywordGenerationJob,
  type KeywordItem,
  type KeywordPriority,
  type KeywordRegionLevel,
  type KeywordSearchIntent,
  type KeywordStructureType,
  type KeywordVersion,
} from "@/lib/keywords-client";

const structureOptions = [
  { value: "short", label: "短关键词" },
  { value: "long_tail", label: "长尾关键词" },
  { value: "general", label: "通用关键词" },
];
const regionOptions = [
  { value: "country", label: "国家/地区" },
  { value: "province", label: "省/州" },
  { value: "city", label: "城市" },
  { value: "district", label: "区县" },
  { value: "custom", label: "自定义" },
];
const intentOptions = [
  { value: "informational", label: "信息型" },
  { value: "navigational", label: "导航型" },
  { value: "commercial", label: "商业调研型" },
  { value: "transactional", label: "交易型" },
];
const priorityOptions = [
  { value: "high", label: "高" },
  { value: "medium", label: "中" },
  { value: "low", label: "低" },
];

const readOnlyReasons: Record<string, string> = {
  account_unavailable: "当前账号状态不允许编辑关键词。",
  subject_archived: "已归档主体只能查看关键词历史。",
  subject_version_required: "请先提交主体正式版本，再维护关键词。",
  plan_required: "当前操作需要有效套餐。",
};

function draftItem(): KeywordItem {
  return {
    text: "",
    structure_type: "general",
    is_regional: false,
    region_level: null,
    region_text: null,
    base_keyword_text: null,
    business_category: null,
    search_intent: null,
    relevance_score: null,
    priority: null,
    ai_reason: null,
    sort_order: 0,
  };
}

export default function KeywordEditorPage() {
  const params = useParams<{ id: string }>();
  const [draft, setDraft] = useState<KeywordDraftState>();
  const [items, setItems] = useState<KeywordItem[]>([]);
  const [versions, setVersions] = useState<KeywordVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<KeywordVersion>();
  const [dirty, setDirty] = useState(false);
  const [distillationDirty, setDistillationDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [generation, setGeneration] = useState<KeywordGenerationJob>();
  const [targetCount, setTargetCount] = useState(10);
  const [includeShort, setIncludeShort] = useState(false);
  const [includeLongTail, setIncludeLongTail] = useState(false);
  const [includeRegional, setIncludeRegional] = useState(false);
  const [regionsText, setRegionsText] = useState("");
  const [regenerationConfirmation, setRegenerationConfirmation] = useState(false);
  const generationActive = Boolean(
    generation && ["queued", "running", "retry_wait"].includes(generation.status),
  );

  const reload = useCallback(async () => {
    const [nextDraft, history] = await Promise.all([
      getKeywordDraft(params.id),
      getKeywordVersions(params.id),
    ]);
    setDraft(nextDraft);
    setItems(nextDraft.items);
    setVersions(history.versions);
    setDirty(false);
  }, [params.id]);

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
    if (!generationActive || !generation) return;
    const timer = window.setTimeout(() => {
      void getKeywordGenerationJob(generation.id)
        .then(async (next) => {
          setGeneration(next);
          if (next.status === "succeeded") {
            setNotice("AI 关键词已写入草稿，请审核、编辑后再提交正式版本");
            setError("");
            await reload();
          } else if (["failed", "conflict", "superseded"].includes(next.status)) {
            setError(next.stable_error_code || "关键词生成失败，请重试");
            setNotice("");
          }
        })
        .catch((reason) => setError(userMessage(reason)));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [generation, generationActive, reload]);

  const change = (index: number, patch: Partial<KeywordItem>) => {
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

  const startGeneration = async (regenerate: boolean) => {
    if (!draft?.subject_version) return;
    if (dirty) {
      setError("请先保存或放弃本地未保存修改，再启动 AI 生成");
      return;
    }
    const regions = regionsText
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    if (includeRegional && regions.length === 0) {
      setError("选择地域词时至少填写一个地域");
      return;
    }
    setBusy(true);
    try {
      const job = await createKeywordGeneration(
        params.id,
        {
          expectedSubjectVersionId: draft.subject_version.id,
          expectedKeywordSetVersion: draft.version,
          targetCount,
          includeShort,
          includeLongTail,
          includeRegional,
          regions: includeRegional ? regions : [],
          regenerate,
        },
        crypto.randomUUID(),
      );
      setGeneration(job);
      setRegenerationConfirmation(false);
      setError("");
      if (job.status === "succeeded") {
        await reload();
        setNotice("已恢复此前成功的生成结果，关键词草稿已刷新");
      } else {
        setNotice(
          job.billing.billing_mode === "free_initial"
            ? "首次免费生成任务已提交"
            : "再生成任务已提交，额度已冻结",
        );
      }
    } catch (reason) {
      if (
        reason instanceof AuthApiError &&
        reason.code === "KEYWORD_REGENERATION_CONFIRMATION_REQUIRED"
      ) {
        setRegenerationConfirmation(true);
        setError("");
        setNotice("该主体已使用免费生成，请确认消耗一次再生成额度");
      } else {
        setError(userMessage(reason));
        setNotice("");
      }
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!draft?.subject_version) return;
    setBusy(true);
    try {
      const next = await saveKeywordDraft(params.id, {
        expectedVersion: draft.version,
        expectedSubjectVersionId: draft.subject_version.id,
        items,
      });
      setDraft(next);
      setItems(next.items);
      setDirty(false);
      setError("");
      setNotice("关键词草稿已保存");
    } catch (reason) {
      setError(userMessage(reason));
      setNotice("");
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!draft?.subject_version) return;
    if (dirty) {
      setError("请先保存当前关键词草稿，再提交正式版本。");
      return;
    }
    setBusy(true);
    try {
      const result = await commitKeywords(params.id, draft.version, draft.subject_version.id);
      setNotice(`关键词正式版本 v${result.version.version_no} 已提交`);
      setError("");
      await reload();
    } catch (reason) {
      setError(userMessage(reason));
      setNotice("");
    } finally {
      setBusy(false);
    }
  };

  if (!draft && !error) return <Spin fullscreen description="正在加载关键词" />;
  const disabled = !draft?.can_write || busy || generationActive;
  const baseStale = Boolean(
    draft?.subject_version &&
    draft.draft_subject_version &&
    draft.subject_version.id !== draft.draft_subject_version.id,
  );

  return (
    <main className="page-shell">
      <Link href={`/subjects/${params.id}`}>返回主体详情</Link>
      <Typography.Title style={{ marginTop: 16 }}>关键词编辑器</Typography.Title>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      {notice && <Alert type="success" showIcon message={notice} style={{ marginBottom: 16 }} />}
      {baseStale && (
        <Alert
          type="warning"
          showIcon
          message="主体资料正式版本已更新，请先保存关键词草稿以重新绑定后再提交。"
          style={{ marginBottom: 16 }}
        />
      )}
      {draft && !draft.can_write && draft.read_only_reason && (
        <Alert
          type="warning"
          showIcon
          message={readOnlyReasons[draft.read_only_reason] ?? "当前状态为只读"}
          style={{ marginBottom: 16 }}
        />
      )}
      {draft?.subject_version && (
        <Space style={{ marginBottom: 16 }}>
          <Tag color="blue">主体正式版本 v{draft.subject_version.version_no}</Tag>
          {draft.current_keyword_version_no && (
            <Tag color="green">关键词正式版本 v{draft.current_keyword_version_no}</Tag>
          )}
          {dirty && <Tag color="orange">有未保存修改</Tag>}
        </Space>
      )}

      <Card title="AI 关键词生成" style={{ marginBottom: 20 }}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space wrap>
            <Typography.Text>生成数量</Typography.Text>
            <InputNumber
              aria-label="生成数量"
              min={1}
              max={200}
              value={targetCount}
              disabled={disabled}
              onChange={(value) => setTargetCount(value ?? 1)}
            />
            <Checkbox
              checked={includeShort}
              disabled={disabled}
              onChange={(event) => setIncludeShort(event.target.checked)}
            >
              短关键词
            </Checkbox>
            <Checkbox
              checked={includeLongTail}
              disabled={disabled}
              onChange={(event) => setIncludeLongTail(event.target.checked)}
            >
              长尾关键词
            </Checkbox>
            <Checkbox
              checked={includeRegional}
              disabled={disabled}
              onChange={(event) => setIncludeRegional(event.target.checked)}
            >
              地域词
            </Checkbox>
          </Space>
          {!includeShort && !includeLongTail && (
            <Typography.Text type="secondary">
              未选择短词或长尾词时，将使用通用模式。
            </Typography.Text>
          )}
          {includeRegional && (
            <Input
              aria-label="生成地域"
              value={regionsText}
              disabled={disabled}
              placeholder="多个地域用英文逗号分隔，例如：上海,杭州"
              onChange={(event) => setRegionsText(event.target.value)}
            />
          )}
          <Space wrap>
            <Button
              type="primary"
              loading={busy}
              disabled={disabled || dirty}
              onClick={() => void startGeneration(false)}
            >
              AI 生成关键词
            </Button>
            {regenerationConfirmation && (
              <Popconfirm
                title="确认消耗一次关键词再生成额度？"
                description="额度会先冻结，只有结果成功写入草稿后才会扣除；失败或冲突会释放。"
                okText="确认再生成"
                cancelText="取消"
                onConfirm={() => void startGeneration(true)}
              >
                <Button danger disabled={disabled || dirty}>
                  确认消耗额度并再生成
                </Button>
              </Popconfirm>
            )}
            {generation && (
              <>
                <Tag color={generation.status === "succeeded" ? "green" : "blue"}>
                  任务：{generation.status}
                </Tag>
                <Tag>
                  {generation.billing.billing_mode === "free_initial"
                    ? "首次免费"
                    : `再生成剩余 ${generation.billing.remaining ?? "-"}`}
                </Tag>
              </>
            )}
          </Space>
        </Space>
      </Card>

      <Card title="关键词草稿">
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          {items.map((item, index) => (
            <Card key={item.id ?? `new-${index}`} size="small">
              <Space wrap align="start">
                <Input
                  aria-label={`关键词-${index + 1}`}
                  value={item.text}
                  disabled={disabled}
                  placeholder="输入关键词"
                  style={{ width: 220 }}
                  onChange={(event) => change(index, { text: event.target.value })}
                />
                <Select
                  aria-label={`关键词类型-${index + 1}`}
                  value={item.structure_type}
                  disabled={disabled}
                  options={structureOptions}
                  style={{ width: 140 }}
                  onChange={(value: KeywordStructureType) =>
                    change(index, { structure_type: value })
                  }
                />
                <Checkbox
                  aria-label={`地域词-${index + 1}`}
                  checked={item.is_regional}
                  disabled={disabled}
                  onChange={(event) =>
                    change(index, {
                      is_regional: event.target.checked,
                      region_level: event.target.checked ? item.region_level : null,
                      region_text: event.target.checked ? item.region_text : null,
                    })
                  }
                >
                  地域词
                </Checkbox>
                {item.is_regional && (
                  <>
                    <Select
                      aria-label={`地域层级-${index + 1}`}
                      allowClear
                      value={item.region_level ?? undefined}
                      disabled={disabled}
                      options={regionOptions}
                      placeholder="地域层级"
                      style={{ width: 140 }}
                      onChange={(value: KeywordRegionLevel | undefined) =>
                        change(index, { region_level: value ?? null })
                      }
                    />
                    <Input
                      aria-label={`地域文本-${index + 1}`}
                      value={item.region_text ?? ""}
                      disabled={disabled}
                      placeholder="例如：上海"
                      style={{ width: 180 }}
                      onChange={(event) => change(index, { region_text: event.target.value })}
                    />
                  </>
                )}
                <Input
                  aria-label={`基础关键词-${index + 1}`}
                  value={item.base_keyword_text ?? ""}
                  disabled={disabled}
                  placeholder="基础关键词（可选）"
                  style={{ width: 200 }}
                  onChange={(event) =>
                    change(index, { base_keyword_text: event.target.value || null })
                  }
                />
                <Input
                  aria-label={`业务分类-${index + 1}`}
                  value={item.business_category ?? ""}
                  disabled={disabled}
                  placeholder="业务分类（可选）"
                  style={{ width: 180 }}
                  onChange={(event) =>
                    change(index, { business_category: event.target.value || null })
                  }
                />
                <Select
                  aria-label={`搜索意图-${index + 1}`}
                  allowClear
                  value={item.search_intent ?? undefined}
                  disabled={disabled}
                  options={intentOptions}
                  placeholder="搜索意图"
                  style={{ width: 150 }}
                  onChange={(value: KeywordSearchIntent | undefined) =>
                    change(index, { search_intent: value ?? null })
                  }
                />
                <Select
                  aria-label={`优先级-${index + 1}`}
                  allowClear
                  value={item.priority ?? undefined}
                  disabled={disabled}
                  options={priorityOptions}
                  placeholder="优先级"
                  style={{ width: 120 }}
                  onChange={(value: KeywordPriority | undefined) =>
                    change(index, { priority: value ?? null })
                  }
                />
                {item.relevance_score !== null && (
                  <Tag aria-label={`相关度-${index + 1}`}>相关度 {item.relevance_score}</Tag>
                )}
                {item.ai_reason && (
                  <Typography.Text
                    aria-label={`AI 理由-${index + 1}`}
                    type="secondary"
                    style={{ maxWidth: 360 }}
                  >
                    {item.ai_reason}
                  </Typography.Text>
                )}
                <Button
                  aria-label={`上移-${index + 1}`}
                  disabled={disabled || index === 0}
                  onClick={() => move(index, -1)}
                >
                  上移
                </Button>
                <Button
                  aria-label={`下移-${index + 1}`}
                  disabled={disabled || index === items.length - 1}
                  onClick={() => move(index, 1)}
                >
                  下移
                </Button>
                <Button
                  aria-label={`删除-${index + 1}`}
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
            </Card>
          ))}
          <Space>
            <Button
              disabled={disabled}
              onClick={() => {
                setItems((current) => [...current, { ...draftItem(), sort_order: current.length }]);
                setDirty(true);
              }}
            >
              添加关键词
            </Button>
            <Button type="primary" loading={busy} disabled={disabled} onClick={() => void save()}>
              保存草稿
            </Button>
            <Popconfirm
              title="提交关键词正式版本"
              description="提交后会形成不可修改的关键词历史版本。"
              okText="确认提交"
              cancelText="取消"
              onConfirm={() => void commit()}
            >
              <Button
                loading={busy}
                disabled={disabled || dirty || baseStale || items.length === 0}
              >
                保存并生成新版本
              </Button>
            </Popconfirm>
          </Space>
        </Space>
      </Card>

      <DistillationPanel
        subjectId={params.id}
        keywordDirty={dirty}
        onDirtyChange={setDistillationDirty}
      />
      <QuestionBankPanel subjectId={params.id} upstreamDirty={dirty || distillationDirty} />

      <Card title="关键词版本历史" style={{ marginTop: 20 }}>
        <Space direction="vertical" style={{ width: "100%" }}>
          {versions.length === 0 && (
            <Typography.Text type="secondary">暂无正式版本</Typography.Text>
          )}
          {versions.map((version) => (
            <Space key={version.id}>
              <Typography.Text>v{version.version_no}</Typography.Text>
              <Typography.Text type="secondary">
                基于主体 v{version.subject_version.version_no} · {version.item_count} 个关键词
              </Typography.Text>
              <Button
                size="small"
                onClick={() =>
                  void getKeywordVersion(params.id, version.id)
                    .then(setSelectedVersion)
                    .catch((reason) => setError(userMessage(reason)))
                }
              >
                查看
              </Button>
            </Space>
          ))}
        </Space>
      </Card>

      {selectedVersion && (
        <Card title={`关键词正式版本 v${selectedVersion.version_no}`} style={{ marginTop: 20 }}>
          <Space direction="vertical">
            {selectedVersion.items?.map((item) => (
              <Typography.Text key={item.id}>
                {item.text} ·{" "}
                {structureOptions.find((option) => option.value === item.structure_type)?.label}
                {item.is_regional && item.region_text ? ` · ${item.region_text}` : ""}
              </Typography.Text>
            ))}
          </Space>
        </Card>
      )}
    </main>
  );
}
