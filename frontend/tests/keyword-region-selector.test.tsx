// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  keywordRegionSelectionsFromServiceArea,
  KeywordRegionSelector,
} from "@/components/keyword-region-selector";

beforeEach(() => {
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
  Object.defineProperty(globalThis, "ResizeObserver", {
    writable: true,
    value: class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  });
});

afterEach(cleanup);

describe("KeywordRegionSelector", () => {
  it("保留主体省市区街道 code、name、level 和 path", () => {
    const serviceRegions = JSON.stringify({
      version: 1,
      nationwide: false,
      areas: [
        {
          code: "440106001",
          name: "石牌街道",
          level: "street",
          path: [
            { code: "440000", name: "广东省" },
            { code: "440100", name: "广州市" },
            { code: "440106", name: "天河区" },
            { code: "440106001", name: "石牌街道" },
          ],
        },
      ],
    });

    expect(keywordRegionSelectionsFromServiceArea(serviceRegions)).toEqual([
      {
        code: "440106001",
        name: "石牌街道",
        level: "street",
        path: [
          { code: "440000", name: "广东省" },
          { code: "440100", name: "广州市" },
          { code: "440106", name: "天河区" },
          { code: "440106001", name: "石牌街道" },
        ],
      },
    ]);

    render(
      <KeywordRegionSelector
        mode="subject"
        serviceRegions={serviceRegions}
        value={[]}
        onChange={() => undefined}
      />,
    );
    expect(screen.getByText("广东省 / 广州市 / 天河区 / 石牌街道")).toBeTruthy();
  });

  it("自定义地域复用完整行政区划选择器并支持全国", async () => {
    const onChange = vi.fn();
    render(
      <KeywordRegionSelector mode="custom" serviceRegions="" value={[]} onChange={onChange} />,
    );

    expect(screen.getByText("选择省 / 市 / 区县")).toBeTruthy();
    expect(screen.getByLabelText("乡镇或街道")).toBeTruthy();
    await userEvent.click(screen.getByRole("checkbox", { name: "支持全国" }));
    expect(onChange).toHaveBeenLastCalledWith([
      {
        code: "CN",
        name: "全国",
        level: "country",
        path: [{ code: "CN", name: "全国" }],
      },
    ]);
  });
});
