// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { getCurrentQuotaAccounts } = vi.hoisted(() => ({
  getCurrentQuotaAccounts: vi.fn(),
}));

vi.mock("@/lib/quota-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/quota-client")>("@/lib/quota-client");
  return { ...actual, getCurrentQuotaAccounts };
});

import { QuotaActionHint } from "../components/quota-action-hint";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("业务操作额度提示", () => {
  it("展示业务说明和当前自然单位余额", async () => {
    getCurrentQuotaAccounts.mockResolvedValue({
      accounts: [
        {
          quota_type: "source_index_scans",
          unit: "count",
          scope: "subscription",
          entitlement_amount: 10,
          available: 9,
          frozen: 0,
        },
      ],
    });

    render(
      <QuotaActionHint
        quotaType="source_index_scans"
        actionText="本次扫描获得有效结果后使用 1 次信源扫描额度"
      />,
    );

    expect(await screen.findByText(/剩余 9 次/)).toBeTruthy();
  });

  it("额度暂时无法读取时仍保留操作说明", async () => {
    getCurrentQuotaAccounts.mockRejectedValue(new Error("暂时不可用"));

    render(
      <QuotaActionHint
        quotaType="website_generations"
        actionText="成功生成官网内容后使用 1 次官网生成额度"
      />,
    );

    expect(await screen.findByText("成功生成官网内容后使用 1 次官网生成额度")).toBeTruthy();
  });
});
