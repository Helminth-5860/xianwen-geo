// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import ApprovalDetailPage from "../app/admin/approvals/[id]/page";
import ApprovalListPage from "../app/admin/approvals/page";
import AuditPage from "../app/admin/audit/page";
import RiskPoliciesPage from "../app/admin/risk-policies/page";

const mocks = vi.hoisted(() => ({
  context: {
    user_id: "approver-user",
    is_superuser: true,
    permission_keys: ["approvals.approve", "approvals.reject", "approvals.cancel"],
  },
  getApprovals: vi.fn(),
  getApproval: vi.fn(),
  approveApproval: vi.fn(),
  rejectApproval: vi.fn(),
  cancelApproval: vi.fn(),
  getRiskPolicies: vi.fn(),
  updateRiskPolicy: vi.fn(),
  getAuditEvents: vi.fn(),
  getAuditEvent: vi.fn(),
  userMessage: vi.fn((error: unknown) =>
    error instanceof Error ? error.message : "明确的无权限或服务错误",
  ),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "approval-1" }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/components/admin/admin-capability", () => ({
  useAdminCapabilities: () => mocks.context,
}));
vi.mock("@/lib/auth-client", () => ({
  userMessage: mocks.userMessage,
}));
vi.mock("@/lib/risk-client", () => ({
  getApprovals: mocks.getApprovals,
  getApproval: mocks.getApproval,
  approveApproval: mocks.approveApproval,
  rejectApproval: mocks.rejectApproval,
  cancelApproval: mocks.cancelApproval,
  getRiskPolicies: mocks.getRiskPolicies,
  updateRiskPolicy: mocks.updateRiskPolicy,
  getAuditEvents: mocks.getAuditEvents,
  getAuditEvent: mocks.getAuditEvent,
}));

const pagination = {
  page: 1,
  page_size: 20,
  count: 1,
  total_pages: 1,
};

const approval = {
  id: "approval-1",
  action_key: "user.freeze",
  policy_version: 3,
  requester_id: "requester-user",
  target_type: "user",
  target_id: "target-user",
  target_version: 2,
  safe_summary: "冻结目标用户",
  status: "pending" as const,
  expires_at: "2026-08-02T00:00:00Z",
  approved_by_id: null,
  approved_at: null,
  rejected_by_id: null,
  rejected_at: null,
  rejection_reason: "",
  cancelled_at: null,
  executed_at: null,
  execution_result: {},
  stable_error_code: "",
  request_id: "00000000-0000-4000-8000-000000000001",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const policy = {
  action_key: "user.freeze",
  current_mode: "confirm" as const,
  version: 2,
  supported_modes: ["confirm", "password", "two_person"] as const,
  default_mode: "confirm" as const,
  minimum_mode: "confirm" as const,
  updated_at: "2026-08-01T00:00:00Z",
};

const audit = {
  id: "audit-1",
  category: "approval",
  action_key: "user.freeze",
  outcome: "executed",
  actor_id: "actor",
  subject_id: "subject",
  requester_id: "requester",
  approver_id: "approver",
  target_type: "user",
  target_id: "target",
  request_id: "00000000-0000-4000-8000-000000000002",
  approval_request_id: "approval-1",
  safe_before: { status: "active" },
  safe_after: { status: "frozen" },
  stable_error_code: "",
  ip_fingerprint: "fingerprint-only",
  user_agent_digest: "digest-only",
  created_at: "2026-08-01T00:00:00Z",
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
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  Element.prototype.scrollTo = vi.fn();
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.context.user_id = "approver-user";
  mocks.context.is_superuser = true;
  mocks.getApprovals.mockResolvedValue({ results: [approval], pagination });
  mocks.getApproval.mockResolvedValue(approval);
  mocks.approveApproval.mockResolvedValue({ ...approval, status: "executed" });
  mocks.rejectApproval.mockResolvedValue({ ...approval, status: "rejected" });
  mocks.cancelApproval.mockResolvedValue({ ...approval, status: "cancelled" });
  mocks.getRiskPolicies.mockResolvedValue([policy]);
  mocks.updateRiskPolicy.mockResolvedValue({ ...policy, current_mode: "password", version: 3 });
  mocks.getAuditEvents.mockResolvedValue({ results: [audit], pagination });
  mocks.getAuditEvent.mockResolvedValue(audit);
});

