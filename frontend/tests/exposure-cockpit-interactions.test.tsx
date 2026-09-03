// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ExposureTimeline } from "../app/geo/exposure/components/exposure-timeline";
import { GeoExposureMap } from "../app/geo/exposure/components/map/geo-exposure-map";
import { createDemonstrationMaps, createNeutralMaps } from "../app/geo/exposure/exposure-demo-data";
import type {
  ExposureEvent,
  ExposureMapLevel,
  ExposureMapScope,
  GeoJsonCollection,
  RegionExposure,
} from "../app/geo/exposure/types";

const boundaryByLevel: Record<ExposureMapLevel, GeoJsonCollection> = {
  country: {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {
          adcode: 440000,
          name: "广东省",
          center: [113.2, 23.1],
          level: "province",
        },
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [109, 20],
              [117, 20],
              [117, 25],
              [109, 25],
              [109, 20],
            ],
          ],
        },
      },
      {
        type: "Feature",
        properties: {
          adcode: 510000,
          name: "四川省",
          center: [104.0665, 30.5723],
          level: "province",
        },
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [97, 26],
              [108, 26],
              [108, 34],
              [97, 34],
              [97, 26],
            ],
          ],
        },
      },
    ],
  },
  province: {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {
          adcode: 440100,
          name: "广州市",
          center: [113.26, 23.13],
          level: "city",
        },
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [112.9, 22.7],
              [113.9, 22.7],
              [113.9, 23.8],
              [112.9, 23.8],
              [112.9, 22.7],
            ],
          ],
        },
      },
    ],
  },
  city: {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {
          adcode: 440106,
          name: "天河区",
          center: [113.36, 23.12],
          level: "district",
        },
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [113.2, 23],
              [113.5, 23],
              [113.5, 23.3],
              [113.2, 23.3],
              [113.2, 23],
            ],
          ],
        },
      },
    ],
  },
};

const sichuanBoundary: GeoJsonCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: {
        adcode: 510100,
        name: "成都市",
        center: [104.0665, 30.5723],
        level: "city",
      },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [102.9, 30],
            [104.9, 30],
            [104.9, 31.4],
            [102.9, 31.4],
            [102.9, 30],
          ],
        ],
      },
    },
  ],
};

const chengduBoundary: GeoJsonCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: {
        adcode: 510107,
        name: "武侯区",
        center: [104.0434, 30.6418],
        level: "district",
      },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [103.9, 30.5],
            [104.2, 30.5],
            [104.2, 30.8],
            [103.9, 30.8],
            [103.9, 30.5],
          ],
        ],
      },
    },
  ],
};

function MapHarness() {
  const maps = createDemonstrationMaps("2026-09-02T08:00:00Z");
  const [navigationPath, setNavigationPath] = useState<readonly ExposureMapScope[]>([]);
  const [lockedRegion, setLockedRegion] = useState<RegionExposure | null>(null);
  const scope = navigationPath.at(-1);
  const level: ExposureMapLevel = !scope
    ? "country"
    : scope.level === "province"
      ? "province"
      : "city";
  const data = scope
    ? {
        ...maps[level],
        code: scope.code,
        name: scope.name,
        boundaryUrl: `/geo-boundaries/${scope.code}`,
      }
    : maps.country;
  return (
    <GeoExposureMap
      data={data}
      visibleEvents={data.events}
      activeEvent={data.events[0] ?? null}
      eventPlaybackKey={`test-${level}`}
      lockedRegion={lockedRegion}
      onLockedRegionChange={setLockedRegion}
      navigationPath={navigationPath}
      onNavigationPathChange={setNavigationPath}
    />
  );
}

const timelineEvents: readonly ExposureEvent[] = [
  {
    id: "event-1",
    sourceRegionCode: "440100",
    sourceRegionName: "广州",
    sourceCoordinates: [113.264385, 23.129112],
    targetRegionCode: "440300",
    targetRegionName: "深圳",
    targetCoordinates: [114.057868, 22.543099],
    model: "DeepSeek",
    keyword: "深圳 GEO 优化",
    question: "深圳企业如何提升人工智能搜索曝光？",
    estimatedExposure: 3200,
    score: 80,
    timestamp: "2026-09-02T07:30:00Z",
    origin: "sample",
  },
];

describe("曝光态势地图与时间轴", () => {
  beforeAll(() => {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const url = String(input);
        const boundary = url.includes("510100")
          ? chengduBoundary
          : url.includes("510000")
            ? sichuanBoundary
            : null;
        const level: ExposureMapLevel = url.includes("440100")
          ? "city"
          : url.includes("440000")
            ? "province"
            : "country";
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(boundary ?? boundaryByLevel[level]),
        } as Response);
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("生产地图没有真实区域事件时保持中性色，不预置演示红点", () => {
    const maps = createNeutralMaps("2026-09-02T08:00:00Z");

    expect(maps.country.events).toEqual([]);
    expect(maps.province.events).toEqual([]);
    expect(maps.city.events).toEqual([]);
    expect(
      Object.values(maps)
        .flatMap((map) => map.regions)
        .every((region) => region.latestHitAt === null),
    ).toBe(true);
  });

  it("支持从全国钻取到广东省和广州市，并可返回上一级", async () => {
    render(<MapHarness />);

    fireEvent.click(await screen.findByRole("button", { name: "广东省区域" }));
    expect(await screen.findByRole("heading", { name: "广东省曝光态势地图" })).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "广州市区域" }));
    expect(await screen.findByRole("heading", { name: "广州市曝光态势地图" })).toBeTruthy();
    expect(screen.getByText("当前仅展示真实行政区边界，暂无区级曝光记录。")).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "天河区区域" }));
    expect(
      within(screen.getByRole("navigation", { name: "地图层级" })).getByText("天河区"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "返回上一级" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "广东省" }));
    expect(await screen.findByRole("heading", { name: "广东省曝光态势地图" })).toBeTruthy();
  });

  it("全国任意省市都可逐级进入，不依赖广东固定路径", async () => {
    render(<MapHarness />);

    fireEvent.click(await screen.findByRole("button", { name: "四川省区域" }));
    expect(await screen.findByRole("heading", { name: "四川省曝光态势地图" })).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "成都市区域" }));
    expect(await screen.findByRole("heading", { name: "成都市曝光态势地图" })).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "武侯区区域" }));
    expect(
      within(screen.getByRole("navigation", { name: "地图层级" })).getByText("武侯区"),
    ).toBeTruthy();
  });

  it("时间轴拖动会返回真实进度并保留播放与速度控制", async () => {
    const onProgressChange = vi.fn();
    const onModeChange = vi.fn();
    const onSpeedChange = vi.fn();
    render(
      <ExposureTimeline
        events={timelineEvents}
        playing={false}
        mode="replay"
        speed={1}
        progress={25}
        currentTime="15:30:00"
        onPlayingChange={vi.fn()}
        onModeChange={onModeChange}
        onSpeedChange={onSpeedChange}
        onProgressChange={onProgressChange}
      />,
    );

    fireEvent.change(screen.getByRole("slider", { name: "曝光回放时间" }), {
      target: { value: "63.5" },
    });
    expect(onProgressChange).toHaveBeenCalledWith(63.5);

    fireEvent.click(screen.getByRole("button", { name: "1x" }));
    expect(onSpeedChange).toHaveBeenCalledWith(2);

    fireEvent.click(screen.getByRole("button", { name: "实时" }));
    await waitFor(() => expect(onModeChange).toHaveBeenCalledWith("live"));
  });
});
