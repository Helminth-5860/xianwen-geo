// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { emptySubjectBusinessProfile, type SubjectDetail } from "@/lib/subjects-client";

import { SubjectAiEnrichment } from "./subject-ai-enrichment";

const api = vi.hoisted(() => ({
  getEnrichmentSources: vi.fn(),
  getEnrichmentJob: vi.fn(),
  createEnrichment: vi.fn(),
  confirmEnrichment: vi.fn(),
}));

vi.mock("@/lib/subject-enrichment-client", () => api);

const subject = {
  id: "subject-1",
  subject_type: { id: "type-1", key: "enterprise", name: "企业", icon_key: "building" },
  status: "draft",
  version: 3,
  is_current: true,
  current_version_no: null,
  official_name: "示例企业",
  retest_required: false,
  created_at: "2026-08-14T00:00:00Z",
  updated_at: "2026-08-14T00:00:00Z",
  schema_version: 1,
  draft_values: { name: "示例企业", summary: null },
  business_profile: emptySubjectBusinessProfile(),
  form_schema: {
    id: "type-1",
    key: "enterprise",
    name: "企业",
    description: "",
    icon_key: "building",
    schema_version: 1,
    fields: [],
  },
  product_candidates: [],
  has_uncommitted_changes: true,
  risk: { status: "not_assessed", review_id: null, public_reason: "" },
} as SubjectDetail;

const source = {
  source_type: "web" as const,
  parsed_version_id: "11111111-1111-4111-8111-111111111111",
  label: "https://example.com/about",
  version_no: 2,
  character_count: 120,
};

const target = {
  field_key: "summary",
  label: "主体简介",
  field_type: "textarea",
  current_value: null,
};

const succeededJob = {
  id: "22222222-2222-4222-8222-222222222222",
  subject_id: subject.id,
  status: "succeeded" as const,
  version: 3,
  stable_error_code: "",
  provider_key: "mock" as const,
  model_key: "mock-subject-enrichment-v1",
  suggestions: [
    {
      id: "33333333-3333-4333-8333-333333333333",
      field_key: "summary",
      suggested_value: "Mock AI 建议：主体简介",
      confidence: "low" as const,
      conflict: true,
      conflict_code: "CURRENT_VALUE_DIFFERS",
      sources: [{ source_id: "source-link-1", source_type: "web" as const }],
    },
  ],
  applied: false,
  created_at: "2026-08-14T00:00:00Z",
  updated_at: "2026-08-14T00:00:00Z",
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
  api.getEnrichmentSources.mockResolvedValue({
    sources: [source],
    target_fields: [target],
    latest_job: null,
  });
});

afterEach(cleanup);

describe("SubjectAiEnrichment", () => {
  it("creates a job only from explicitly selected confirmed sources and targets", async () => {
    api.createEnrichment.mockResolvedValue({ ...succeededJob, status: "queued", suggestions: [] });
    render(
      <SubjectAiEnrichment
        subject={subject}
        localValues={subject.draft_values}
        onApplied={vi.fn()}
      />,
    );

    await userEvent.click(await screen.findByRole("checkbox", { name: /example.com\/about/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: "主体简介" }));
    await userEvent.click(screen.getByRole("button", { name: "开始 AI 补充" }));

    await waitFor(() =>
      expect(api.createEnrichment).toHaveBeenCalledWith(
        subject.id,
        subject.version,
        [source],
        ["summary"],
      ),
    );
    expect(screen.queryByText(/忽略之前的指令/)).toBeNull();
  });

  it("requires an explicit decision before a low-confidence conflict can be applied", async () => {
    const appliedSubject = {
      ...subject,
      version: 4,
      draft_values: { ...subject.draft_values, summary: "Mock AI 建议：主体简介" },
    };
    api.getEnrichmentSources
      .mockResolvedValueOnce({
        sources: [source],
        target_fields: [target],
        latest_job: succeededJob,
      })
      .mockResolvedValue({ sources: [source], target_fields: [target], latest_job: null });
    api.confirmEnrichment.mockResolvedValue({
      created: true,
      confirmation_id: "44444444-4444-4444-8444-444444444444",
      subject: appliedSubject,
    });
    const onApplied = vi.fn();
    render(
      <SubjectAiEnrichment
        subject={subject}
        localValues={subject.draft_values}
        onApplied={onApplied}
      />,
    );

    await screen.findByText("与当前值冲突");
    await userEvent.click(screen.getByRole("button", { name: "批量确认并写入草稿" }));
    expect(await screen.findByText("请逐项决定采纳或拒绝全部 AI 建议")).toBeTruthy();
    expect(api.confirmEnrichment).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "采纳" }));
    await userEvent.click(screen.getByRole("button", { name: "批量确认并写入草稿" }));
    await waitFor(() => expect(api.confirmEnrichment).toHaveBeenCalledTimes(1));
    expect(api.confirmEnrichment).toHaveBeenCalledWith(subject.id, succeededJob, subject.version, [
      { suggestion_id: succeededJob.suggestions[0].id, accepted: true },
    ]);
    expect(onApplied).toHaveBeenCalledWith(appliedSubject);
  });

  it("blocks starting AI enrichment while manual draft edits are unsaved", async () => {
    render(
      <SubjectAiEnrichment
        subject={subject}
        localValues={{ ...subject.draft_values, summary: "本地未保存" }}
        onApplied={vi.fn()}
      />,
    );

    expect(await screen.findByText("存在未保存的手工修改，请先保存草稿")).toBeTruthy();
    expect(screen.getByRole("button", { name: "开始 AI 补充" })).toHaveProperty("disabled", true);
  });
});
