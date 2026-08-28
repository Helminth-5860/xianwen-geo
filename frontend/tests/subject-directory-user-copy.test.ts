import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

const userPages = [
  "../app/workspace/page.tsx",
  "../app/subjects/page.tsx",
  "../app/subjects/[id]/versions/page.tsx",
  "../app/subjects/[id]/versions/[versionId]/page.tsx",
  "../app/geo/knowledge-graph/maps/page.tsx",
  "../app/geo/knowledge-graph/subjects/page.tsx",
  "../app/geo/knowledge-graph/media-signals/page.tsx",
  "../app/geo/website-audits/page.tsx",
  "../app/geo/website-audits/[id]/page.tsx",
].map(read);

describe("主体与资源目录普通用户文案", () => {
  it("不展示英文眉题、技术版本号和内部实现术语", () => {
    const source = userPages.join("\n");

    for (const forbidden of [
      "GEO WORKSPACE",
      "GEO Score",
      "KNOWLEDGE GRAPH",
      "WEBSITE AUDIT",
      "WEBSITE AUDIT REPORT",
      "冻结 Schema",
      "评分版本 ${report.score_version}",
      "个 URL",
      "TTFB P75",
      "LCP P75",
      "CLS P75",
      "TBT P75",
      "问题库 v${",
      "scoreLabels[key] ?? key",
      "semanticLabels[key] ?? key",
    ]) {
      expect(source).not.toContain(forbidden);
    }
  });

  it("为资料记录、空状态和官网检测提供明确中文说明", () => {
    const source = userPages.join("\n");

    for (const expected of [
      "显问 GEO 情报中心",
      "问题库已就绪",
      "资料更新记录",
      "之后的修改不会影响这份记录",
      "知识图谱建设",
      "请更换名称或域名后再试",
      "官网检测报告",
      "这些项目不会按 0 分计算，你可以稍后刷新查看",
    ]) {
      expect(source).toContain(expected);
    }
  });
});
