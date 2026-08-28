// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import {
  PAID_MEDIA_PAGE_SIZE,
  PaidMediaShoppingWorkspace,
} from "../app/subjects/[id]/paid-media/paid-media-shopping-workspace";

const paidMediaApi = vi.hoisted(() => ({
  createPaidMediaInquiry: vi.fn(),
  getPaidMediaCatalog: vi.fn(),
}));

vi.mock("../lib/paid-media-client", () => ({
  createPaidMediaInquiry: (...args: unknown[]) => paidMediaApi.createPaidMediaInquiry(...args),
  getPaidMediaCatalog: (...args: unknown[]) => paidMediaApi.getPaidMediaCatalog(...args),
}));

const catalog = Array.from({ length: 21 }, (_, index) => ({
  id: `media-${index + 1}`,
  name: index === 0 ? "人民网" : `媒体 ${index + 1}`,
  price_cents: (index + 1) * 10_000,
  url: index === 19 ? null : `https://media-${index + 1}.example.com`,
  domain: index === 19 ? "" : `media-${index + 1}.example.com`,
  logo_path: `/media-logos/media-${index + 1}.png`,
}));

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
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: { randomUUID: () => "paid-media-request-key" },
  });
  const getComputedStyle = window.getComputedStyle.bind(window);
  Object.defineProperty(window, "getComputedStyle", {
    configurable: true,
    value: (element: Element) => getComputedStyle(element),
  });
});

beforeEach(() => {
  paidMediaApi.createPaidMediaInquiry.mockReset();
  paidMediaApi.getPaidMediaCatalog.mockReset();
  paidMediaApi.getPaidMediaCatalog.mockImplementation((search: string, page: number) => {
    const filtered = search
      ? catalog.filter(
          (item) => item.name.includes(search) || item.domain?.toLowerCase().includes(search),
        )
      : catalog;
    const start = (page - 1) * PAID_MEDIA_PAGE_SIZE;
    return Promise.resolve({
      items: filtered.slice(start, start + PAID_MEDIA_PAGE_SIZE),
      pagination: {
        page,
        page_size: PAID_MEDIA_PAGE_SIZE,
        count: filtered.length,
        total_pages: Math.ceil(filtered.length / PAID_MEDIA_PAGE_SIZE),
      },
    });
  });
  paidMediaApi.createPaidMediaInquiry.mockResolvedValue({
    id: "inquiry-1",
    subject_id: "subject-1",
    selected_media: [],
    item_count: 2,
    total_price: "2200.00",
    status: "pending",
    version: 1,
    created_at: "2026-08-28T00:00:00Z",
    updated_at: "2026-08-28T00:00:00Z",
  });
});

afterEach(cleanup);

describe("付费媒体购物页", () => {
  it("服务端每页加载 20 条，并支持名称和域名搜索", async () => {
    const user = userEvent.setup();
    render(<PaidMediaShoppingWorkspace subjectId="subject-1" />);

    expect(await screen.findAllByRole("checkbox", { name: /选择媒体/ })).toHaveLength(20);
    expect(paidMediaApi.getPaidMediaCatalog).toHaveBeenCalledWith("", 1, expect.any(AbortSignal));
    const referenceLink = screen.getByRole("link", { name: "打开 人民网 参考链接" });
    expect(referenceLink.getAttribute("target")).toBe("_blank");
    expect(referenceLink.getAttribute("rel")).toContain("noopener");
    expect(screen.getByText("暂无可用链接")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /打开 媒体 20/ })).toBeNull();

    await user.type(screen.getByLabelText("搜索媒体名称或域名"), "media-21.example");
    expect(await screen.findByRole("link", { name: "打开 媒体 21 参考链接" })).toBeTruthy();
    await waitFor(() =>
      expect(paidMediaApi.getPaidMediaCatalog).toHaveBeenLastCalledWith(
        "media-21.example",
        1,
        expect.any(AbortSignal),
      ),
    );
  });

  it("保留跨页勾选，计算总价并经中文确认框提交", async () => {
    const user = userEvent.setup();
    render(<PaidMediaShoppingWorkspace subjectId="subject-1" />);

    await user.click(await screen.findByRole("checkbox", { name: "选择媒体：人民网" }));
    await user.click(within(screen.getByLabelText("付费媒体分页")).getByTitle("2"));
    await user.click(await screen.findByRole("checkbox", { name: "选择媒体：媒体 21" }));

    const calculator = screen.getByLabelText("价格计算器");
    expect(within(calculator).getByText("价格计算器 · 已选 2 / 200 家")).toBeTruthy();
    expect(within(calculator).getByText("¥2,200.00")).toBeTruthy();

    await user.click(within(calculator).getByRole("button", { name: "提交发布需求" }));
    const dialog = await screen.findByRole("dialog", { name: "确认提交媒体发布需求" });
    expect(within(dialog).getByRole("button", { name: "取消提交" })).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "确认联系管理员提交" }));

    await waitFor(() =>
      expect(paidMediaApi.createPaidMediaInquiry).toHaveBeenCalledWith(
        "subject-1",
        ["media-1", "media-21"],
        "paid-media-request-key",
      ),
    );
    expect(await screen.findByText("已提交给管理员，管理员将联系您确认发布安排。")).toBeTruthy();
    expect(within(calculator).getByText("价格计算器 · 已选 0 / 200 家")).toBeTruthy();
  });

  it("支持全选本页和清空已选", async () => {
    const user = userEvent.setup();
    render(<PaidMediaShoppingWorkspace subjectId="subject-1" />);

    await screen.findByRole("checkbox", { name: "选择媒体：人民网" });
    await user.click(screen.getByRole("checkbox", { name: "全选本页" }));
    expect(screen.getByText("已选 20 / 200 家，跨页选择会自动保留")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "清空已选" }));
    expect(screen.getByText("已选 0 / 200 家，跨页选择会自动保留")).toBeTruthy();
  });
});
