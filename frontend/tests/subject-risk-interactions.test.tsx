// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import SubjectReviewDetailPage from "../app/admin/subject-reviews/[id]/page";
import SubjectRiskCatalogPage from "../app/admin/subject-risk/page";

const mocks = vi.hoisted(() => ({
  context: { permission_keys: [] as string[] },
  push: vi.fn(),
  getCatalog: vi.fn(),
  getTypes: vi.fn(),
  getRules: vi.fn(),
  createType: vi.fn(),
  createRule: vi.fn(),
  updateType: vi.fn(),
  updateRule: vi.fn(),
  publish: vi.fn(),
  getReview: vi.fn(),
  approve: vi.fn(),
  reject: vi.fn(),
  userMessage: vi.fn((error: unknown) =>
    error instanceof Error ? error.message : "\u64cd\u4f5c\u5931\u8d25",
  ),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "review-1" }),
  useRouter: () => ({ push: mocks.push }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/components/admin/admin-capability", () => ({
  useAdminCapabilities: () => mocks.context,
}));
vi.mock("@/lib/auth-client", () => ({ userMessage: mocks.userMessage }));
vi.mock("@/lib/subject-risk-client", () => ({
  getSubjectRiskCatalog: mocks.getCatalog,
  getSubjectRiskTypes: mocks.getTypes,
  getSubjectRiskRules: mocks.getRules,
  createSubjectRiskType: mocks.createType,
  createSubjectRiskRule: mocks.createRule,
  updateSubjectRiskType: mocks.updateType,
  updateSubjectRiskRule: mocks.updateRule,
  publishSubjectRiskCatalog: mocks.publish,
  getSubjectReview: mocks.getReview,
  approveSubjectReview: mocks.approve,
  rejectSubjectReview: mocks.reject,
}));

const catalog = { version: 4, published_revision: null };
const riskType = {
  id: "type-1",
  key: "test.restricted",
  name: "\u6d4b\u8bd5\u98ce\u9669",
  description: "",
  enabled: false,
  manual_review_required: true,
  allow_geo_detection: false,
  allow_article_generation: false,
  allow_image_generation: false,
  require_authoritative_citations: true,
  require_disclaimer: true,
  sort_order: 0,
  version: 1,
};
const review = {
  id: "review-1",
  user_id: "user-1",
  subject_id: "subject-1",
  subject_version_id: "version-1",
  version_no: 1,
  official_name: "\u6d4b\u8bd5\u4e3b\u4f53",
  status: "pending" as const,
  reason_types: ["data_conflict"],
  review_evidence: [
    {
      risk_type_key: "test.restricted",
      rule_key: "test.rule",
      reason_type: "data_conflict",
      field_key: "name",
    },
  ],
  public_reason: "",
  internal_note: "",
  version: 3,
  reviewed_at: null,
  created_at: "2026-08-11T00:00:00Z",
  updated_at: "2026-08-11T00:00:00Z",
};

