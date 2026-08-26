"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Input,
  InputNumber,
  Popconfirm,
  Radio,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  keywordRegionSelectionsFromServiceArea,
  KeywordRegionSelector,
} from "@/components/keyword-region-selector";
import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  appendKeywordCandidates,
  createKeywordGeneration,
  getKeywordAssets,
  getKeywordDraft,
  getKeywordGenerationJob,
  keywordBusinessCategoryOptions,
  keywordJobErrorMessage,
  keywordJobStatusLabel,
  keywordSearchIntentOptions,
  updateKeywordAsset,
  type KeywordDraftState,
  type KeywordGenerationJob,
  type KeywordAsset,
  type KeywordItem,
  type KeywordRegionSelection,
  type KeywordSearchIntent,
} from "@/lib/keywords-client";

import DistillationPanel from "./distillation-panel";
import QuestionBankPanel from "./question-bank-panel";

export type KeywordCenterStage = "generate" | "custom" | "distill" | "assets" | "questions";
type RegionMode = "unrestricted" | "subject" | "custom";
type LengthType = "short" | "long_tail";

const sourceLabels: Readonly<Record<string, string>> = {
  legacy: "已有关键词",
  manual: "手工添加",
  bulk: "批量添加",
  smart_generation: "智能生成",
  custom_generation: "智能生成",
};

const categoryGroups = [
  {
    title: "品牌与供给",
    values: ["entity", "industry", "product_category", "product", "service"],
  },
  {
    title: "用户需求",
    values: ["capability", "goal", "pain_point", "solution"],
  },
  {
    title: "市场决策",
    values: ["scenario", "audience", "competitor", "trust"],
  },
  { title: "内容认知", values: ["knowledge"] },
] as const;

const legacyIntentMap: Readonly<Record<string, KeywordSearchIntent>> = {
  informational: "informational",
  navigational: "navigational",
  commercial: "recommendation",
  transactional: "transactional",
};

function itemIntents(item: KeywordItem): KeywordSearchIntent[] {
  if (item.search_intents?.length) return item.search_intents;
  const legacy = item.search_intent ? legacyIntentMap[item.search_intent] : undefined;
  return legacy ? [legacy] : [];
}

function categoryLabel(value: string | null) {
  return keywordBusinessCategoryOptions.find((option) => option.value === value)?.label ?? value;
}

function intentLabel(value: KeywordSearchIntent) {
  return keywordSearchIntentOptions.find((option) => option.value === value)?.label ?? value;
}

