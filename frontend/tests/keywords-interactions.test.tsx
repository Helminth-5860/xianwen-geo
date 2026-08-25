// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SmartKeywordPage, { KeywordCenterPage } from "@/app/subjects/[id]/keywords/page";

const api = vi.hoisted(() => ({
  appendKeywordCandidates: vi.fn(),
  createKeywordGeneration: vi.fn(),
  getKeywordAssets: vi.fn(),
  getKeywordDraft: vi.fn(),
  getKeywordGenerationJob: vi.fn(),
  updateKeywordAsset: vi.fn(),
}));

vi.mock("@/lib/keywords-client", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/keywords-client")>("@/lib/keywords-client");
  return { ...actual, ...api };
});
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "subject-1" }) }));
vi.mock("@/components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => ({
    currentSubject: {
      id: "subject-1",
      official_name: "示例企业",
      subject_type: { name: "企业" },
      service_regions: JSON.stringify({ version: 1, nationwide: true, areas: [] }),
    },
  }),
}));
vi.mock("@/components/keyword-region-selector", async () => {
  const actual = await vi.importActual<typeof import("@/components/keyword-region-selector")>(
    "@/components/keyword-region-selector",
  );
  return {
    ...actual,
    KeywordRegionSelector: ({
      mode,
      onChange,
    }: {
      mode?: "subject" | "custom";
      onChange: (
        value: Array<{
          code: string;
          name: string;
          level: "district";
          path: Array<{ code: string; name: string }>;
        }>,
      ) => void;
    }) => (
      <button
        type="button"
        onClick={() =>
          onChange([
            {
              code: "440106",
              name: "天河区",
              level: "district",
              path: [
                { code: "440000", name: "广东省" },
                { code: "440100", name: "广州市" },
                { code: "440106", name: "天河区" },
              ],
            },
          ])
        }
      >
        {mode === "subject" ? "使用主体服务区域" : "选择自定义地域"}
      </button>
    ),
  };
});
vi.mock("@/app/subjects/[id]/keywords/distillation-panel", () => ({
  default: () => <div>蒸馏页面</div>,
}));
vi.mock("@/app/subjects/[id]/keywords/question-bank-panel", () => ({
  default: () => null,
}));

const item = {
  id: "keyword-1",
  text: "GEO",
  structure_type: "short" as const,
  is_regional: false,
  region_level: null,
  region_text: null,
  regions: [],
  base_keyword_text: null,
  business_category: "entity",
  search_intent: "informational" as const,
  search_intents: ["informational" as const],
  source: "manual" as const,
  notes: "",
  relevance_score: null,
  priority: null,
  ai_reason: null,
  sort_order: 0,
};

const draft = {
  version: 1,
  subject_version: { id: "sv-1", version_no: 2, official_name: "示例企业" },
  draft_subject_version: { id: "sv-1", version_no: 2, official_name: "示例企业" },
  current_keyword_version_no: 1,
  can_write: true,
  read_only_reason: null,
  items: [item],
};

const asset = {
  id: "asset-1",
  text: "GEO 品牌咨询",
  source_text: "GEO 品牌咨询",
  related_keywords: ["AI 搜索品牌咨询"],
  audiences: ["品牌负责人"],
  scenarios: ["企业品牌推广"],
  category: "entity",
  intents: ["informational" as const],
  regions: [],
  source: "distillation",
  enabled: true,
  usable_for_questions: true,
  deleted: false,
  updated_at: "2026-08-25T00:00:00Z",
};