afterEach(cleanup);

describe("high-risk approval list page", () => {
  it("loads rows, changes status filter and paginates with real DOM interaction", async () => {
    mocks.getApprovals.mockResolvedValue({
      results: [approval],
      pagination: { ...pagination, count: 40, total_pages: 2 },
    });
    const { container } = render(<ApprovalListPage />);
    await waitFor(() => expect(mocks.getApprovals).toHaveBeenCalledWith(1, ""));
    expect(screen.getByText("user.freeze")).toBeTruthy();
    expect(screen.getByText("冻结目标用户")).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("combobox"));
    const pendingOption = await waitFor(() => {
      const option = Array.from(
        document.querySelectorAll<HTMLElement>(".ant-select-item-option"),
      ).find((item) => item.textContent?.includes("待审批"));
      if (!option) throw new Error("pending option not rendered");
      return option;
    });
    await userEvent.click(pendingOption);
    await waitFor(() => expect(mocks.getApprovals).toHaveBeenCalledWith(1, "pending"));

    await userEvent.click(container.querySelector(".ant-pagination-item-2") as Element);
    await waitFor(() => expect(mocks.getApprovals).toHaveBeenCalledWith(2, "pending"));
  });

  it("renders an empty state", async () => {
    mocks.getApprovals.mockResolvedValueOnce({
      results: [],
      pagination: { ...pagination, count: 0 },
    });
    render(<ApprovalListPage />);
    await waitFor(() => expect(mocks.getApprovals).toHaveBeenCalled());
    expect(document.querySelectorAll("tbody tr.ant-table-row")).toHaveLength(0);
  });

  it.each([403, 429, 503])("renders unified list error %s", async (status) => {
    mocks.getApprovals.mockRejectedValueOnce(new Error(`服务错误 ${status}`));
    render(<ApprovalListPage />);
    expect(await screen.findByText(`服务错误 ${status}`)).toBeTruthy();
  });
});

