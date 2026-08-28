// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import CompetitorComparisonPage from "../app/geo/data-center/competitors/page";
import NegativeInformationIndexPage from "../app/geo/data-center/negative-index/page";
import SourceIndexPage from "../app/geo/data-center/source-index/page";

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

afterEach(cleanup);

describe("数据中心预留页面", () => {
  it.each([
    {
      title: "竞品对比",
      emptyDescription: "当前暂无可展示的竞品对比",
      Page: CompetitorComparisonPage,
    },
    {
      title: "信源指数",
      emptyDescription: "当前暂无可展示的信源指数",
      Page: SourceIndexPage,
    },
    {
      title: "负面信息指数",
      emptyDescription: "当前暂无可展示的负面信息指数",
      Page: NegativeInformationIndexPage,
    },
  ])("$title 页面只显示中文空状态，不展示虚构数据", ({ title, emptyDescription, Page }) => {
    render(<Page />);

    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
    expect(screen.getByText(emptyDescription)).toBeTruthy();
    expect(screen.queryByText(/预留|后续完善|接口|开发/)).toBeNull();
  });
});
