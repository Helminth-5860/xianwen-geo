import { describe, expect, it } from "vitest";

import { SITE_DESCRIPTION, SITE_NAME } from "../lib/site";

describe("站点基础信息", () => {
  it("使用冻结的简体中文产品名称", () => {
    expect(SITE_NAME).toBe("显问 GEO 智能体系统");
    expect(SITE_DESCRIPTION).toContain("XW-0001");
  });
});
