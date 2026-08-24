// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AdminQuotasPage from "../app/admin/quotas/page";
import { AdminCapabilityContext } from "../components/admin/admin-capability";

const getAdminQuotaAccounts = vi.fn();
const adjustQuotaAccount = vi.fn();

vi.mock("../lib/quota-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/quota-client")>("../lib/quota-client");
  return {
    ...actual,
    getAdminQuotaAccounts: (...args: unknown[]) => getAdminQuotaAccounts(...args),
    adjustQuotaAccount: (...args: unknown[]) => adjustQuotaAccount(...args),
  };
});

const account = {
  id: "account-1",
  user_id: "user-1",
  user_nickname: "\u6d4b\u8bd5\u7528\u6237",
  subscription_id: "subscription-1",
  quota_type: "detection_points" as const,
  unit: "point",
  scope: "subscription" as const,
  entitlement_amount: 100,
  available: 80,
  frozen: 20,
  cycle_started_at: null,
  cycle_ends_at: null,
  ledger_sequence: 3,
  version: 4,
};

beforeAll(() => {
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
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    nativeGetComputedStyle(element),
  );
});
beforeEach(() => {
  getAdminQuotaAccounts.mockResolvedValue({
    results: [account],
    pagination: { page: 1, page_size: 20, count: 1, total_pages: 1 },
  });
  adjustQuotaAccount.mockResolvedValue({
    account_id: "account-1",
    ledger_entry_id: "ledger-4",
    available: 83,
    frozen: 20,
    version: 5,
    replayed: false,
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("quota administrator interactions", () => {
  it("shows three actions only with quotas.adjust and submits an in-memory idempotency key", async () => {
    const context = {
      permission_keys: ["quotas.list", "quotas.adjust"],
      menu_keys: ["menu.admin.quotas"],
    } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <AdminQuotasPage />
      </AdminCapabilityContext.Provider>,
    );
    expect(await screen.findByText("\u6d4b\u8bd5\u7528\u6237")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "增加额度" }));
    await userEvent.type(screen.getByLabelText("\u8c03\u6574\u6570\u91cf"), "3");
    await userEvent.type(
      screen.getByLabelText("\u8c03\u6574\u539f\u56e0"),
      "\u4eba\u5de5\u5ba1\u6838\u8865\u507f",
    );
    await userEvent.click(screen.getByRole("button", { name: "确认调整" }));
    await waitFor(() => expect(adjustQuotaAccount).toHaveBeenCalledTimes(1));
    const call = adjustQuotaAccount.mock.calls[0];
    expect(call.slice(0, 5)).toEqual([
      "account-1",
      "grant",
      4,
      3,
      "\u4eba\u5de5\u5ba1\u6838\u8865\u507f",
    ]);
    expect(call[5]).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByText("额度调整完成")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/审批|approval-quota-1/);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(window.location.href).not.toContain(call[5]);
  });

  it("blocks every adjustment action without quotas.adjust", async () => {
    const context = { permission_keys: ["quotas.list"], menu_keys: [] } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <AdminQuotasPage />
      </AdminCapabilityContext.Provider>,
    );
    expect(
      await screen.findByText(
        "\u5f53\u524d\u8d26\u53f7\u6ca1\u6709\u989d\u5ea6\u8c03\u6574\u6743\u9650",
      ),
    ).toBeTruthy();
    for (const name of ["增加额度", "补充额度", "扣减额度"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(adjustQuotaAccount).not.toHaveBeenCalled();
  });

  it("renders a clear permission error without logging sensitive response data", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    getAdminQuotaAccounts.mockRejectedValue(
      new Error("\u6ca1\u6709\u6743\u9650\u6267\u884c\u6b64\u64cd\u4f5c"),
    );
    const context = { permission_keys: ["quotas.list"], menu_keys: [] } as never;
    render(
      <AdminCapabilityContext.Provider value={context}>
        <AdminQuotasPage />
      </AdminCapabilityContext.Provider>,
    );
    expect(
      await screen.findByText("\u6ca1\u6709\u6743\u9650\u6267\u884c\u6b64\u64cd\u4f5c"),
    ).toBeTruthy();
    expect(consoleSpy).not.toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});