beforeAll(() => {
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    nativeGetComputedStyle(element),
  );
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: () => ({
      matches: false,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
  Element.prototype.scrollTo = vi.fn();
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.context.permission_keys = [
    "subject_risk.catalog.view",
    "subject_risk.catalog.update",
    "subject_risk.catalog.publish",
    "subject_reviews.review",
  ];
  mocks.getCatalog.mockResolvedValue(catalog);
  mocks.getTypes.mockResolvedValue({ catalog_version: 4, risk_types: [riskType] });
  mocks.getRules.mockResolvedValue({ catalog_version: 4, rules: [] });
  mocks.createType.mockResolvedValue(riskType);
  mocks.publish.mockResolvedValue({ approval_id: "approval-9" });
  mocks.getReview.mockResolvedValue(review);
  mocks.approve.mockResolvedValue({ ...review, status: "approved", version: 4 });
  mocks.reject.mockResolvedValue({ ...review, status: "rejected", version: 4 });
});

afterEach(cleanup);

describe("subject risk catalog interactions", () => {
  it("creates only a restrictive draft type and sends publication through two-person approval", async () => {
    render(<SubjectRiskCatalogPage />);
    expect(await screen.findByText("test.restricted")).toBeTruthy();
    await userEvent.type(screen.getByPlaceholderText("machine.key"), "test.new");
    await userEvent.type(screen.getByPlaceholderText("\u540d\u79f0"), "\u65b0\u98ce\u9669");
    await userEvent.click(screen.getAllByRole("button", { name: /\u521b\s*\u5efa/ })[0]);
    await waitFor(() =>
      expect(mocks.createType).toHaveBeenCalledWith(
        4,
        expect.objectContaining({
          key: "test.new",
          enabled: false,
          manual_review_required: true,
          allow_geo_detection: false,
        }),
      ),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "\u53d1\u8d77\u53cc\u4eba\u53d1\u5e03\u5ba1\u6279" }),
    );
    await waitFor(() => expect(mocks.publish).toHaveBeenCalledWith(4));
    expect(mocks.push).toHaveBeenCalledWith("/admin/approvals/approval-9");
  });

  it("disables draft mutation and publication without capability keys", async () => {
    mocks.context.permission_keys = ["subject_risk.catalog.view"];
    render(<SubjectRiskCatalogPage />);
    expect(
      await screen.findByText("\u5f53\u524d\u8d26\u53f7\u65e0\u53d1\u5e03\u6743\u9650"),
    ).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: "\u53d1\u8d77\u53cc\u4eba\u53d1\u5e03\u5ba1\u6279",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (screen.getAllByRole("button", { name: /\u521b\s*\u5efa/ })[0] as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

describe("direct subject review interactions", () => {
  it("approves directly with expected_version instead of creating an ApprovalRequest", async () => {
    render(<SubjectReviewDetailPage />);
    expect(await screen.findByText("\u6d4b\u8bd5\u4e3b\u4f53")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /\u901a\s*\u8fc7/ }));
    await waitFor(() => expect(mocks.approve).toHaveBeenCalledWith(review, "", ""));
    expect(mocks.publish).not.toHaveBeenCalled();
  });

  it("requires a rejection reason and renders a stable permission failure", async () => {
    render(<SubjectReviewDetailPage />);
    await screen.findByText("\u6d4b\u8bd5\u4e3b\u4f53");
    await userEvent.click(screen.getByRole("button", { name: /\u62d2\s*\u7edd/ }));
    expect(
      screen.getByText(
        "\u62d2\u7edd\u65f6\u5fc5\u987b\u586b\u5199\u5bf9\u7528\u6237\u516c\u5f00\u7684\u539f\u56e0",
      ),
    ).toBeTruthy();
    expect(mocks.reject).not.toHaveBeenCalled();

    mocks.approve.mockRejectedValueOnce(new Error("\u65e0\u6743\u6267\u884c\u8be5\u64cd\u4f5c"));
    await userEvent.click(screen.getByRole("button", { name: /\u901a\s*\u8fc7/ }));
    expect(await screen.findByText("\u65e0\u6743\u6267\u884c\u8be5\u64cd\u4f5c")).toBeTruthy();
  });

  it("prevents review actions without subject_reviews.review", async () => {
    mocks.context.permission_keys = [];
    render(<SubjectReviewDetailPage />);
    expect(
      await screen.findByText("\u5f53\u524d\u8d26\u53f7\u65e0\u4e3b\u4f53\u5ba1\u6838\u6743\u9650"),
    ).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /\u901a\s*\u8fc7/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: /\u62d2\s*\u7edd/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
describe("subject review evidence boundaries", () => {
  it("renders safe evidence and submits public reason separately from the internal note", async () => {
    mocks.reject.mockResolvedValueOnce({
      ...review,
      status: "rejected",
      public_reason: "\u8bf7\u6838\u5bf9\u516c\u5f00\u8d44\u6599",
      internal_note: "\u4ec5\u7ba1\u7406\u5458\u53ef\u89c1\u7ebf\u7d22",
      version: 4,
    });
    render(<SubjectReviewDetailPage />);

    expect(await screen.findByText(/test\.restricted \/ test\.rule \/ name/)).toBeTruthy();
    await userEvent.type(
      screen.getByLabelText("\u5bf9\u7528\u6237\u516c\u5f00\u7684\u539f\u56e0"),
      "\u8bf7\u6838\u5bf9\u516c\u5f00\u8d44\u6599",
    );
    await userEvent.type(
      screen.getByLabelText("\u4ec5\u7ba1\u7406\u5458\u53ef\u89c1\u7684\u5907\u6ce8"),
      "\u4ec5\u7ba1\u7406\u5458\u53ef\u89c1\u7ebf\u7d22",
    );
    await userEvent.click(screen.getByRole("button", { name: /\u62d2\s*\u7edd/ }));

    await waitFor(() =>
      expect(mocks.reject).toHaveBeenCalledWith(
        review,
        "\u8bf7\u6838\u5bf9\u516c\u5f00\u8d44\u6599",
        "\u4ec5\u7ba1\u7406\u5458\u53ef\u89c1\u7ebf\u7d22",
      ),
    );
    expect(await screen.findByText("\u8bf7\u6838\u5bf9\u516c\u5f00\u8d44\u6599")).toBeTruthy();
    expect(screen.getByText("\u4ec5\u7ba1\u7406\u5458\u53ef\u89c1\u7ebf\u7d22")).toBeTruthy();
  });
});
