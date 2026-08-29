// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { CompetitorManagementWorkspace } from "../app/subjects/[id]/competitors/competitor-management-workspace";
import type { Competitor, CompetitorList } from "../lib/competitors-client";

const subjectA = {
  id: "subject-a",
  official_name: "甲公司",
  subject_type: { id: "type-1", key: "company", name: "企业", icon_key: "company" },
};
const subjectB = {
  id: "subject-b",
  official_name: "乙公司",
  subject_type: { id: "type-1", key: "company", name: "企业", icon_key: "company" },
};

let workspace = { currentSubject: subjectA, subjects: [subjectA, subjectB] };
const getSubjectCompetitors = vi.fn();
const createSubjectCompetitor = vi.fn();
const updateSubjectCompetitor = vi.fn();
const removeSubjectCompetitor = vi.fn();

vi.mock("../components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => workspace,
}));

vi.mock("../lib/competitors-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/competitors-client")>(
    "../lib/competitors-client",
  );
  return {
    ...actual,
    getSubjectCompetitors: (...args: unknown[]) => getSubjectCompetitors(...args),
    createSubjectCompetitor: (...args: unknown[]) => createSubjectCompetitor(...args),
    updateSubjectCompetitor: (...args: unknown[]) => updateSubjectCompetitor(...args),
    removeSubjectCompetitor: (...args: unknown[]) => removeSubjectCompetitor(...args),
  };
});

function competitor(id: string, name: string, position: number): Competitor {
  return {
    id,
    name,
    website: `https://${id}.example.test`,
    domain: `${id}.example.test`,
    source: "manual",
    position,
    version: 1,
    created_at: "2026-08-29T08:00:00Z",
    updated_at: "2026-08-29T08:00:00Z",
  };
}