function formatUpdatedAt(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function GenerationControls({
  targetCount,
  includeShort,
  includeLongTail,
  regionMode,
  regionSelections,
  serviceRegions,
  disabled,
  onTargetCountChange,
  onIncludeShortChange,
  onIncludeLongTailChange,
  onRegionModeChange,
  onRegionSelectionsChange,
}: Readonly<{
  targetCount: number;
  includeShort: boolean;
  includeLongTail: boolean;
  regionMode: RegionMode;
  regionSelections: KeywordRegionSelection[];
  serviceRegions: string;
  disabled: boolean;
  onTargetCountChange: (value: number) => void;
  onIncludeShortChange: (value: boolean) => void;
  onIncludeLongTailChange: (value: boolean) => void;
  onRegionModeChange: (value: RegionMode) => void;
  onRegionSelectionsChange: (value: KeywordRegionSelection[]) => void;
}>) {
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <div>
        <Typography.Text strong>3. 生成数量</Typography.Text>
        <div style={{ marginTop: 8 }}>
          <Space wrap>
            <Radio.Group
              aria-label="生成数量快捷选择"
              value={[10, 20, 50, 100].includes(targetCount) ? targetCount : undefined}
              disabled={disabled}
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: 10, label: "10 个" },
                { value: 20, label: "20 个" },
                { value: 50, label: "50 个" },
                { value: 100, label: "100 个" },
              ]}
              onChange={(event) => onTargetCountChange(event.target.value)}
            />
            <InputNumber
              aria-label="自定义生成数量"
              addonBefore="自定义"
              min={1}
              max={200}
              value={targetCount}
              disabled={disabled}
              onChange={(value) => onTargetCountChange(value ?? 1)}
            />
          </Space>
        </div>
      </div>
      <div>
        <Typography.Text strong>4. 关键词长度</Typography.Text>
        <div style={{ marginTop: 8 }}>
          <Space wrap>
            <Checkbox
              checked={includeShort}
              disabled={disabled}
              onChange={(event) => onIncludeShortChange(event.target.checked)}
            >
              短关键词
            </Checkbox>
            <Checkbox
              checked={includeLongTail}
              disabled={disabled}
              onChange={(event) => onIncludeLongTailChange(event.target.checked)}
            >
              长尾关键词
            </Checkbox>
          </Space>
        </div>
      </div>
      <div>
        <Typography.Text strong>5. 地域范围</Typography.Text>
        <div style={{ marginTop: 8 }}>
          <Radio.Group
            aria-label="地域范围"
            value={regionMode}
            disabled={disabled}
            onChange={(event) => onRegionModeChange(event.target.value as RegionMode)}
          >
            <Radio value="unrestricted">不限地域</Radio>
            <Radio value="subject">使用主体服务区域</Radio>
            <Radio value="custom">自定义地域</Radio>
          </Radio.Group>
        </div>
        {regionMode !== "unrestricted" ? (
          <div style={{ marginTop: 12 }}>
            <KeywordRegionSelector
              mode={regionMode === "subject" ? "subject" : "custom"}
              serviceRegions={serviceRegions}
              value={regionSelections}
              disabled={disabled}
              onChange={onRegionSelectionsChange}
            />
          </div>
        ) : null}
      </div>
    </Space>
  );
}

