// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AuditPage from "../app/admin/audit/page";
import RiskPoliciesPage from "../app/admin/risk-policies/page";

const mocks = vi.hoisted(() => ({
  redirect: vi.fn(),
  getAuditEvents: vi.fn(),
  getAuditEvent: vi.fn(),
  userMessage: vi.fn((error: unknown) =>
    error instanceof Error ? error.message : "明确的无权限或服务错误",
  ),
}));

vi.mock("next/navigation", () => ({
  redirect: mocks.redirect,
}));
vi.mock("@/lib/auth-client", () => ({
  userMessage: mocks.userMessage,
}));
vi.mock("@/lib/risk-client", () => ({
  getAuditEvents: mocks.getAuditEvents,
  getAuditEvent: mocks.getAuditEvent,
}));

const pagination = {
  page: 1,
  page_size: 20,
  count: 1,
  total_pages: 1,
};

const audit = {
  id: "audit-1",
  category: "high_risk_action",
  action_key: "user.freeze",
  outcome: "executed",
  actor_id: "actor",
  subject_id: "subject",
  requester_id: "requester",
  target_type: "user",
  target_id: "target",
  request_id: "00000000-0000-4000-8000-000000000002",
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
  mocks.getAuditEvents.mockResolvedValue({ results: [audit], pagination });
  mocks.getAuditEvent.mockResolvedValue(audit);
});

afterEach(cleanup);

describe("risk settings route", () => {
  it("redirects the legacy policy route to system settings", () => {
    render(<RiskPoliciesPage />);
    expect(mocks.redirect).toHaveBeenCalledWith("/admin/settings");
  });
});

describe("operation record compatibility page", () => {
  it("filters and opens a safe operation detail without sensitive payloads", async () => {
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

  it.each([403, 429, 503])("shows operation record access/service error %s", async (status) => {
    mocks.getAuditEvents.mockRejectedValueOnce(new Error(`操作记录错误 ${status}`));
    render(<AuditPage />);
    expect(await screen.findByText(`操作记录错误 ${status}`)).toBeTruthy();
  });
});