function list(subjectId: string, subjectName: string, items: Competitor[]): CompetitorList {
  return {
    subject: { id: subjectId, name: subjectName },
    items,
    count: items.length,
    max_count: 3,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

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

beforeEach(() => {
  workspace = { currentSubject: subjectA, subjects: [subjectA, subjectB] };
  getSubjectCompetitors.mockReset();
  createSubjectCompetitor.mockReset();
  updateSubjectCompetitor.mockReset();
  removeSubjectCompetitor.mockReset();
});

afterEach(cleanup);

describe("竞品管理", () => {
  it("首次读取失败时只显示重试入口，重试成功后恢复正常内容", async () => {
    getSubjectCompetitors
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce(list("subject-a", "甲公司", []));

    render(<CompetitorManagementWorkspace subjectId="subject-a" />);

    expect(await screen.findByText("竞品信息暂时无法读取")).toBeTruthy();
    expect(screen.queryByText("已设置：0 / 3")).toBeNull();
    expect(screen.queryByText("暂无竞品")).toBeNull();
    expect(screen.queryByRole("button", { name: /添加竞品/ })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "重新加载" }));

    expect(await screen.findByText("已设置：0 / 3")).toBeTruthy();
    expect(screen.getByText("暂无竞品")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /添加竞品/ }).length).toBeGreaterThan(0);
    expect(getSubjectCompetitors).toHaveBeenCalledTimes(2);
  });

  it("添加竞品后刷新列表并保留当前主体", async () => {
    const added = competitor("competitor-a", "竞品甲", 1);
    getSubjectCompetitors
      .mockResolvedValueOnce(list("subject-a", "甲公司", []))
      .mockResolvedValueOnce(list("subject-a", "甲公司", [added]));
    createSubjectCompetitor.mockResolvedValue({ competitor: added });

    render(<CompetitorManagementWorkspace subjectId="subject-a" />);
    expect(await screen.findByText("暂无竞品")).toBeTruthy();
    expect(screen.getByText("已设置：0 / 3")).toBeTruthy();

    await userEvent.click(screen.getAllByRole("button", { name: /添加竞品/ })[0]);
    await userEvent.type(screen.getByLabelText("竞品名称"), "竞品甲");
    await userEvent.type(screen.getByLabelText("官方网站（选填）"), "www.example.cn");
    await userEvent.click(screen.getByRole("button", { name: "确认添加" }));

    await waitFor(() =>
      expect(createSubjectCompetitor).toHaveBeenCalledWith("subject-a", {
        name: "竞品甲",
        website: "www.example.cn",
      }),
    );
    expect(await screen.findByText("竞品已添加。")).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "竞品甲" })).toBeTruthy();
    expect(getSubjectCompetitors).toHaveBeenCalledTimes(2);
  });

  it("编辑和移除后立即读取更新后的唯一竞品名单", async () => {
    const first = competitor("competitor-a", "竞品甲", 1);
    const second = competitor("competitor-b", "竞品乙", 2);
    const edited = { ...first, name: "竞品甲新版", version: 2 };
    getSubjectCompetitors
      .mockResolvedValueOnce(list("subject-a", "甲公司", [first, second]))
      .mockResolvedValueOnce(list("subject-a", "甲公司", [edited, second]))
      .mockResolvedValueOnce(list("subject-a", "甲公司", [edited]));
    updateSubjectCompetitor.mockResolvedValue({ competitor: edited });
    removeSubjectCompetitor.mockResolvedValue(undefined);

    render(<CompetitorManagementWorkspace subjectId="subject-a" />);
    expect(await screen.findByRole("heading", { name: "竞品甲" })).toBeTruthy();

    await userEvent.click(screen.getAllByRole("button", { name: /编\s*辑/ })[0]);
    const nameInput = screen.getByLabelText("竞品名称");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "竞品甲新版");
    await userEvent.click(screen.getByRole("button", { name: "保存修改" }));

    await waitFor(() =>
      expect(updateSubjectCompetitor).toHaveBeenCalledWith(
        "subject-a",
        first,
        expect.objectContaining({ name: "竞品甲新版" }),
      ),
    );
    expect(await screen.findByRole("heading", { name: "竞品甲新版" })).toBeTruthy();

    await userEvent.click(screen.getAllByRole("button", { name: /移\s*除/ })[1]);
    await userEvent.click(
      await screen.findByRole("button", { name: /确认移除|确\s*认\s*移\s*除/ }),
    );
    await waitFor(() =>
      expect(removeSubjectCompetitor).toHaveBeenCalledWith("subject-a", "competitor-b"),
    );
    expect(await screen.findByText("竞品已移除。")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "竞品乙" })).toBeNull();
    expect(screen.getByText("已设置：1 / 3")).toBeTruthy();
  });

  it("设置满三家后不再提供新增入口", async () => {
    getSubjectCompetitors.mockResolvedValue(
      list("subject-a", "甲公司", [
        competitor("competitor-a", "竞品甲", 1),
        competitor("competitor-b", "竞品乙", 2),
        competitor("competitor-c", "竞品丙", 3),
      ]),
    );

    render(<CompetitorManagementWorkspace subjectId="subject-a" />);
    expect(await screen.findByText("已设置：3 / 3")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /添加竞品/ })).toBeNull();
  });

  it("切换主体时不会让上一主体的迟到响应覆盖新主体", async () => {
    const subjectAResult = deferred<CompetitorList>();
    getSubjectCompetitors.mockImplementation((subjectId: string) =>
      subjectId === "subject-a"
        ? subjectAResult.promise
        : Promise.resolve(list("subject-b", "乙公司", [competitor("competitor-b", "乙方竞品", 1)])),
    );

    const { rerender } = render(<CompetitorManagementWorkspace subjectId="subject-a" />);
    workspace = { currentSubject: subjectB, subjects: [subjectA, subjectB] };
    rerender(<CompetitorManagementWorkspace subjectId="subject-b" />);

    expect(await screen.findByRole("heading", { name: "乙方竞品" })).toBeTruthy();
    subjectAResult.resolve(
      list("subject-a", "甲公司", [competitor("competitor-a", "甲方旧竞品", 1)]),
    );
    await Promise.resolve();

    expect(screen.getByRole("heading", { name: "乙方竞品" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "甲方旧竞品" })).toBeNull();
  });
});
