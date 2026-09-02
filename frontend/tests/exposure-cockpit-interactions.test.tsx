// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ExposureTimeline } from "../app/geo/exposure/components/exposure-timeline";
import { GeoExposureMap } from "../app/geo/exposure/components/map/geo-exposure-map";
import { createDemonstrationMaps } from "../app/geo/exposure/exposure-demo-data";
import type {
  ExposureEvent,
  ExposureMapLevel,
  GeoJsonCollection,
  RegionExposure,
} from "../app/geo/exposure/types";

const boundaryByLevel: Record<ExposureMapLevel, GeoJsonCollection> = {
  country: {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: { adcode: 440000, name: "广东省", center: [113.2, 23.1] },
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
    ],
  },
  province: {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: { adcode: 440100, name: "广州市", center: [113.26, 23.13] },
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
        properties: { adcode: 440106, name: "天河区", center: [113.36, 23.12] },
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

function MapHarness() {
  const maps = createDemonstrationMaps("2026-09-02T08:00:00Z");
  const [level, setLevel] = useState<ExposureMapLevel>("country");
  const [lockedRegion, setLockedRegion] = useState<RegionExposure | null>(null);
  return (
    <GeoExposureMap
      data={maps[level]}
      visibleEvents={maps[level].events}
      activeEvent={maps[level].events[0] ?? null}
      lockedRegion={lockedRegion}
      onLockedRegionChange={setLockedRegion}
      onLevelChange={setLevel}
    />
  );
}

const timelineEvents: readonly ExposureEvent[] = [
  {
    id: "event-1",
    sourceCityCode: "440100",
    sourceCityName: "广州",
    sourceCoordinates: [113.264385, 23.129112],
    targetCityCode: "440300",
    targetCityName: "深圳",
    targetCoordinates: [114.057868, 22.543099],
    model: "DeepSeek",
    keyword: "深圳 GEO 优化",
    question: "深圳企业如何提升人工智能搜索曝光？",
    estimatedExposure: 3200,
    score: 80,
    timestamp: "2026-09-02T07:30:00Z",
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
        const level: ExposureMapLevel = url.includes("guangzhou")
          ? "city"
          : url.includes("guangdong")
            ? "province"
            : "country";
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(boundaryByLevel[level]),
        } as Response);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("支持从全国钻取到广东省和广州市，并可返回上一级", async () => {
    render(<MapHarness />);

    fireEvent.click(await screen.findByRole("button", { name: "广东省区域" }));
    expect(await screen.findByRole("heading", { name: "广东省曝光态势地图" })).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "广州市区域" }));
    expect(await screen.findByRole("heading", { name: "广州市曝光态势地图" })).toBeTruthy();
    expect(screen.getByText("区级曝光数据尚未接入，当前仅展示真实行政区边界。")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "广东省" }));
    expect(await screen.findByRole("heading", { name: "广东省曝光态势地图" })).toBeTruthy();
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
