// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { GeoTrendChart, type GeoTrendPoint } from "@/components/xw/geo-trend-chart";

const points: GeoTrendPoint[] = [
  {
    id: "first",
    label: "8月1日",
    detail: "8月1日上午首次检测",
    score: 61.5,
  },
  {
    id: "second",
    label: "8月12日",
    detail: "8月12日下午再次检测",
    score: 68,
  },
  {
    id: "third",
    label: "8月26日",
    detail: "8月26日晚间最近检测",
    score: 74.25,
  },
];

afterEach(cleanup);

describe("综合得分趋势图", () => {
  it("加载、失败和空数据都提供清楚的中文说明", () => {
    const { rerender } = render(<GeoTrendChart points={[]} loading />);
    expect(screen.getByRole("status").textContent).toContain("正在整理得分变化");

    rerender(<GeoTrendChart points={[]} error />);
    expect(screen.getByRole("alert").textContent).toContain("趋势暂时无法显示");
    expect(screen.getByRole("alert").textContent).toContain("请稍后再试");

    rerender(<GeoTrendChart points={[]} />);
    expect(screen.getByRole("status").textContent).toContain("完成至少两次检测后");

    rerender(<GeoTrendChart points={[points[0]]} />);
    expect(screen.getByRole("status").textContent).toContain("已记录首次得分");
    expect(screen.getByRole("status").textContent).toContain("完成至少两次检测后");
    expect(screen.getByRole("status").textContent).toContain("61.5 分");
  });

  it("不依赖页面尺寸监听也能渲染真实数据和零到一百分坐标", () => {
    render(<GeoTrendChart points={points} />);

    const chart = screen.getByLabelText(
      "综合得分趋势图，得分范围为零到一百分；可使用鼠标或键盘逐个查看数据点",
    );
    expect(chart.tagName.toLowerCase()).toBe("svg");
    expect(chart.getAttribute("viewBox")).toBe("0 0 640 260");
    expect(screen.getByText("100")).toBeTruthy();
    expect(screen.getByText("50")).toBeTruthy();
    expect(screen.getByText("0")).toBeTruthy();
    expect(screen.getByText("检测时间")).toBeTruthy();
    expect(screen.getByText("共 3 次检测")).toBeTruthy();
    expect(screen.getByText("74.25 分")).toBeTruthy();
  });

  it("鼠标和键盘聚焦数据点时都会更新当前说明", () => {
    render(<GeoTrendChart points={points} />);

    const dataPoints = screen.getAllByRole("button", { name: /第 \d 次检测/ });
    expect(dataPoints).toHaveLength(3);
    expect(dataPoints.map((point) => point.getAttribute("tabindex"))).toEqual(["-1", "-1", "0"]);

    fireEvent.mouseEnter(dataPoints[0]);
    expect(screen.getByText("8月1日上午首次检测")).toBeTruthy();
    expect(screen.getByText("61.5 分")).toBeTruthy();
    expect(dataPoints[0].getAttribute("aria-pressed")).toBe("true");

    fireEvent.focus(dataPoints[1]);
    expect(screen.getByText("8月12日下午再次检测")).toBeTruthy();
    expect(screen.getByText("68 分")).toBeTruthy();
    expect(dataPoints[1].getAttribute("aria-pressed")).toBe("true");

    fireEvent.keyDown(dataPoints[1], { key: "ArrowRight" });
    expect(screen.getByText("8月26日晚间最近检测")).toBeTruthy();
    expect(screen.getByText("74.25 分")).toBeTruthy();
    expect(dataPoints[2].getAttribute("aria-pressed")).toBe("true");
  });
});
