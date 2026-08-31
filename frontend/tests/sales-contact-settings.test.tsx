// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  context: vi.fn(),
  getAdminSalesContact: vi.fn(),
  setAdminSalesContactEnabled: vi.fn(),
  uploadAdminSalesContact: vi.fn(),
}));

vi.mock("@/components/admin/admin-capability", () => ({
  useAdminCapabilities: () => mocks.context(),
}));

vi.mock("@/lib/sales-contact-client", () => ({
  getAdminSalesContact: mocks.getAdminSalesContact,
  setAdminSalesContactEnabled: mocks.setAdminSalesContactEnabled,
  uploadAdminSalesContact: mocks.uploadAdminSalesContact,
}));

import AdminSettingsPage from "../app/admin/settings/page";

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
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("销售联系方式设置", () => {
  it("超级管理员管理平台全局销售二维码", async () => {
    mocks.context.mockReturnValue({ commercial_identity: "SUPER_ADMIN" });
    mocks.getAdminSalesContact.mockResolvedValue({
      scope: "global",
      configured: false,
      enabled: false,
      qr_code_url: null,
      updated_at: null,
    });

    render(<AdminSettingsPage />);

    expect(await screen.findByText(/平台直营客户和未单独配置的代理客户/)).toBeTruthy();
    expect(screen.getByText("尚未上传二维码")).toBeTruthy();
    expect(screen.getByRole("button", { name: /选择二维码图片/ })).toBeTruthy();
  });

  it("普通管理员只看到自己的设置并可停用", async () => {
    mocks.context.mockReturnValue({ commercial_identity: "ADMIN" });
    mocks.getAdminSalesContact.mockResolvedValue({
      scope: "agent",
      configured: true,
      enabled: true,
      qr_code_url: "data:image/png;base64,iVBORw0KGgo=",
      updated_at: "2026-08-31T10:00:00Z",
    });
    mocks.setAdminSalesContactEnabled.mockResolvedValue({
      scope: "agent",
      configured: true,
      enabled: false,
      qr_code_url: "data:image/png;base64,iVBORw0KGgo=",
      updated_at: "2026-08-31T10:00:00Z",
    });

    render(<AdminSettingsPage />);

    expect(await screen.findByText(/由你负责的客户将优先看到/)).toBeTruthy();
    expect(screen.queryByText("平台直营客户和未单独配置的代理客户")).toBeNull();
    await userEvent.click(screen.getByRole("switch", { name: "启用销售联系方式" }));
    await waitFor(() => expect(mocks.setAdminSalesContactEnabled).toHaveBeenCalledWith(false));
  });
});
