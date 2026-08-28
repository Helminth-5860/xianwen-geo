import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

const userPages = [
  "../app/geo/detections/page.tsx",
  "../app/geo/detections/[detectionId]/page.tsx",
  "../app/geo/reports/page.tsx",
  "../app/geo/reports/report-page.tsx",
  "../app/geo/reports/history/page.tsx",
  "../app/geo/exposure/page.tsx",
  "../app/geo/retest/page.tsx",
  "../app/geo/strategy/page.tsx",
  "../app/geo/reports/[reportId]/strategy/strategy-page.tsx",
  "../app/subjects/[id]/videos/new/video-generation-workspace.tsx",
  "../components/video-library-workspace.tsx",
].map(read);

describe("GEO 普通用户页面文案", () => {
  it("不显示英文眉题、原始状态或内部实现术语", () => {
    const source = userPages.join("\n");

    for (const forbidden of [
      "GEO DETECTION",
      "GEO REPORT",
      "GEO COMPARISON",
      "AI EXPOSURE",
      "GEO VALIDATION",
      "GEO OPTIMIZATION",
      "GEO Score",
      "任务长时间未被执行器领取",
      "模型执行状态",
      "调用进度：",
      "不可变来源事实",
      "逻辑模型集合",
      "由后端基于冻结问题",
      "导出任务已创建",
      "AI 原始策略",
    ]) {
      expect(source).not.toContain(forbidden);
    }
  });

  it("为检测和报告状态提供中文兜底", () => {
    const detection = read("../app/geo/detections/page.tsx");
    const report = read("../app/geo/reports/report-page.tsx");

    expect(detection).toContain('queued: "等待检测"');
    expect(detection).toContain('succeeded: "已完成"');
    expect(report).toContain('not_generated: "未生成"');
    expect(report).toContain('return reportStatusLabels[status] ?? "状态待确认"');
  });
});
