"use client";

import {
  CompressOutlined,
  EnvironmentOutlined,
  LoadingOutlined,
  ReloadOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from "@ant-design/icons";
import { useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from "react";

import type {
  ExposureEvent,
  ExposureMapData,
  ExposureMapLevel,
  GeoJsonCollection,
  RegionExposure,
} from "../../types";
import styles from "../../exposure-command-center.module.css";
import { CityLabelLayer } from "./city-label-layer";
import { GeoBoundaryLayer } from "./geo-boundary-layer";
import { createGeoProjection } from "./geo-projection";
import { GeoTooltip } from "./geo-tooltip";
import { PulseArcLayer } from "./pulse-arc-layer";
import { SourcePulseLayer } from "./source-pulse-layer";
import { TargetPulseLayer } from "./target-pulse-layer";

const LEVEL_LABELS: Record<ExposureMapLevel, string> = {
  country: "全国视图",
  province: "省级视图（广东）",
  city: "市级视图（广州）",
};

type ViewTransform = Readonly<{ zoom: number; x: number; y: number }>;
type BoundaryState = Readonly<{
  url: string;
  collection: GeoJsonCollection | null;
  error: string;
}>;

export function GeoExposureMap({
  data,
  visibleEvents,
  activeEvent,
  lockedRegion,
  onLockedRegionChange,
  onLevelChange,
}: Readonly<{
  data: ExposureMapData;
  visibleEvents: readonly ExposureEvent[];
  activeEvent: ExposureEvent | null;
  lockedRegion: RegionExposure | null;
  onLockedRegionChange: (region: RegionExposure | null) => void;
  onLevelChange: (level: ExposureMapLevel) => void;
}>) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [boundaryState, setBoundaryState] = useState<BoundaryState>({
    url: "",
    collection: null,
    error: "",
  });
  const [hostSize, setHostSize] = useState({ width: 960, height: 600 });
  const [view, setView] = useState<ViewTransform>({ zoom: 1, x: 0, y: 0 });
  const [dragStart, setDragStart] = useState<Readonly<{ x: number; y: number }> | null>(null);
  const [hoveredRegion, setHoveredRegion] = useState<RegionExposure | null>(null);
  const [tooltipPosition, setTooltipPosition] = useState({ x: 18, y: 72 });

  useEffect(() => {
    const controller = new AbortController();
    void fetch(data.boundaryUrl, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("地图边界加载失败");
        return response.json() as Promise<GeoJsonCollection>;
      })
      .then((nextCollection) => {
        setBoundaryState({ url: data.boundaryUrl, collection: nextCollection, error: "" });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setBoundaryState({
          url: data.boundaryUrl,
          collection: null,
          error: reason instanceof Error ? reason.message : "地图边界暂时无法显示",
        });
      });
    return () => controller.abort();
  }, [data.boundaryUrl]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setHostSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  const collection = boundaryState.url === data.boundaryUrl ? boundaryState.collection : null;
  const mapError = boundaryState.url === data.boundaryUrl ? boundaryState.error : "";

  const projection = useMemo(
    () => (collection ? createGeoProjection(collection) : null),
    [collection],
  );

  const displayedRegions = useMemo(() => {
    if (!data.events.length) return data.regions;
    const visibleCodes = new Set(visibleEvents.map((event) => event.targetCityCode));
    return data.regions.map((region) => ({
      ...region,
      cumulativeIntensity: visibleCodes.has(region.code) ? region.cumulativeIntensity : 0,
    }));
  }, [data.events.length, data.regions, visibleEvents]);

  const emptyRegion = (code: string, name: string): RegionExposure => {
    const known = data.regions.find((item) => item.code === code || item.name === name);
    if (known) return known;
    const feature = collection?.features.find(
      (item) => String(item.properties.adcode) === code || item.properties.name === name,
    );
    const point =
      feature?.properties.centroid ?? feature?.properties.center ?? data.sourceCity.coordinates;
    return {
      code,
      name,
      coordinates: [point[0], point[1]],
      exposureIndex: null,
      keywordHits: null,
      estimatedExposure: null,
      recommendationRate: null,
      modelCount: null,
      latestHitAt: null,
      cumulativeIntensity: 0,
    };
  };

  const selectBoundary = (code: string, name: string) => {
    const region = emptyRegion(code, name);
    onLockedRegionChange(region);
    if (data.level === "country" && code === "440000") onLevelChange("province");
    if (data.level === "province" && code === "440100") onLevelChange("city");
  };

  const updateZoom = (next: number) =>
    setView((current) => ({ ...current, zoom: Math.max(0.8, Math.min(3.2, next)) }));

  const handleWheel = (event: WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const factor = event.deltaY > 0 ? 0.9 : 1.1;
    updateZoom(view.zoom * factor);
  };

  const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.target instanceof Element && event.target.closest('[role="button"]')) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragStart({ x: event.clientX - view.x, y: event.clientY - view.y });
  };

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = hostRef.current?.getBoundingClientRect();
    if (bounds) {
      setTooltipPosition({
        x: Math.min(bounds.width - 246, Math.max(12, event.clientX - bounds.left + 14)),
        y: Math.min(bounds.height - 238, Math.max(64, event.clientY - bounds.top + 14)),
      });
    }
    if (!dragStart) return;
    setView((current) => ({
      ...current,
      x: event.clientX - dragStart.x,
      y: event.clientY - dragStart.y,
    }));
  };

  const stopDragging = () => setDragStart(null);
  const updatedAt = new Date(
    activeEvent?.timestamp ?? data.events.at(-1)?.timestamp ?? data.updatedAt,
  );

  return (
    <section className={`${styles.panel} ${styles.mapPanel}`} aria-labelledby="exposure-map-title">
      <header className={styles.mapHeader}>
        <div>
          <h2 id="exposure-map-title">{data.name}曝光态势地图</h2>
          <span className={styles.levelBadge}>{LEVEL_LABELS[data.level]}</span>
          {!data.hasRegionalFacts && <span className={styles.sampleBadge}>区域传播示例</span>}
        </div>
        <span className={styles.updatedAt}>数据更新时间：{updatedAt.toLocaleString("zh-CN")}</span>
      </header>
      <nav className={styles.mapBreadcrumb} aria-label="地图层级">
        <button type="button" onClick={() => onLevelChange("country")}>
          全国
        </button>
        {data.level !== "country" && (
          <>
            <span>/</span>
            <button type="button" onClick={() => onLevelChange("province")}>
              广东省
            </button>
          </>
        )}
        {data.level === "city" && (
          <>
            <span>/</span>
            <strong>广州市</strong>
          </>
        )}
      </nav>
      <div
        ref={hostRef}
        className={`${styles.mapViewport} ${styles[`mapLevel${data.level}`]}`}
        data-width={Math.round(hostSize.width)}
      >
        <div className={styles.mapRadar} aria-hidden="true" />
        {!collection && !mapError && (
          <div className={styles.mapStatus}>
            <LoadingOutlined spin /> 正在载入区域地图
          </div>
        )}
        {mapError && (
          <div className={styles.mapStatus}>
            <EnvironmentOutlined />
            <span>{mapError}</span>
            <button type="button" onClick={() => window.location.reload()}>
              重新加载
            </button>
          </div>
        )}
        {collection && projection && (
          <svg
            className={styles.geoSvg}
            viewBox="0 0 960 600"
            role="img"
            aria-label={`${data.name}曝光传播地图，可滚轮缩放并拖动查看`}
            onWheel={handleWheel}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={stopDragging}
            onPointerCancel={stopDragging}
            onPointerLeave={stopDragging}
          >
            <defs>
              <linearGradient id="map-surface-fill" x1="0" y1="0" x2="0.8" y2="1">
                <stop offset="0" stopColor="#fbfdff" />
                <stop offset="0.58" stopColor="#edf5ff" />
                <stop offset="1" stopColor="#dceaff" />
              </linearGradient>
              <linearGradient id="map-depth-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#c9ddfa" />
                <stop offset="1" stopColor="#8db6ee" />
              </linearGradient>
              <filter id="map-soft-shadow" x="-20%" y="-20%" width="140%" height="155%">
                <feDropShadow
                  dx="0"
                  dy="15"
                  stdDeviation="14"
                  floodColor="#528bd6"
                  floodOpacity="0.22"
                />
              </filter>
            </defs>
            <g transform={`translate(${view.x} ${view.y}) scale(${view.zoom})`}>
              <g className={styles.mapPerspective} filter="url(#map-soft-shadow)">
                <GeoBoundaryLayer
                  collection={collection}
                  projection={projection}
                  depth={data.level === "country" ? 14 : data.level === "province" ? 10 : 5}
                  lockedCode={lockedRegion?.code ?? ""}
                  onHover={(code, name) => setHoveredRegion(emptyRegion(code, name))}
                  onLeave={() => setHoveredRegion(null)}
                  onSelect={selectBoundary}
                />
                <PulseArcLayer event={activeEvent} projection={projection} />
                <TargetPulseLayer
                  regions={data.events.length ? displayedRegions : []}
                  projection={projection}
                  activeEvent={activeEvent}
                  onHover={setHoveredRegion}
                  onLeave={() => setHoveredRegion(null)}
                  onSelect={onLockedRegionChange}
                />
                {(data.level !== "city" || data.hasRegionalFacts) && (
                  <SourcePulseLayer source={data.sourceCity} projection={projection} />
                )}
                <CityLabelLayer regions={displayedRegions} projection={projection} />
              </g>
            </g>
          </svg>
        )}
        <div className={styles.mapTools} aria-label="地图操作">
          <button type="button" aria-label="放大地图" onClick={() => updateZoom(view.zoom * 1.18)}>
            <ZoomInOutlined />
          </button>
          <button type="button" aria-label="缩小地图" onClick={() => updateZoom(view.zoom * 0.84)}>
            <ZoomOutOutlined />
          </button>
          <button
            type="button"
            aria-label="还原地图"
            onClick={() => setView({ zoom: 1, x: 0, y: 0 })}
          >
            <CompressOutlined />
          </button>
          <button type="button" aria-label="刷新地图" onClick={() => onLockedRegionChange(null)}>
            <ReloadOutlined />
          </button>
        </div>
        {data.events.length > 0 && (
          <div className={styles.mapLegend}>
            <span>
              <i className={styles.legendSource} />
              主体源点（广州）
            </span>
            <span>
              <i className={styles.legendTarget} />
              曝光命中区域
            </span>
            <span>
              <i className={styles.legendArc} />
              最新传播路径
            </span>
          </div>
        )}
        {data.level === "city" && !data.events.length && (
          <div className={styles.cityEmptyNotice}>
            区级曝光数据尚未接入，当前仅展示真实行政区边界。
          </div>
        )}
        {hoveredRegion && <GeoTooltip region={hoveredRegion} position={tooltipPosition} />}
      </div>
    </section>
  );
}
