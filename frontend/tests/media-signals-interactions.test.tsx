// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import MediaSignalsDirectoryPage from "../app/geo/knowledge-graph/media-signals/page";
import { mediaSignalItems } from "../app/geo/knowledge-graph/media-signals/data";

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

describe("媒体信号建设目录", () => {
  it("完整保留 PDF 的 366 条媒体及分级，并生成合法 HTTPS 地址", () => {
    expect(mediaSignalItems).toHaveLength(366);
    expect(
      Object.fromEntries(
        ["S", "A", "B", "C"].map((level) => [
          level,
          mediaSignalItems.filter((item) => item.level === level).length,
        ]),
      ),
    ).toEqual({ S: 29, A: 65, B: 117, C: 155 });
    expect(new Set(mediaSignalItems.map((item) => item.id)).size).toBe(366);
    for (const item of mediaSignalItems) {
      const parsedUrl = new URL(item.url);
      expect(parsedUrl.protocol).toBe("https:");
      expect(parsedUrl.hostname).toBe(item.domain);
    }
  });

  it("每页只显示 20 条，并可翻页查看下一组", async () => {
    render(<MediaSignalsDirectoryPage />);
    expect(screen.getByRole("link", { name: "返回 GEO 工作台" }).getAttribute("href")).toBe(
      "/workspace",
    );
    expect(screen.getAllByRole("link", { name: /打开 .+ 官网/ })).toHaveLength(20);
    expect(screen.getByRole("link", { name: "打开 人民网 官网" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "打开 界面新闻 官网" })).toBeNull();

    await userEvent.click(within(screen.getByLabelText("媒体目录分页")).getByTitle("2"));
    expect(screen.getByRole("link", { name: "打开 界面新闻 官网" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "打开 人民网 官网" })).toBeNull();
  });

  it("支持名称和域名模糊搜索，并在搜索时重置到第一页", async () => {
    const user = userEvent.setup();
    render(<MediaSignalsDirectoryPage />);
    await user.click(within(screen.getByLabelText("媒体目录分页")).getByTitle("2"));

    const search = screen.getByLabelText("搜索媒体名称或域名");
    await user.type(search, "  JIEMIAN  ");
    expect(screen.getByRole("link", { name: "打开 界面新闻 官网" })).toBeTruthy();
    expect(screen.getByText("找到 1 家媒体")).toBeTruthy();

    await user.clear(search);
    await user.type(search, "人民网");
    expect(screen.getByRole("link", { name: "打开 人民网 官网" })).toBeTruthy();
  });

  it("整张卡片安全打开官网，并在 favicon 连续失败后显示文字占位", () => {
    render(<MediaSignalsDirectoryPage />);
    const link = screen.getByRole("link", { name: "打开 人民网 官网" });
    expect(link.getAttribute("href")).toBe("https://www.people.com.cn");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.getAttribute("rel")).toContain("noreferrer");

    let logo = link.querySelector("img");
    expect(logo?.getAttribute("src")).toContain("google.com/s2/favicons");
    fireEvent.error(logo as HTMLImageElement);
    logo = link.querySelector("img");
    expect(logo?.getAttribute("src")).toBe("https://www.people.com.cn/favicon.ico");
    fireEvent.error(logo as HTMLImageElement);
    logo = link.querySelector("img");
    expect(logo?.getAttribute("src")).toContain("favicon.im/www.people.com.cn");
    fireEvent.error(logo as HTMLImageElement);
    expect(link.querySelector("img")).toBeNull();
    expect(within(link).getByText("人")).toBeTruthy();
  });

  it("搜索无结果时给出空状态", async () => {
    render(<MediaSignalsDirectoryPage />);
    await userEvent.type(screen.getByLabelText("搜索媒体名称或域名"), "不存在的媒体域名");
    expect(screen.getByText("未找到匹配的媒体，请更换名称或域名后再试")).toBeTruthy();
    expect(screen.queryByLabelText("媒体目录分页")).toBeNull();
  });
});