export function KeywordCenterPage({
  stage = "generate",
}: Readonly<{ stage?: KeywordCenterStage }>) {
  const params = useParams<{ id: string }>();
  const { currentSubject, subjects } = useSubjectWorkspace();
  const routeSubject = subjects.find((subject) => subject.id === params.id) ?? currentSubject;
  const [draft, setDraft] = useState<KeywordDraftState>();
  const [items, setItems] = useState<KeywordItem[]>([]);
  const [assets, setAssets] = useState<KeywordAsset[]>([]);
  const [viewingAssetId, setViewingAssetId] = useState<string>();
  const [editingAssetId, setEditingAssetId] = useState<string>();
  const [assetText, setAssetText] = useState("");
  const [assetCategory, setAssetCategory] = useState<string>();
  const [assetIntents, setAssetIntents] = useState<KeywordSearchIntent[]>([]);
  const [distillationDirty, setDistillationDirty] = useState(false);
  const [generation, setGeneration] = useState<KeywordGenerationJob>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [regenerationConfirmation, setRegenerationConfirmation] = useState(false);
  const [targetCount, setTargetCount] = useState(10);
  const [includeShort, setIncludeShort] = useState(true);
  const [includeLongTail, setIncludeLongTail] = useState(true);
  const [regionMode, setRegionMode] = useState<RegionMode>("subject");
  const [regionSelections, setRegionSelections] = useState<KeywordRegionSelection[]>([]);
  const [businessCategories, setBusinessCategories] = useState<string[]>(() =>
    keywordBusinessCategoryOptions.map((option) => option.value),
  );
  const [searchIntents, setSearchIntents] = useState<KeywordSearchIntent[]>(() =>
    keywordSearchIntentOptions.map((option) => option.value),
  );
  const [manualText, setManualText] = useState("");
  const [manualCategory, setManualCategory] = useState<string>();
  const [manualIntents, setManualIntents] = useState<KeywordSearchIntent[]>([]);
  const [manualLength, setManualLength] = useState<LengthType>("short");
  const [manualRegions, setManualRegions] = useState<KeywordRegionSelection[]>([]);
  const [manualNotes, setManualNotes] = useState("");
  const [batchText, setBatchText] = useState("");
  const [batchCategory, setBatchCategory] = useState<string>();
  const [batchIntents, setBatchIntents] = useState<KeywordSearchIntent[]>([]);
  const [batchLength, setBatchLength] = useState<LengthType>("short");
  const [batchRegions, setBatchRegions] = useState<KeywordRegionSelection[]>([]);
  const generationActive = Boolean(
    generation && ["queued", "running", "retry_wait"].includes(generation.status),
  );

  const reload = useCallback(async () => {
    const [nextDraft, nextAssets] = await Promise.all([
      getKeywordDraft(params.id),
      getKeywordAssets(params.id),
    ]);
    setDraft(nextDraft);
    setItems(nextDraft.items);
    setAssets(nextAssets.items.filter((asset) => !asset.deleted));
  }, [params.id]);

  useEffect(() => {
    const timer = window.setTimeout(
      () => void reload().catch((reason) => setError(userMessage(reason))),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [reload]);

  useEffect(() => {
    if (!generationActive || !generation) return;
    const timer = window.setTimeout(() => {
      void getKeywordGenerationJob(generation.id)
        .then(async (next) => {
          setGeneration(next);
          if (next.status === "succeeded") {
            setNotice("AI 关键词已生成，已加入待蒸馏关键词");
            setError("");
            await reload();
          } else if (["failed", "conflict", "superseded"].includes(next.status)) {
            setError(keywordJobErrorMessage(next.stable_error_code, "关键词生成失败，请重试"));
            setNotice("");
          }
        })
        .catch((reason) => setError(userMessage(reason)));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [generation, generationActive, reload]);

  const startGeneration = async (regenerate: boolean) => {
    if (!draft?.subject_version) return;
    if (!includeShort && !includeLongTail) {
      setError("请至少选择一种关键词长度");
      return;
    }
    if (regionMode === "custom" && regionSelections.length === 0) {
      setError("请选择至少一个自定义地域");
      return;
    }
    if (!businessCategories.length || !searchIntents.length) {
      setError("请至少选择一个关键词类别和一个用户意图");
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
          includeRegional: regionMode !== "unrestricted",
          regions:
            regionMode === "custom"
              ? regionSelections
              : regionMode === "subject"
                ? keywordRegionSelectionsFromServiceArea(routeSubject?.service_regions ?? "")
                : [],
          generationMode: "smart",
          categories: businessCategories,
          intents: searchIntents,
          regionMode,
          regenerate,
        },
        crypto.randomUUID(),
      );
      setGeneration(job);
      setRegenerationConfirmation(false);
      setError("");
      if (job.status === "succeeded") {
        await reload();
        setNotice("关键词已生成并加入待蒸馏关键词");
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

  const appendCandidates = async (
    source: "manual" | "bulk",
    values: Array<{
      text: string;
      category: string;
      intents: KeywordSearchIntent[];
      lengthType: LengthType;
      regions: KeywordRegionSelection[];
      notes: string;
    }>,
  ) => {
    if (!draft?.subject_version || values.length === 0) return false;
    setBusy(true);
    try {
      const result = await appendKeywordCandidates(params.id, {
        expectedVersion: draft.version,
        expectedSubjectVersionId: draft.subject_version.id,
        source,
        items: values,
      });
      setDraft(result.candidate_pool);
      setItems(result.candidate_pool.items);
      setError("");
      setNotice(
        result.skipped_duplicates.length
          ? `已加入 ${result.added_count} 个待蒸馏关键词，跳过 ${result.skipped_duplicates.length} 个重复词`
          : `已加入 ${result.added_count} 个待蒸馏关键词`,
      );
      return true;
    } catch (reason) {
      setError(userMessage(reason));
      setNotice("");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const addManualKeyword = async () => {
    const text = manualText.trim();
    if (!text || !manualCategory || manualIntents.length === 0) {
      setError("请填写关键词，并选择关键词分类和用户意图");
      return;
    }
    const added = await appendCandidates("manual", [
      {
        text,
        category: manualCategory,
        intents: manualIntents,
        lengthType: manualLength,
        regions: manualRegions,
        notes: manualNotes.trim(),
      },
    ]);
    if (added) {
      setManualText("");
      setManualNotes("");
    }
  };

  const addBatchKeywords = async () => {
    const nonEmptyLines = batchText
      .split(/\r?\n/)
      .map((value) => value.trim())
      .filter(Boolean);
    const texts = Array.from(new Set(nonEmptyLines));
    const localDuplicateCount = nonEmptyLines.length - texts.length;
    if (!texts.length || !batchCategory || batchIntents.length === 0) {
      setError("请逐行填写关键词，并选择统一的关键词分类和用户意图");
      return;
    }
    const added = await appendCandidates(
      "bulk",
      texts.map((text) => ({
        text,
        category: batchCategory,
        intents: batchIntents,
        lengthType: batchLength,
        regions: batchRegions,
        notes: "",
      })),
    );
    if (added) {
      setBatchText("");
      if (localDuplicateCount > 0) {
        setNotice((current) => `${current}；另跳过 ${localDuplicateCount} 个本地重复项`);
      }
    }
  };

  const patchAsset = async (
    asset: KeywordAsset,
    patch: Parameters<typeof updateKeywordAsset>[2],
  ) => {
    setBusy(true);
    try {
      const updated = await updateKeywordAsset(params.id, asset.id, patch);
      setAssets((current) =>
        updated.deleted
          ? current.filter((item) => item.id !== updated.id)
          : current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setEditingAssetId(undefined);
      setError("");
      setNotice(updated.deleted ? "关键词已删除" : "关键词资产已更新");
    } catch (reason) {
      setError(userMessage(reason));
      setNotice("");
    } finally {
      setBusy(false);
    }
  };

  const beginAssetEdit = (asset: KeywordAsset) => {
    setEditingAssetId(asset.id);
    setAssetText(asset.text);
    setAssetCategory(asset.category ?? undefined);
    setAssetIntents(asset.intents);
  };

  const toggleBusinessCategory = (value: string, checked: boolean) => {
    setBusinessCategories((current) =>
      checked ? Array.from(new Set([...current, value])) : current.filter((item) => item !== value),
    );
  };

  const selectCategoryGroup = (values: readonly string[]) => {
    setBusinessCategories((current) => Array.from(new Set([...current, ...values])));
  };

  const toggleSearchIntent = (value: KeywordSearchIntent, checked: boolean) => {
    setSearchIntents((current) =>
      checked ? Array.from(new Set([...current, value])) : current.filter((item) => item !== value),
    );
  };

  if (!draft && !error) return <Spin fullscreen description="正在加载关键词" />;
  const disabled = !draft?.can_write || busy || generationActive;
  const baseStale = Boolean(
    draft?.subject_version &&
    draft.draft_subject_version &&
    draft.subject_version.id !== draft.draft_subject_version.id,
  );
  const serviceRegions = routeSubject?.service_regions ?? "";
  const pageTitle =
    stage === "generate"
      ? "智能关键词"
      : stage === "custom"
        ? "自定义关键词"
        : stage === "distill"
          ? "关键词蒸馏"
          : stage === "assets"
            ? "关键词资产"
            : "问题库";
  const pageSubtitle =
    stage === "generate"
      ? "根据当前主体、关键词类别、用户意图和地域范围智能生成关键词"
      : stage === "custom"
        ? "手工添加和管理关键词"
        : stage === "distill"
          ? "整理并确认当前主体的待蒸馏关键词"
          : stage === "assets"
            ? "管理当前主体已确认的正式关键词"
            : "管理当前主体的问题";

  return (
    <main className="page-shell">
      <Link href={`/subjects/${params.id}`}>返回主体详情</Link>
      <Typography.Title style={{ marginTop: 16 }}>{pageTitle}</Typography.Title>
      <Typography.Paragraph type="secondary">{pageSubtitle}</Typography.Paragraph>
      <Typography.Paragraph type="secondary">
        当前企业：{routeSubject?.official_name || routeSubject?.subject_type.name || "当前主体"}
      </Typography.Paragraph>
      <Card className="keyword-center-summary" style={{ marginBottom: 20 }}>
        <Space wrap className="keyword-center-stats">
          <Tag color="orange">待蒸馏关键词 {items.length}</Tag>
          <Tag color="green">关键词资产 {assets.length}</Tag>
        </Space>
      </Card>
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      {notice ? (
        <Alert type="success" showIcon message={notice} style={{ marginBottom: 16 }} />
      ) : null}
      {baseStale ? (
        <Alert
          type="warning"
          showIcon
          message="主体资料已更新，请重新添加或生成关键词。"
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {draft && !draft.can_write && draft.read_only_reason ? (
        <Alert
          type="warning"
          showIcon
          message="当前账号或主体状态不允许维护关键词"
          style={{ marginBottom: 16 }}
        />
      ) : null}

      {stage === "generate" ? (
        <Card title="智能生成设置">
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            <div>
              <Space wrap style={{ marginBottom: 12 }}>
                <Typography.Text strong>1. 关键词类别（可多选）</Typography.Text>
                <Button
                  size="small"
                  disabled={disabled}
                  onClick={() =>
                    setBusinessCategories(
                      keywordBusinessCategoryOptions.map((option) => option.value),
                    )
                  }
                >
                  全部选择
                </Button>
                <Button
                  size="small"
                  disabled={disabled || businessCategories.length === 0}
                  onClick={() => setBusinessCategories([])}
                >
                  清空
                </Button>
              </Space>
              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                {categoryGroups.map((group) => (
                  <Card key={group.title} size="small">
                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                      <Space wrap>
                        <Typography.Text strong>{group.title}</Typography.Text>
                        <Button
                          size="small"
                          disabled={disabled}
                          onClick={() => selectCategoryGroup(group.values)}
                        >
                          本组全选
                        </Button>
                      </Space>
                      <Space wrap>
                        {group.values.map((value) => (
                          <Checkbox
                            key={value}
                            checked={businessCategories.includes(value)}
                            disabled={disabled}
                            onChange={(event) =>
                              toggleBusinessCategory(value, event.target.checked)
                            }
                          >
                            {categoryLabel(value)}
                          </Checkbox>
                        ))}
                      </Space>
                    </Space>
                  </Card>
                ))}
              </Space>
            </div>

            <div>
              <Space wrap style={{ marginBottom: 8 }}>
                <Typography.Text strong>2. 用户意图（可多选）</Typography.Text>
                <Button
                  size="small"
                  disabled={disabled}
                  onClick={() =>
                    setSearchIntents(keywordSearchIntentOptions.map((option) => option.value))
                  }
                >
                  全部选择
                </Button>
                <Button
                  size="small"
                  disabled={disabled || searchIntents.length === 0}
                  onClick={() => setSearchIntents([])}
                >
                  清空
                </Button>
              </Space>
              <Space wrap>
                {keywordSearchIntentOptions.map((option) => (
                  <Checkbox
                    key={option.value}
                    checked={searchIntents.includes(option.value)}
                    disabled={disabled}
                    onChange={(event) => toggleSearchIntent(option.value, event.target.checked)}
                  >
                    {option.label}
                  </Checkbox>
                ))}
              </Space>
            </div>

            <GenerationControls
              targetCount={targetCount}
              includeShort={includeShort}
              includeLongTail={includeLongTail}
              regionMode={regionMode}
              regionSelections={regionSelections}
              serviceRegions={serviceRegions}
              disabled={disabled}
              onTargetCountChange={setTargetCount}
              onIncludeShortChange={setIncludeShort}
              onIncludeLongTailChange={setIncludeLongTail}
              onRegionModeChange={setRegionMode}
              onRegionSelectionsChange={setRegionSelections}
            />
          </Space>
          <Space wrap style={{ marginTop: 20 }}>
            <Button
              type="primary"
              loading={busy}
              disabled={disabled}
              onClick={() => void startGeneration(false)}
            >
              AI 生成关键词
            </Button>
            {generation ? (
              <Tag color={generation.status === "succeeded" ? "green" : "blue"}>
                {keywordJobStatusLabel[generation.status]}
              </Tag>
            ) : null}
            {regenerationConfirmation ? (
              <Popconfirm
                title="确认消耗一次关键词再生成额度？"
                description="任务成功后才会扣除，失败会释放额度。"
                okText="确认再生成"
                cancelText="取消"
                onConfirm={() => void startGeneration(true)}
              >
                <Button danger disabled={disabled}>
                  确认消耗额度并再生成
                </Button>
              </Popconfirm>
            ) : null}
          </Space>
        </Card>
      ) : null}

      {stage === "custom" ? (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Card title="手工添加">
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <div>
                <Typography.Text strong>关键词 *</Typography.Text>
                <Input
                  aria-label="手工关键词"
                  value={manualText}
                  disabled={disabled}
                  placeholder="输入一个关键词"
                  style={{ marginTop: 8 }}
                  onChange={(event) => setManualText(event.target.value)}
                />
              </div>
              <div>
                <Typography.Text strong>关键词类别 *</Typography.Text>
                <Select
                  aria-label="手工关键词分类"
                  value={manualCategory}
                  disabled={disabled}
                  options={keywordBusinessCategoryOptions}
                  placeholder="选择关键词分类"
                  style={{ width: "100%", marginTop: 8 }}
                  onChange={setManualCategory}
                />
              </div>
              <div>
                <Typography.Text strong>用户意图（可多选）*</Typography.Text>
                <Select
                  aria-label="手工用户意图"
                  mode="multiple"
                  value={manualIntents}
                  disabled={disabled}
                  options={keywordSearchIntentOptions}
                  placeholder="选择用户意图（可多选）"
                  style={{ width: "100%", marginTop: 8 }}
                  onChange={setManualIntents}
                />
              </div>
              <div>
                <Typography.Text strong>关键词长度 *</Typography.Text>
                <Select
                  aria-label="手工关键词长度"
                  value={manualLength}
                  disabled={disabled}
                  options={[
                    { value: "short", label: "短关键词" },
                    { value: "long_tail", label: "长尾关键词" },
                  ]}
                  style={{ width: 180, marginTop: 8 }}
                  onChange={setManualLength}
                />
              </div>
              <div>
                <Typography.Text strong>地域（可选）</Typography.Text>
                <div style={{ marginTop: 8 }}>
                  <KeywordRegionSelector
                    mode="custom"
                    serviceRegions={serviceRegions}
                    value={manualRegions}
                    disabled={disabled}
                    onChange={setManualRegions}
                  />
                </div>
              </div>
              <div>
                <Typography.Text strong>备注（可选）</Typography.Text>
                <Input.TextArea
                  aria-label="手工关键词备注"
                  value={manualNotes}
                  disabled={disabled}
                  rows={2}
                  maxLength={1000}
                  placeholder="补充说明"
                  style={{ marginTop: 8 }}
                  onChange={(event) => setManualNotes(event.target.value)}
                />
              </div>
              <Button type="primary" loading={busy} disabled={disabled} onClick={addManualKeyword}>
                添加关键词
              </Button>
            </Space>
          </Card>

          <Card title="批量添加">
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <div>
                <Typography.Text strong>关键词（每行一个）*</Typography.Text>
                <Input.TextArea
                  aria-label="批量关键词"
                  value={batchText}
                  disabled={disabled}
                  rows={6}
                  placeholder={"GEO优化\nAI搜索优化\nGEO优化公司\n广州GEO服务\nAI搜索排名优化"}
                  style={{ marginTop: 8 }}
                  onChange={(event) => setBatchText(event.target.value)}
                />
              </div>
              <div>
                <Typography.Text strong>默认关键词类别 *</Typography.Text>
                <Select
                  aria-label="批量关键词分类"
                  value={batchCategory}
                  disabled={disabled}
                  options={keywordBusinessCategoryOptions}
                  placeholder="选择默认关键词类别"
                  style={{ width: "100%", marginTop: 8 }}
                  onChange={setBatchCategory}
                />
              </div>
              <div>
                <Typography.Text strong>默认用户意图（可多选）*</Typography.Text>
                <Select
                  aria-label="批量用户意图"
                  mode="multiple"
                  value={batchIntents}
                  disabled={disabled}
                  options={keywordSearchIntentOptions}
                  placeholder="选择默认用户意图"
                  style={{ width: "100%", marginTop: 8 }}
                  onChange={setBatchIntents}
                />
              </div>
              <div>
                <Typography.Text strong>默认关键词长度 *</Typography.Text>
                <Select
                  aria-label="批量关键词长度"
                  value={batchLength}
                  disabled={disabled}
                  options={[
                    { value: "short", label: "短关键词" },
                    { value: "long_tail", label: "长尾关键词" },
                  ]}
                  style={{ width: 180, marginTop: 8 }}
                  onChange={setBatchLength}
                />
              </div>
              <div>
                <Typography.Text strong>默认地域（可选）</Typography.Text>
                <div style={{ marginTop: 8 }}>
                  <KeywordRegionSelector
                    mode="custom"
                    serviceRegions={serviceRegions}
                    value={batchRegions}
                    disabled={disabled}
                    onChange={setBatchRegions}
                  />
                </div>
              </div>
              <Button type="primary" loading={busy} disabled={disabled} onClick={addBatchKeywords}>
                批量添加
              </Button>
            </Space>
          </Card>

          <Card title="待蒸馏关键词">
            {items.length ? (
              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                {items.map((item, index) => (
                  <Card key={item.id ?? `${item.text}-${index}`} size="small">
                    <Space wrap>
                      <Typography.Text strong>{item.text}</Typography.Text>
                      <Tag>{item.structure_type === "long_tail" ? "长尾关键词" : "短关键词"}</Tag>
                      {item.business_category ? (
                        <Tag color="blue">{categoryLabel(item.business_category)}</Tag>
                      ) : null}
                      {itemIntents(item).map((intent) => (
                        <Tag key={intent} color="purple">
                          {intentLabel(intent)}
                        </Tag>
                      ))}
                      {(item.regions ?? []).map((region) => (
                        <Tag key={region.path.map((node) => node.code).join("/")} color="cyan">
                          {region.path.map((node) => node.name).join(" / ")}
                        </Tag>
                      ))}
                      <Tag>{sourceLabels[item.source ?? "legacy"] ?? "已有关键词"}</Tag>
                    </Space>
                  </Card>
                ))}
              </Space>
            ) : (
              <Typography.Text type="secondary">
                暂无待蒸馏关键词，可通过单条或批量方式添加。
              </Typography.Text>
            )}
          </Card>
        </Space>
      ) : null}

      {stage === "distill" ? (
        <DistillationPanel
          subjectId={params.id}
          keywordDirty={false}
          onDirtyChange={setDistillationDirty}
        />
      ) : null}
      {stage === "questions" ? (
        <QuestionBankPanel subjectId={params.id} upstreamDirty={distillationDirty} />
      ) : null}
      {stage === "assets" ? (
        <Card title="关键词资产">
          {assets.length ? (
            <Space direction="vertical" style={{ width: "100%" }} size="middle">
              <Typography.Text type="secondary">
                这里只展示当前主体已确认的蒸馏结果；问题库只读取这组稳定关键词资产。
              </Typography.Text>
              <Tag color="green">资产数量 {assets.length}</Tag>
              {assets.map((asset) => {
                const editing = editingAssetId === asset.id;
                const viewing = viewingAssetId === asset.id;
                return (
                  <Card key={asset.id} size="small">
                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                      {editing ? (
                        <>
                          <Input
                            aria-label={`编辑关键词-${asset.id}`}
                            value={assetText}
                            disabled={busy}
                            onChange={(event) => setAssetText(event.target.value)}
                          />
                          <Space wrap>
                            <Select
                              aria-label={`编辑分类-${asset.id}`}
                              value={assetCategory}
                              disabled={busy}
                              options={keywordBusinessCategoryOptions}
                              placeholder="选择关键词分类"
                              style={{ minWidth: 200 }}
                              onChange={setAssetCategory}
                            />
                            <Select
                              aria-label={`编辑意图-${asset.id}`}
                              mode="multiple"
                              value={assetIntents}
                              disabled={busy}
                              options={keywordSearchIntentOptions}
                              placeholder="选择用户意图"
                              style={{ minWidth: 320 }}
                              onChange={setAssetIntents}
                            />
                          </Space>
                          <Space>
                            <Button
                              type="primary"
                              disabled={busy || !assetText.trim()}
                              onClick={() =>
                                void patchAsset(asset, {
                                  displayText: assetText.trim(),
                                  category: assetCategory ?? "",
                                  intents: assetIntents,
                                })
                              }
                            >
                              保存
                            </Button>
                            <Button disabled={busy} onClick={() => setEditingAssetId(undefined)}>
                              取消
                            </Button>
                          </Space>
                        </>
                      ) : (
                        <>
                          <Space wrap>
                            <Typography.Text strong>{asset.text}</Typography.Text>
                            <Tag color={asset.enabled ? "green" : "default"}>
                              {asset.enabled ? "已启用" : "已停用"}
                            </Tag>
                            <Tag color={asset.usable_for_questions ? "blue" : "default"}>
                              {asset.usable_for_questions ? "用于问题生成" : "未用于问题生成"}
                            </Tag>
                          </Space>
                          {viewing ? (
                            <Space direction="vertical" size="small" style={{ width: "100%" }}>
                              <Space wrap>
                                {asset.category ? <Tag>{categoryLabel(asset.category)}</Tag> : null}
                                {asset.intents.map((intent) => (
                                  <Tag key={intent} color="purple">
                                    {intentLabel(intent)}
                                  </Tag>
                                ))}
                                {asset.regions.map((region) => (
                                  <Tag
                                    key={region.path.map((node) => node.code).join("/")}
                                    color="cyan"
                                  >
                                    {region.path.map((node) => node.name).join(" / ")}
                                  </Tag>
                                ))}
                              </Space>
                              <Typography.Text>
                                相关关键词：{asset.related_keywords.join("、") || "暂无"}
                              </Typography.Text>
                              <Typography.Text>
                                目标人群：{asset.audiences.join("、") || "暂无"}
                              </Typography.Text>
                              <Typography.Text>
                                使用场景：{asset.scenarios.join("、") || "暂无"}
                              </Typography.Text>
                              <Typography.Text type="secondary">
                                来源：{sourceLabels[asset.source] ?? "蒸馏确认"} · 更新时间：
                                {formatUpdatedAt(asset.updated_at)}
                              </Typography.Text>
                            </Space>
                          ) : null}
                          <Space wrap>
                            <Button
                              size="small"
                              onClick={() =>
                                setViewingAssetId((current) =>
                                  current === asset.id ? undefined : asset.id,
                                )
                              }
                            >
                              {viewing ? "收起" : "查看"}
                            </Button>
                            <Button
                              size="small"
                              disabled={busy}
                              onClick={() => beginAssetEdit(asset)}
                            >
                              编辑
                            </Button>
                            <Button
                              size="small"
                              disabled={busy}
                              onClick={() => void patchAsset(asset, { enabled: !asset.enabled })}
                            >
                              {asset.enabled ? "停用" : "启用"}
                            </Button>
                            <Button
                              size="small"
                              disabled={busy}
                              onClick={() =>
                                void patchAsset(asset, {
                                  usableForQuestions: !asset.usable_for_questions,
                                })
                              }
                            >
                              {asset.usable_for_questions ? "取消用于问题生成" : "选择用于问题生成"}
                            </Button>
                            <Popconfirm
                              title="删除关键词资产？"
                              description="删除后将不再用于问题生成。"
                              okText="确认删除"
                              cancelText="取消"
                              onConfirm={() => void patchAsset(asset, { deleted: true })}
                            >
                              <Button danger size="small" disabled={busy}>
                                删除
                              </Button>
                            </Popconfirm>
                          </Space>
                        </>
                      )}
                    </Space>
                  </Card>
                );
              })}
            </Space>
          ) : (
            <Typography.Text type="secondary">
              暂无关键词资产，请先添加关键词并确认蒸馏结果。
            </Typography.Text>
          )}
        </Card>
      ) : null}
    </main>
  );
}

export default function SmartKeywordPage() {
  return <KeywordCenterPage />;
}