const succeededJob = {
  id: "job-1",
  subject_id: "subject-1",
  subject_version_id: "sv-1",
  status: "succeeded" as const,
  version: 1,
  stable_error_code: "",
  billing: { billing_mode: "free_initial" as const, held: false, remaining: 2 },
  configuration: {
    target_count: 10,
    include_short: true,
    include_long_tail: true,
    include_regional: true,
    regions: [],
    generation_mode: "smart" as const,
    categories: [],
    intents: [],
    region_mode: "subject" as const,
  },
  provenance: {
    provider_key: "provider",
    model_key: "model",
    adapter_version: "1",
    prompt_version: "keyword-generation-v1",
  },
  result: { item_count: 1, applied_keyword_set_version: 2 },
  attempts: 1,
  created_at: "2026-08-25T00:00:00Z",
  updated_at: "2026-08-25T00:00:01Z",
  finished_at: "2026-08-25T00:00:01Z",
};

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  Object.defineProperty(globalThis, "ResizeObserver", {
    writable: true,
    value: class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  });
  vi.clearAllMocks();
  api.getKeywordDraft.mockResolvedValue(draft);
  api.getKeywordAssets.mockResolvedValue({ items: [] });
  api.createKeywordGeneration.mockResolvedValue(succeededJob);
  api.appendKeywordCandidates.mockResolvedValue({
    candidate_pool: { ...draft, version: 2 },
    added_count: 1,
    skipped_duplicates: [],
  });
  api.updateKeywordAsset.mockImplementation(
    async (_subjectId: string, _assetId: string, patch: Record<string, unknown>) => ({
      ...asset,
      text: patch.displayText ?? asset.text,
      category: patch.category ?? asset.category,
      intents: patch.intents ?? asset.intents,
      enabled: patch.enabled ?? asset.enabled,
      usable_for_questions: patch.usableForQuestions ?? asset.usable_for_questions,
      deleted: patch.deleted ?? asset.deleted,
    }),
  );
});

afterEach(cleanup);

