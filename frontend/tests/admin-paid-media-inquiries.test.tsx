// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AdminPaidMediaInquiriesPage from "../app/admin/paid-media-inquiries/page";

const paidMediaAdminApi = vi.hoisted(() => ({
  getAdminPaidMediaInquiries: vi.fn(),
  updateAdminPaidMediaInquiry: vi.fn(),
}));

vi.mock("../lib/paid-media-client", () => ({
  getAdminPaidMediaInquiries: (...args: unknown[]) =>
    paidMediaAdminApi.getAdminPaidMediaInquiries(...args),
  updateAdminPaidMediaInquiry: (...args: unknown[]) =>
    paidMediaAdminApi.updateAdminPaidMediaInquiry(...args),
}));

const inquiry = {
  id: "inquiry-1",
  subject_id: "subject-1",
  user: { id: "user-1", nickname: "张经理", phone: "13800000000" },
  subject: { id: "subject-1", name: "广州测试企业" },
  selected_media: [
    {
      id: "media-1",
      name: "人民网",
      price: "1000.00",
      price_cents: 100_000,
      url: "https://www.people.com.cn",
      domain: "people.com.cn",
      logo_path: "/paid-media-logos/media-1.png",
    },
  ],
  item_count: 1,
  total_price: "1000.00",
  status: "pending",
  version: 1,
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
} as const;

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
  const getComputedStyle = window.getComputedStyle.bind(window);
  Object.defineProperty(window, "getComputedStyle", {
    configurable: true,
    value: (element: Element) => getComputedStyle(element),
  });
});

beforeEach(() => {
  paidMediaAdminApi.getAdminPaidMediaInquiries.mockReset();
  paidMediaAdminApi.updateAdminPaidMediaInquiry.mockReset();
  paidMediaAdminApi.getAdminPaidMediaInquiries.mockResolvedValue({
    items: [inquiry],
    pagination: { page: 1, page_size: 20, count: 1, total_pages: 1 },
  });
  paidMediaAdminApi.updateAdminPaidMediaInquiry.mockResolvedValue({
    ...inquiry,
    status: "contacted",
    version: 2,
  });
});

afterEach(cleanup);

describe("后台媒体发布需求", () => {
  it("查看客户和媒体明细，并能标记为已联系", async () => {
    const user = userEvent.setup();
    render(<AdminPaidMediaInquiriesPage />);

    expect(await screen.findByText("张经理")).toBeTruthy();
    expect(screen.getByText("13800000000")).toBeTruthy();
    expect(screen.getByText("广州测试企业")).toBeTruthy();
    expect(screen.getByText("¥1,000.00")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "查看明细" }));
    await screen.findByText("媒体发布需求明细");
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("link", { name: /人民网/ })).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: /关\s*闭/ }));

    await user.click(screen.getByRole("button", { name: "标记已联系" }));
    await waitFor(() =>
      expect(paidMediaAdminApi.updateAdminPaidMediaInquiry).toHaveBeenCalledWith(
        "inquiry-1",
        "contacted",
        1,
      ),
    );
    expect((await screen.findAllByText("已联系")).length).toBeGreaterThan(0);
  });
});
