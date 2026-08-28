// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActionCard, HeatmapCell } from "../components/xw";

describe("显问基础数据组件", () => {
  it("行动卡片使用用户可理解的中文信息与可访问入口", () => {
    render(
      <ActionCard
        eyebrow="当前建议"
        title="先完善主体资料"
        description="完整资料有助于提升后续检测的准确性。"
        action={{ label: "去完善", href: "/subjects/subject-1" }}
      />,
    );

    expect(screen.getByText("当前建议")).toBeTruthy();
    expect(screen.getByRole("link", { name: "去完善" }).getAttribute("href")).toBe(
      "/subjects/subject-1",
    );
  });

  it("热力单元格提供中文状态并支持交互", () => {
    const onClick = vi.fn();
    render(<HeatmapCell status="recommended" detail="豆包检测结果" onClick={onClick} />);

    const cell = screen.getByRole("button", { name: "已推荐，豆包检测结果" });
    fireEvent.click(cell);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/recommended|mentioned|missing|negative|unknown/i)).toBeNull();
  });
});