describe("关键词中心四页", () => {
  it("智能关键词提供数量、长度和三种地域模式，并直接生成待蒸馏关键词", async () => {
    render(<SmartKeywordPage />);

    expect(await screen.findByRole("heading", { name: "智能关键词" })).toBeTruthy();
    for (const label of ["10 个", "20 个", "50 个", "100 个"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    expect(screen.getByLabelText("自定义生成数量")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "短关键词" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "长尾关键词" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "不限地域" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "使用主体服务区域" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "自定义地域" })).toBeTruthy();
    expect(screen.queryByText("草稿")).toBeNull();
    expect(screen.queryByText("版本历史")).toBeNull();
    expect(screen.queryByText("当前批次")).toBeNull();

    await userEvent.click(screen.getByRole("radio", { name: "不限地域" }));
    await userEvent.click(screen.getByRole("button", { name: "一键生成关键词" }));

    await waitFor(() => expect(api.createKeywordGeneration).toHaveBeenCalledTimes(1));
    expect(api.createKeywordGeneration.mock.calls[0][1]).toMatchObject({
      targetCount: 10,
      includeShort: true,
      includeLongTail: true,
      regionMode: "unrestricted",
      generationMode: "smart",
      regions: [],
    });
    expect(await screen.findByText("关键词已生成并加入待蒸馏关键词")).toBeTruthy();
  });

  it("自定义 AI 生成直接展示四组 14 类与 8 类用户意图", async () => {
    render(<KeywordCenterPage stage="custom" />);

    expect(await screen.findByRole("heading", { name: "自定义关键词" })).toBeTruthy();
    for (const group of ["品牌与业务", "服务与能力", "需求与场景", "竞争与信任"]) {
      expect(screen.getByText(group)).toBeTruthy();
    }
    for (const category of [
      "企业与品牌",
      "行业与赛道",
      "产品或服务类别",
      "具体产品",
      "具体服务",
      "能力与功能",
      "目标与收益",
      "问题与痛点",
      "解决方案",
      "使用场景",
      "目标人群",
      "竞品与替代",
      "信任与口碑",
      "知识与教育",
    ]) {
      expect(screen.getByRole("checkbox", { name: category })).toBeTruthy();
    }
    for (const intent of [
      "信息了解",
      "推荐评估",
      "对比选择",
      "交易转化",
      "地域本地",
      "导航联系",
      "信任口碑",
      "使用服务",
    ]) {
      expect(screen.getByRole("checkbox", { name: intent })).toBeTruthy();
    }

    await userEvent.click(screen.getByRole("button", { name: "全部选择" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "信息了解" }));
    await userEvent.click(screen.getByRole("radio", { name: "不限地域" }));
    await userEvent.click(screen.getByRole("button", { name: "生成自定义关键词" }));

    await waitFor(() => expect(api.createKeywordGeneration).toHaveBeenCalledTimes(1));
    expect(api.createKeywordGeneration.mock.calls[0][1]).toMatchObject({
      generationMode: "custom",
      categories: [
        "entity",
        "industry",
        "product_category",
        "product",
        "service",
        "capability",
        "goal",
        "pain_point",
        "solution",
        "scenario",
        "audience",
        "competitor",
        "trust",
        "knowledge",
      ],
      intents: ["informational"],
    });
  });

  it("批量添加明确合并本地和服务端重复项提示", async () => {
    api.appendKeywordCandidates.mockResolvedValue({
      candidate_pool: { ...draft, version: 2 },
      added_count: 2,
      skipped_duplicates: ["已有词"],
    });
    render(<KeywordCenterPage stage="custom" />);
    expect(await screen.findByRole("heading", { name: "自定义关键词" })).toBeTruthy();

    await userEvent.type(screen.getByLabelText("批量关键词"), "新词一\n新词一\n新词二");
    await userEvent.click(screen.getByLabelText("批量关键词分类"));
    await userEvent.click(
      await screen.findByText("企业与品牌", { selector: ".ant-select-item-option-content" }),
    );
    await userEvent.click(screen.getByLabelText("批量用户意图"));
    await userEvent.click(
      await screen.findByText("信息了解", { selector: ".ant-select-item-option-content" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "批量加入待蒸馏关键词" }));

    await waitFor(() => expect(api.appendKeywordCandidates).toHaveBeenCalledTimes(1));
    expect(api.appendKeywordCandidates.mock.calls[0][1].items).toHaveLength(2);
    expect(
      await screen.findByText("已加入 2 个待蒸馏关键词，跳过 1 个重复词；另跳过 1 个本地重复项"),
    ).toBeTruthy();
  });

  it("关键词资产支持查看、编辑、启停、问题生成选择和删除", async () => {
    api.getKeywordAssets.mockResolvedValue({ items: [asset] });
    render(<KeywordCenterPage stage="assets" />);

    expect(await screen.findByRole("heading", { name: "关键词资产" })).toBeTruthy();
    expect(screen.getByText("GEO 品牌咨询")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /查\s*看/ }));
    expect(screen.getByText("相关关键词：AI 搜索品牌咨询")).toBeTruthy();
    expect(screen.getByText("目标人群：品牌负责人")).toBeTruthy();
    expect(screen.getByText("使用场景：企业品牌推广")).toBeTruthy();
    expect(screen.getByText(/来源：蒸馏确认 · 更新时间：/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /停\s*用/ }));
    await waitFor(() =>
      expect(api.updateKeywordAsset).toHaveBeenCalledWith("subject-1", "asset-1", {
        enabled: false,
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "取消用于问题生成" }));
    await waitFor(() =>
      expect(api.updateKeywordAsset).toHaveBeenCalledWith("subject-1", "asset-1", {
        usableForQuestions: false,
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: /编\s*辑/ }));
    await userEvent.clear(screen.getByLabelText("编辑关键词-asset-1"));
    await userEvent.type(screen.getByLabelText("编辑关键词-asset-1"), "更新后的关键词");
    await userEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
    await waitFor(() =>
      expect(api.updateKeywordAsset).toHaveBeenCalledWith(
        "subject-1",
        "asset-1",
        expect.objectContaining({ displayText: "更新后的关键词" }),
      ),
    );

    await userEvent.click(screen.getByRole("button", { name: /删\s*除/ }));
    await userEvent.click(await screen.findByRole("button", { name: "确认删除" }));
    await waitFor(() =>
      expect(api.updateKeywordAsset).toHaveBeenCalledWith("subject-1", "asset-1", {
        deleted: true,
      }),
    );
  });

  it("AI 返回结构异常时只显示明确中文，不暴露英文错误码", async () => {
    const queued = { ...succeededJob, status: "queued" as const, result: null, finished_at: null };
    api.createKeywordGeneration.mockResolvedValue(queued);
    api.getKeywordGenerationJob.mockResolvedValue({
      ...queued,
      status: "failed",
      stable_error_code: "KEYWORD_GENERATION_INVALID_RESPONSE",
    });
    render(<SmartKeywordPage />);
    expect(await screen.findByRole("heading", { name: "智能关键词" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "一键生成关键词" }));

    expect(
      await screen.findByText("AI 返回格式异常，请重新生成。", {}, { timeout: 2500 }),
    ).toBeTruthy();
    expect(screen.queryByText("KEYWORD_GENERATION_INVALID_RESPONSE")).toBeNull();
  });
});
