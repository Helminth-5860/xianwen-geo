import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createSubjectCompetitor,
  getCompetitorComparison,
  getSubjectCompetitors,
  removeSubjectCompetitor,
  updateSubjectCompetitor,
  type Competitor,
} from "../lib/competitors-client";

const get = vi.fn();
const post = vi.fn();
const write = vi.fn();
const remove = vi.fn();

vi.mock("../lib/auth-client", () => ({
  get: (...args: unknown[]) => get(...args),
  post: (...args: unknown[]) => post(...args),
  write: (...args: unknown[]) => write(...args),
  remove: (...args: unknown[]) => remove(...args),
}));

const competitor: Competitor = {
  id: "competitor-1",
  name: "竞品甲",
  website: "https://example.test",
  domain: "example.test",
  source: "manual",
  position: 1,
  version: 3,
  created_at: "2026-08-29T08:00:00Z",
  updated_at: "2026-08-29T08:00:00Z",
};

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  write.mockReset();
  remove.mockReset();
});

describe("竞品客户端", () => {
  it("名单和对比始终使用同一主体范围", () => {
    const controller = new AbortController();
    void getSubjectCompetitors("subject-1", controller.signal);
    void getCompetitorComparison("subject-1", controller.signal);

    expect(get).toHaveBeenNthCalledWith(1, "/subjects/subject-1/competitors", {
      signal: controller.signal,
    });
    expect(get).toHaveBeenNthCalledWith(2, "/subjects/subject-1/competitors/comparison", {
      signal: controller.signal,
    });
  });

  it("新增、编辑和移除使用约定的主体竞品接口", () => {
    void createSubjectCompetitor("subject-1", { name: "竞品甲", website: "example.test" });
    void updateSubjectCompetitor("subject-1", competitor, {
      name: "竞品甲新版",
      website: "new.example.test",
    });
    void removeSubjectCompetitor("subject-1", "competitor-1");

    expect(post).toHaveBeenCalledWith("/subjects/subject-1/competitors", {
      name: "竞品甲",
      website: "example.test",
    });
    expect(write).toHaveBeenCalledWith("PATCH", "/subjects/subject-1/competitors/competitor-1", {
      name: "竞品甲新版",
      website: "new.example.test",
      expected_version: 3,
    });
    expect(remove).toHaveBeenCalledWith("/subjects/subject-1/competitors/competitor-1");
  });
});