describe("approval detail page", () => {
  it("approves with current password and never writes payload to browser storage", async () => {
    const { container } = render(<ApprovalDetailPage />);
    await screen.findByText("user.freeze");
    const password = container.querySelector('input[type="password"]') as HTMLInputElement;
    await userEvent.type(password, "temporary-current-password");
    const primary = container.querySelector("button.ant-btn-primary") as HTMLButtonElement;
    await userEvent.click(primary);
    await waitFor(() =>
      expect(mocks.approveApproval).toHaveBeenCalledWith(
        "approval-1",
        "temporary-current-password",
      ),
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("does not show self-approval controls and supports reject and cancel interactions", async () => {
    mocks.context.user_id = "requester-user";
    const { container } = render(<ApprovalDetailPage />);
    await screen.findByText("user.freeze");
    expect(container.querySelector('input[type="password"]')).toBeNull();
    const buttons = Array.from(container.querySelectorAll("button"));
    const cancel = buttons.at(-1) as HTMLButtonElement;
    await userEvent.click(cancel);
    const confirm = await waitFor(
      () => document.querySelector(".ant-modal-confirm-btns .ant-btn-primary") as HTMLButtonElement,
    );
    await userEvent.click(confirm);
    await waitFor(() => expect(mocks.cancelApproval).toHaveBeenCalledWith("approval-1"));
    cleanup();

    mocks.context.user_id = "approver-user";
    render(<ApprovalDetailPage />);
    await screen.findByText("user.freeze");
    const reason = document.querySelector("textarea") as HTMLTextAreaElement;
    await userEvent.type(reason, "资料不完整");
    const danger = document.querySelector("button.ant-btn-dangerous") as HTMLButtonElement;
    await userEvent.click(danger);
    await waitFor(() =>
      expect(mocks.rejectApproval).toHaveBeenCalledWith("approval-1", "资料不完整"),
    );
  });

  it.each(["stale", "expired", "execution_failed"])(
    "shows terminal %s without action controls",
    async (status) => {
      mocks.getApproval.mockResolvedValueOnce({
        ...approval,
        status,
        stable_error_code: `APPROVAL_${status.toUpperCase()}`,
      });
      const { container } = render(<ApprovalDetailPage />);
      await screen.findByText(status);
      expect(container.querySelector('input[type="password"]')).toBeNull();
    },
  );

  it.each([409, 410, 422, 429, 503])("shows operation error %s", async (status) => {
    mocks.approveApproval.mockRejectedValueOnce(new Error(`审批错误 ${status}`));
    const { container } = render(<ApprovalDetailPage />);
    await screen.findByText("user.freeze");
    await userEvent.type(
      container.querySelector('input[type="password"]') as HTMLInputElement,
      "temporary-password",
    );
    await userEvent.click(container.querySelector("button.ant-btn-primary") as HTMLButtonElement);
    expect(await screen.findByText(`审批错误 ${status}`)).toBeTruthy();
  });
});

describe("risk policy page", () => {
  it("renders supported/default/minimum/current, blocks below-minimum options and submits password", async () => {
    mocks.getRiskPolicies.mockResolvedValueOnce([
      { ...policy, minimum_mode: "password", current_mode: "password" },
    ]);
    const { container } = render(<RiskPoliciesPage />);
    await screen.findByText("user.freeze");
    expect(container.textContent).toContain("密码再验证");
    const adjust = container.querySelector("tbody button") as HTMLButtonElement;
    await userEvent.click(adjust);
    fireEvent.mouseDown(screen.getByRole("combobox"));
    const disabledOption = document.querySelector(".ant-select-item-option-disabled");
    expect(disabledOption).toBeTruthy();
    await userEvent.type(
      container.querySelector('input[type="password"]') as HTMLInputElement,
      "temporary-current-password",
    );
    const submit = container.querySelector('button[type="submit"]') as HTMLButtonElement;
    await userEvent.click(submit);
    await waitFor(() => expect(mocks.updateRiskPolicy).toHaveBeenCalled());
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it.each([403, 409, 422, 429, 503])("shows policy API error %s", async (status) => {
    mocks.getRiskPolicies.mockRejectedValueOnce(new Error(`策略错误 ${status}`));
    render(<RiskPoliciesPage />);
    expect(await screen.findByText(`策略错误 ${status}`)).toBeTruthy();
  });
});

describe("audit page", () => {
  it("filters, paginates and opens safe detail without sensitive payloads", async () => {
    const { container } = render(<AuditPage />);
    await screen.findByText("user.freeze");
    const inputs = container.querySelectorAll("input");
    await userEvent.type(inputs[0], "user.freeze");
    await userEvent.type(inputs[1], "executed");
    await waitFor(() =>
      expect(mocks.getAuditEvents).toHaveBeenLastCalledWith(1, "user.freeze", "executed"),
    );
    await userEvent.click(container.querySelector("tbody button") as HTMLButtonElement);
    await waitFor(() => expect(mocks.getAuditEvent).toHaveBeenCalledWith("audit-1"));
    expect(container.textContent).toContain("active");
    expect(container.textContent).toContain("frozen");
    expect(container.textContent).not.toContain("13800138000");
    expect(container.textContent).not.toContain("203.0.113.99");
    expect(container.textContent).not.toContain("raw exception");
  });

  it.each([403, 429, 503])("shows audit access/service error %s", async (status) => {
    mocks.getAuditEvents.mockRejectedValueOnce(new Error(`审计错误 ${status}`));
    render(<AuditPage />);
    expect(await screen.findByText(`审计错误 ${status}`)).toBeTruthy();
  });
});
