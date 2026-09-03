"use client";

import {
  AimOutlined,
  ArrowLeftOutlined,
  EnvironmentOutlined,
  LoadingOutlined,
  MinusOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import type {
  GeoJSONSource,
  LngLatBoundsLike,
  Map as MapLibreMap,
  MapLayerMouseEvent,
} from "maplibre-gl";
import type { MapboxOverlay } from "@deck.gl/mapbox";

import styles from "../../exposure-command-center.module.css";
import type {
  ExposureEvent,
  ExposureMapData,
  ExposureMapLevel,
  ExposureMapScope,
  GeoJsonCollection,
  GeoJsonFeature,
  GeoPosition,
  RegionExposure,
} from "../../types";
import { GeoTooltip } from "./geo-tooltip";

const BOUNDARY_SOURCE_ID = "exposure-boundaries";
const BOUNDARY_SHADOW_ID = "exposure-boundary-shadow";
const BOUNDARY_DEPTH_ID = "exposure-boundary-depth";
const BOUNDARY_SURFACE_ID = "exposure-boundary-surface";
const BOUNDARY_SELECTED_ID = "exposure-boundary-selected";
const BOUNDARY_LINE_ID = "exposure-boundary-line";

const LEVEL_CAMERA: Record<
  ExposureMapLevel,
  Readonly<{ pitch: number; bearing: number; maxZoom: number; extrusion: number }>
> = {
  country: { pitch: 50, bearing: -8, maxZoom: 3.6, extrusion: 220_000 },
  province: { pitch: 46, bearing: -6, maxZoom: 6.4, extrusion: 46_000 },
  city: { pitch: 42, bearing: -4, maxZoom: 9.5, extrusion: 11_000 },
};

type DeckConstructors = Readonly<{
  ArcLayer: (typeof import("@deck.gl/layers"))["ArcLayer"];
  ScatterplotLayer: (typeof import("@deck.gl/layers"))["ScatterplotLayer"];
  TextLayer: (typeof import("@deck.gl/layers"))["TextLayer"];
}>;

type DeckRuntime = Readonly<{
  overlay: MapboxOverlay;
  constructors: DeckConstructors;
}>;

type HoverInfo = Readonly<{
  region: RegionExposure;
  x: number;
  y: number;
}> | null;

type MapRuntimeState = Readonly<{
  data: ExposureMapData;
  collection: GeoJsonCollection | null;
  visibleEvents: readonly ExposureEvent[];
  activeEvent: ExposureEvent | null;
  lockedRegion: RegionExposure | null;
  navigationPath: readonly ExposureMapScope[];
  onLockedRegionChange: (region: RegionExposure | null) => void;
  onNavigationPathChange: (path: readonly ExposureMapScope[]) => void;
}>;

function levelLabel(data: ExposureMapData) {
  if (data.level === "country") return "全国视图";
  return `${data.level === "province" ? "省级" : "市级"}视图（${data.name.replace(/[省市]$/, "")}）`;
}

function emptyRegion(
  data: ExposureMapData,
  collection: GeoJsonCollection | null,
  code: string,
  name: string,
): RegionExposure {
  const known = data.regions.find((item) => item.code === code || item.name === name);
  if (known) return known;
  const feature = collection?.features.find(
    (item) => String(item.properties.adcode) === code || item.properties.name === name,
  );
  const point = feature?.properties.centroid ?? feature?.properties.center;
  return {
    code,
    name,
    coordinates: point ? [point[0], point[1]] : data.sourceCity.coordinates,
    exposureIndex: null,
    keywordHits: null,
    estimatedExposure: null,
    recommendationRate: null,
    modelCount: null,
    latestHitAt: null,
    cumulativeIntensity: 0,
  };
}

function regionsFromCollection(data: ExposureMapData, collection: GeoJsonCollection | null) {
  const boundaryRegions =
    collection?.features
      .map((feature, index) =>
        emptyRegion(
          data,
          collection,
          String(feature.properties.adcode ?? index),
          feature.properties.name ?? "当前区域",
        ),
      )
      .filter((region) => region.name !== "市辖区") ?? [];
  const byCode = new Map(boundaryRegions.map((region) => [region.code, region]));
  for (const region of data.regions) byCode.set(region.code, region);
  return { boundaryRegions, allRegions: [...byCode.values()] };
}

function sourceVisibleInScope(data: ExposureMapData) {
  if (data.level === "country" || data.sourceCity.code === "100000") return true;
  if (data.level === "province") return data.sourceCity.code.slice(0, 2) === data.code.slice(0, 2);
  return data.sourceCity.code.slice(0, 4) === data.code.slice(0, 4);
}

function visitCoordinates(value: unknown, visit: (point: GeoPosition) => void) {
  if (!Array.isArray(value)) return;
  if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
    visit([value[0], value[1]]);
    return;
  }
  for (const child of value) visitCoordinates(child, visit);
}

function boundsForFeatures(features: readonly GeoJsonFeature[]): LngLatBoundsLike {
  let west = 180;
  let south = 90;
  let east = -180;
  let north = -90;
  for (const feature of features) {
    visitCoordinates(feature.geometry.coordinates, ([longitude, latitude]) => {
      west = Math.min(west, longitude);
      south = Math.min(south, latitude);
      east = Math.max(east, longitude);
      north = Math.max(north, latitude);
    });
  }
  return [
    [west, south],
    [east, north],
  ];
}

function fitMap(
  map: MapLibreMap,
  features: readonly GeoJsonFeature[],
  level: ExposureMapLevel,
  compact = false,
) {
  if (!features.length) return;
  const camera = LEVEL_CAMERA[level];
  map.fitBounds(boundsForFeatures(features), {
    padding: compact ? 88 : level === "country" ? 44 : 58,
    maxZoom: compact ? 10.4 : camera.maxZoom,
    pitch: compact ? Math.max(28, camera.pitch - 5) : camera.pitch,
    bearing: compact ? camera.bearing : camera.bearing,
    duration: 1_250,
    curve: 1.26,
    essential: true,
  });
}

function updateSelectedBoundary(map: MapLibreMap, code: string) {
  if (!map.getLayer(BOUNDARY_SELECTED_ID)) return;
  const numericCode = Number(code);
  map.setFilter(
    BOUNDARY_SELECTED_ID,
    code && Number.isFinite(numericCode) ? ["==", "adcode", numericCode] : ["==", "adcode", -1],
  );
}

function installOrUpdateBoundary(
  map: MapLibreMap,
  collection: GeoJsonCollection,
  data: ExposureMapData,
  lockedCode: string,
) {
  const source = map.getSource(BOUNDARY_SOURCE_ID) as GeoJSONSource | undefined;
  if (source) {
    source.setData(collection as Parameters<GeoJSONSource["setData"]>[0]);
  } else {
    map.addSource(BOUNDARY_SOURCE_ID, {
      type: "geojson",
      data: collection as Parameters<GeoJSONSource["setData"]>[0],
    });
  }

  const camera = LEVEL_CAMERA[data.level];
  if (!map.getLayer(BOUNDARY_SHADOW_ID)) {
    map.addLayer({
      id: BOUNDARY_SHADOW_ID,
      type: "fill",
      source: BOUNDARY_SOURCE_ID,
      paint: {
        "fill-color": "#346fc5",
        "fill-opacity": 0.2,
        "fill-translate": [0, 20],
        "fill-translate-anchor": "viewport",
      },
    });
    map.addLayer({
      id: BOUNDARY_DEPTH_ID,
      type: "fill-extrusion",
      source: BOUNDARY_SOURCE_ID,
      paint: {
        "fill-extrusion-base": 0,
        "fill-extrusion-height": camera.extrusion,
        "fill-extrusion-color": "#658dc8",
        "fill-extrusion-opacity": 0.92,
        "fill-extrusion-vertical-gradient": true,
      },
    });
    map.addLayer({
      id: BOUNDARY_SURFACE_ID,
      type: "fill",
      source: BOUNDARY_SOURCE_ID,
      paint: {
        "fill-color": "#c6ddfb",
        "fill-opacity": 0.94,
      },
    });
    map.addLayer({
      id: BOUNDARY_SELECTED_ID,
      type: "fill",
      source: BOUNDARY_SOURCE_ID,
      filter: ["==", "adcode", -1],
      paint: { "fill-color": "#72a9f5", "fill-opacity": 0.88 },
    });
    map.addLayer({
      id: BOUNDARY_LINE_ID,
      type: "line",
      source: BOUNDARY_SOURCE_ID,
      paint: {
        "line-color": "#f4f9ff",
        "line-width": ["interpolate", ["linear"], ["zoom"], 2, 1.05, 9, 1.85],
        "line-opacity": 0.96,
      },
    });
  } else {
    map.setPaintProperty(BOUNDARY_DEPTH_ID, "fill-extrusion-height", camera.extrusion);
  }
  updateSelectedBoundary(map, lockedCode);
  fitMap(map, collection.features, data.level);
}

function clamp(value: number, minimum = 0, maximum = 1) {
  return Math.min(maximum, Math.max(minimum, value));
}

function easeInOut(value: number) {
  const bounded = clamp(value);
  return bounded < 0.5 ? 4 * bounded * bounded * bounded : 1 - Math.pow(-2 * bounded + 2, 3) / 2;
}

function distanceInKilometres(from: GeoPosition, to: GeoPosition) {
  const latitude = ((from[1] + to[1]) / 2) * (Math.PI / 180);
  const longitudeDistance = (to[0] - from[0]) * 111.32 * Math.cos(latitude);
  const latitudeDistance = (to[1] - from[1]) * 110.57;
  return Math.hypot(longitudeDistance, latitudeDistance);
}

function particlePosition(event: ExposureEvent, progress: number): [number, number, number] {
  const travelled = easeInOut(progress);
  const longitude =
    event.sourceCoordinates[0] +
    (event.targetCoordinates[0] - event.sourceCoordinates[0]) * travelled;
  const latitude =
    event.sourceCoordinates[1] +
    (event.targetCoordinates[1] - event.sourceCoordinates[1]) * travelled;
  const altitude =
    Math.sin(Math.PI * travelled) *
    Math.min(
      420_000,
      Math.max(
        22_000,
        distanceInKilometres(event.sourceCoordinates, event.targetCoordinates) * 150,
      ),
    );
  return [longitude, latitude, altitude];
}

function buildDeckLayers(
  constructors: DeckConstructors,
  runtime: MapRuntimeState,
  progress: number,
  hoverRef: MutableRefObject<(info: HoverInfo) => void>,
) {
  const { ArcLayer, ScatterplotLayer, TextLayer } = constructors;
  const { data, visibleEvents, activeEvent } = runtime;
  const { boundaryRegions, allRegions } = regionsFromCollection(data, runtime.collection);
  const historicalCodes = new Set(
    visibleEvents
      .filter((event) => event.id !== activeEvent?.id)
      .map((event) => event.targetRegionCode),
  );
  const historicalRegions = allRegions.filter((region) => historicalCodes.has(region.code));
  const historicalEvents = visibleEvents
    .filter(
      (event) => event.id !== activeEvent?.id && event.sourceRegionCode !== event.targetRegionCode,
    )
    .slice(-8);
  const crossRegion =
    activeEvent && activeEvent.sourceRegionCode !== activeEvent.targetRegionCode
      ? activeEvent
      : null;
  const localHit =
    activeEvent && activeEvent.sourceRegionCode === activeEvent.targetRegionCode
      ? activeEvent
      : null;
  const travelProgress = clamp((progress - 0.08) / 0.58);
  const hasArrived = Boolean(activeEvent && progress >= 0.66);
  const arrivalProgress = clamp((progress - 0.66) / 0.34);
  const arcOpacity = Math.round(
    230 * clamp(progress / 0.13) * (progress > 0.78 ? 1 - (progress - 0.78) / 0.22 : 1),
  );
  const pulseOpacity = Math.round(188 * (1 - arrivalProgress));
  const labelCharacters = Array.from(
    new Set(boundaryRegions.flatMap((region) => Array.from(region.name))),
  );
  const sourceRegions = sourceVisibleInScope(data) ? [data.sourceCity] : [];
  const cityLabelOffsets: Readonly<Record<string, readonly [number, number]>> = {
    "440103": [-21, -15],
    "440104": [18, -14],
    "440105": [-19, 14],
    "440106": [23, 1],
    "440111": [-9, -20],
    "440112": [22, 16],
  };

  const onRegionHover = (info: { object?: RegionExposure; x: number; y: number }) => {
    hoverRef.current(info.object ? { region: info.object, x: info.x + 14, y: info.y + 14 } : null);
  };

  return [
    new ScatterplotLayer<RegionExposure>({
      id: "neutral-regions",
      data: boundaryRegions,
      pickable: true,
      radiusUnits: "pixels",
      getRadius: 2.8,
      radiusMinPixels: 2.5,
      radiusMaxPixels: 5,
      getPosition: (region) => region.coordinates,
      getFillColor: [44, 101, 185, 132],
      stroked: true,
      getLineColor: [245, 250, 255, 225],
      getLineWidth: 1.2,
      lineWidthUnits: "pixels",
      onHover: onRegionHover,
      onClick: (info) => {
        if (info.object) runtime.onLockedRegionChange(info.object);
      },
    }),
    new ScatterplotLayer<RegionExposure>({
      id: "historical-regions",
      data: historicalRegions,
      pickable: false,
      radiusUnits: "pixels",
      getRadius: 7,
      getPosition: (region) => region.coordinates,
      getFillColor: [236, 126, 105, 24],
      stroked: true,
      getLineColor: [238, 122, 102, 42],
      getLineWidth: 1,
      lineWidthUnits: "pixels",
    }),
    new ScatterplotLayer<RegionExposure>({
      id: "source-idle-halo",
      data: sourceRegions,
      pickable: false,
      radiusUnits: "pixels",
      getRadius: progress < 0.22 && activeEvent ? 20 + progress * 36 : 14,
      getPosition: (region) => region.coordinates,
      getFillColor: activeEvent && progress < 0.22 ? [255, 77, 66, 92] : [43, 111, 246, 42],
    }),
    new ScatterplotLayer<RegionExposure>({
      id: "source-core",
      data: sourceRegions,
      pickable: true,
      radiusUnits: "pixels",
      getRadius: activeEvent && progress < 0.22 ? 6.2 : 4.5,
      getPosition: (region) => region.coordinates,
      getFillColor: activeEvent ? [255, 78, 66, 255] : [28, 98, 225, 245],
      stroked: true,
      getLineColor: [255, 255, 255, 238],
      getLineWidth: 2,
      lineWidthUnits: "pixels",
      onHover: onRegionHover,
      onClick: () => runtime.onLockedRegionChange(data.sourceCity),
    }),
    new ArcLayer<ExposureEvent>({
      id: "historical-arcs",
      data: historicalEvents,
      greatCircle: true,
      numSegments: 72,
      getSourcePosition: (event) => event.sourceCoordinates,
      getTargetPosition: (event) => event.targetCoordinates,
      getSourceColor: [237, 105, 91, 72],
      getTargetColor: [246, 145, 112, 34],
      getWidth: 1.15,
      widthUnits: "pixels",
      getHeight: data.level === "country" ? 0.48 : data.level === "province" ? 0.28 : 0.16,
    }),
    crossRegion
      ? new ArcLayer<ExposureEvent>({
          id: `active-arc-glow-${crossRegion.id}`,
          data: [crossRegion],
          greatCircle: true,
          numSegments: 96,
          getSourcePosition: (event) => event.sourceCoordinates,
          getTargetPosition: (event) => event.targetCoordinates,
          getSourceColor: [255, 76, 62, Math.round(arcOpacity * 0.3)],
          getTargetColor: [255, 149, 84, Math.round(arcOpacity * 0.18)],
          getWidth: 9,
          widthUnits: "pixels",
          getHeight: data.level === "country" ? 0.58 : data.level === "province" ? 0.34 : 0.2,
        })
      : null,
    crossRegion
      ? new ArcLayer<ExposureEvent>({
          id: `active-arc-${crossRegion.id}`,
          data: [crossRegion],
          greatCircle: true,
          numSegments: 96,
          getSourcePosition: (event) => event.sourceCoordinates,
          getTargetPosition: (event) => event.targetCoordinates,
          getSourceColor: [255, 91, 78, arcOpacity],
          getTargetColor: [255, 126, 105, Math.round(arcOpacity * 0.72)],
          getWidth: 3.1,
          widthUnits: "pixels",
          getHeight: data.level === "country" ? 0.58 : data.level === "province" ? 0.34 : 0.2,
        })
      : null,
    crossRegion && progress >= 0.08 && progress <= 0.72
      ? new ScatterplotLayer<ExposureEvent>({
          id: `travelling-pulse-${crossRegion.id}`,
          data: [crossRegion],
          pickable: false,
          radiusUnits: "pixels",
          getRadius: 8,
          getPosition: (event) => particlePosition(event, travelProgress),
          getFillColor: [255, 255, 255, 255],
          stroked: true,
          getLineColor: [255, 72, 64, 255],
          getLineWidth: 5,
          lineWidthUnits: "pixels",
          updateTriggers: { getPosition: Math.round(progress * 1_000) },
        })
      : null,
    hasArrived && activeEvent
      ? new ScatterplotLayer<ExposureEvent>({
          id: `arrival-core-${activeEvent.id}`,
          data: [activeEvent],
          pickable: false,
          radiusUnits: "pixels",
          getRadius: 5.6,
          getPosition: (event) => event.targetCoordinates,
          getFillColor: [255, 74, 66, Math.max(78, pulseOpacity)],
          stroked: true,
          getLineColor: [255, 255, 255, 236],
          getLineWidth: 1.6,
          lineWidthUnits: "pixels",
        })
      : null,
    (hasArrived && activeEvent) || localHit
      ? new ScatterplotLayer<ExposureEvent>({
          id: `arrival-ring-${activeEvent?.id ?? localHit?.id}`,
          data: activeEvent ? [activeEvent] : localHit ? [localHit] : [],
          pickable: false,
          radiusUnits: "pixels",
          getRadius: 8 + arrivalProgress * 28,
          getPosition: (event) => event.targetCoordinates,
          filled: false,
          stroked: true,
          getLineColor: [255, 82, 73, pulseOpacity],
          getLineWidth: 2.2,
          lineWidthUnits: "pixels",
          updateTriggers: {
            getRadius: Math.round(progress * 1_000),
            getLineColor: pulseOpacity,
          },
        })
      : null,
    (hasArrived && activeEvent) || localHit
      ? new ScatterplotLayer<ExposureEvent>({
          id: `arrival-outer-ring-${activeEvent?.id ?? localHit?.id}`,
          data: activeEvent ? [activeEvent] : localHit ? [localHit] : [],
          pickable: false,
          radiusUnits: "pixels",
          getRadius: 13 + arrivalProgress * 48,
          getPosition: (event) => event.targetCoordinates,
          filled: false,
          stroked: true,
          getLineColor: [255, 119, 86, Math.round(pulseOpacity * 0.62)],
          getLineWidth: 1.4,
          lineWidthUnits: "pixels",
          updateTriggers: {
            getRadius: Math.round(progress * 1_000),
            getLineColor: pulseOpacity,
          },
        })
      : null,
    new TextLayer<RegionExposure>({
      id: "region-labels",
      data: boundaryRegions,
      pickable: false,
      getPosition: (region) => region.coordinates,
      getText: (region) => region.name,
      getColor: [30, 47, 75, 220],
      getSize: data.level === "country" ? 12 : data.level === "province" ? 11 : 12,
      getPixelOffset: (region) =>
        data.level === "city" ? (cityLabelOffsets[region.code] ?? [0, -13]) : [0, -13],
      sizeUnits: "pixels",
      fontFamily: '"Microsoft YaHei", "PingFang SC", sans-serif',
      fontWeight: 650,
      characterSet: labelCharacters,
      fontSettings: { sdf: true, fontSize: 64, buffer: 6, radius: 3, cutoff: 0.25 },
      outlineWidth: 3,
      outlineColor: [235, 245, 255, 250],
    }),
  ].filter(Boolean);
}

export function GeoExposureMap({
  data,
  visibleEvents,
  activeEvent,
  eventPlaybackKey,
  lockedRegion,
  navigationPath,
  onLockedRegionChange,
  onNavigationPathChange,
}: Readonly<{
  data: ExposureMapData;
  visibleEvents: readonly ExposureEvent[];
  activeEvent: ExposureEvent | null;
  eventPlaybackKey: string;
  lockedRegion: RegionExposure | null;
  navigationPath: readonly ExposureMapScope[];
  onLockedRegionChange: (region: RegionExposure | null) => void;
  onNavigationPathChange: (path: readonly ExposureMapScope[]) => void;
}>) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const deckRef = useRef<DeckRuntime | null>(null);
  const frameRef = useRef<number | null>(null);
  const cameraFrameRef = useRef<number | null>(null);
  const cameraPauseUntilRef = useRef(0);
  const runtimeRef = useRef<MapRuntimeState>({
    data,
    collection: null,
    visibleEvents,
    activeEvent,
    lockedRegion,
    navigationPath,
    onLockedRegionChange,
    onNavigationPathChange,
  });
  const [collection, setCollection] = useState<GeoJsonCollection | null>(null);
  const [boundaryUrl, setBoundaryUrl] = useState("");
  const [errorState, setErrorState] = useState({ url: "", message: "" });
  const [mapReady, setMapReady] = useState(false);
  const [hostWidth, setHostWidth] = useState(0);
  const [hoverInfo, setHoverInfo] = useState<HoverInfo>(null);
  const hoverSetterRef = useRef<(info: HoverInfo) => void>(setHoverInfo);

  const currentCollection = boundaryUrl === data.boundaryUrl ? collection : null;
  const mapError = errorState.url === data.boundaryUrl ? errorState.message : "";

  useEffect(() => {
    runtimeRef.current = {
      data,
      collection: currentCollection,
      visibleEvents,
      activeEvent,
      lockedRegion,
      navigationPath,
      onLockedRegionChange,
      onNavigationPathChange,
    };
  }, [
    activeEvent,
    currentCollection,
    data,
    lockedRegion,
    navigationPath,
    onNavigationPathChange,
    onLockedRegionChange,
    visibleEvents,
  ]);

  useEffect(() => {
    const controller = new AbortController();
    void fetch(data.boundaryUrl, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("区域地图暂时无法载入");
        return response.json() as Promise<GeoJsonCollection>;
      })
      .then((nextCollection) => {
        setBoundaryUrl(data.boundaryUrl);
        setCollection(nextCollection);
        setErrorState({ url: data.boundaryUrl, message: "" });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setBoundaryUrl(data.boundaryUrl);
        setCollection(null);
        setErrorState({
          url: data.boundaryUrl,
          message: reason instanceof Error ? reason.message : "区域地图暂时无法显示",
        });
      });
    return () => controller.abort();
  }, [data.boundaryUrl]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setHostWidth(Math.round(entry.contentRect.width));
      mapRef.current?.resize();
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (
      !currentCollection ||
      !hostRef.current ||
      mapRef.current ||
      typeof WebGLRenderingContext === "undefined"
    ) {
      return;
    }
    let cancelled = false;
    void Promise.all([
      import("maplibre-gl"),
      import("@deck.gl/mapbox"),
      import("@deck.gl/layers"),
    ]).then(([maplibre, deckMapbox, deckLayers]) => {
      if (cancelled || !hostRef.current || mapRef.current) return;
      const map = new maplibre.Map({
        container: hostRef.current,
        style: {
          version: 8,
          sources: {},
          layers: [
            {
              id: "vacuum-background",
              type: "background",
              paint: { "background-color": "rgba(233,243,255,0.04)" },
            },
          ],
        },
        center: [104.2, 35.6],
        zoom: 2.35,
        pitch: LEVEL_CAMERA.country.pitch,
        bearing: LEVEL_CAMERA.country.bearing,
        minZoom: 1.8,
        maxZoom: 12,
        maxPitch: 58,
        attributionControl: false,
        dragRotate: false,
        renderWorldCopies: false,
      });
      map.touchZoomRotate.disableRotation();
      mapRef.current = map;

      const overlay = new deckMapbox.MapboxOverlay({ interleaved: false, layers: [] });
      const constructors: DeckConstructors = {
        ArcLayer: deckLayers.ArcLayer,
        ScatterplotLayer: deckLayers.ScatterplotLayer,
        TextLayer: deckLayers.TextLayer,
      };
      deckRef.current = { overlay, constructors };

      map.once("load", () => {
        if (cancelled) return;
        map.addControl(overlay);
        const runtime = runtimeRef.current;
        if (runtime.collection) {
          installOrUpdateBoundary(
            map,
            runtime.collection,
            runtime.data,
            runtime.lockedRegion?.code ?? "",
          );
        }
        overlay.setProps({
          layers: buildDeckLayers(
            constructors,
            runtime,
            runtime.activeEvent ? 0 : 1,
            hoverSetterRef,
          ),
        });
        setMapReady(true);
      });

      const boundaryFeature = (event: MapLayerMouseEvent) => event.features?.[0];
      const selectFeature = (event: MapLayerMouseEvent) => {
        const feature = boundaryFeature(event);
        if (!feature) return;
        selectRegion(feature as unknown as GeoJsonFeature);
      };
      const hoverFeature = (event: MapLayerMouseEvent) => {
        const feature = boundaryFeature(event);
        if (!feature) return;
        const runtime = runtimeRef.current;
        const code = String(feature.properties?.adcode ?? "");
        const name = String(feature.properties?.name ?? "当前区域");
        map.getCanvas().style.cursor = "pointer";
        hoverSetterRef.current({
          region: emptyRegion(runtime.data, runtime.collection, code, name),
          x: event.point.x + 14,
          y: event.point.y + 14,
        });
      };
      const clearHover = () => {
        map.getCanvas().style.cursor = "grab";
        hoverSetterRef.current(null);
      };
      const clearSelectionOnBlank = (event: MapLayerMouseEvent) => {
        const features = map.queryRenderedFeatures(event.point, { layers: [BOUNDARY_SURFACE_ID] });
        if (features.length) return;
        const runtime = runtimeRef.current;
        runtime.onLockedRegionChange(null);
      };
      function selectRegion(feature: GeoJsonFeature) {
        const runtime = runtimeRef.current;
        const code = String(feature.properties.adcode ?? "");
        const name = feature.properties.name ?? "当前区域";
        const region = emptyRegion(runtime.data, runtime.collection, code, name);
        const isSameOutline = code === runtime.data.code;
        const childLevel = feature.properties.level;
        if (runtime.data.level === "country") {
          runtime.onNavigationPathChange([{ code, name, level: "province" }]);
        } else if (
          runtime.data.level === "province" &&
          childLevel !== "district" &&
          !isSameOutline
        ) {
          runtime.onNavigationPathChange([
            ...runtime.navigationPath,
            { code, name, level: "city" },
          ]);
        } else {
          runtime.onLockedRegionChange(region);
          fitMap(map, [feature], runtime.data.level, true);
        }
      }
      const semanticZoom = (event: { originalEvent?: unknown }) => {
        if (
          !event.originalEvent ||
          map.getZoom() < LEVEL_CAMERA[runtimeRef.current.data.level].maxZoom
        ) {
          return;
        }
        const canvas = map.getCanvas();
        const features = map.queryRenderedFeatures(
          [canvas.clientWidth / 2, canvas.clientHeight / 2],
          { layers: [BOUNDARY_SURFACE_ID] },
        );
        const feature = features[0] as unknown as GeoJsonFeature | undefined;
        if (feature) selectRegion(feature);
      };
      const markInteraction = () => {
        cameraPauseUntilRef.current = performance.now() + 8_000;
      };
      map.on("click", BOUNDARY_SURFACE_ID, selectFeature);
      map.on("mousemove", BOUNDARY_SURFACE_ID, hoverFeature);
      map.on("mouseleave", BOUNDARY_SURFACE_ID, clearHover);
      map.on("click", clearSelectionOnBlank);
      map.on("zoomend", semanticZoom);
      map.on("dragstart", markInteraction);
      map.on("wheel", markInteraction);
      map.on("touchstart", markInteraction);
    });
    return () => {
      cancelled = true;
    };
  }, [currentCollection]);

  useEffect(
    () => () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      if (cameraFrameRef.current !== null) cancelAnimationFrame(cameraFrameRef.current);
      deckRef.current?.overlay.finalize();
      deckRef.current = null;
      mapRef.current?.remove();
      mapRef.current = null;
    },
    [],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !currentCollection || !map.isStyleLoaded()) return;
    installOrUpdateBoundary(
      map,
      currentCollection,
      data,
      runtimeRef.current.lockedRegion?.code ?? "",
    );
  }, [currentCollection, data, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map) return;
    updateSelectedBoundary(map, lockedRegion?.code ?? "");
  }, [lockedRegion?.code, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || activeEvent) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion) return;
    let previousPaint = 0;
    const startedAt = performance.now();
    const animateCamera = (now: number) => {
      if (
        now - previousPaint >= 50 &&
        now >= cameraPauseUntilRef.current &&
        document.visibilityState === "visible" &&
        !map.isMoving()
      ) {
        previousPaint = now;
        const base = LEVEL_CAMERA[runtimeRef.current.data.level].bearing;
        map.setBearing(base + Math.sin((now - startedAt) / 5_200) * 3.2);
      }
      cameraFrameRef.current = requestAnimationFrame(animateCamera);
    };
    cameraFrameRef.current = requestAnimationFrame(animateCamera);
    return () => {
      if (cameraFrameRef.current !== null) cancelAnimationFrame(cameraFrameRef.current);
      cameraFrameRef.current = null;
    };
  }, [activeEvent, data.level, mapReady]);

  useEffect(() => {
    const deck = deckRef.current;
    const map = mapRef.current;
    if (!deck || !mapReady || !map) return;
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    const duration =
      activeEvent?.sourceRegionCode === activeEvent?.targetRegionCode ? 1_550 : 2_750;
    const startedAt = performance.now();
    if (activeEvent && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const midpoint: GeoPosition = [
        (activeEvent.sourceCoordinates[0] + activeEvent.targetCoordinates[0]) / 2,
        (activeEvent.sourceCoordinates[1] + activeEvent.targetCoordinates[1]) / 2,
      ];
      map.easeTo({
        center: [midpoint[0], midpoint[1]],
        zoom: Math.min(map.getZoom() + 0.28, LEVEL_CAMERA[data.level].maxZoom),
        pitch: Math.min(56, LEVEL_CAMERA[data.level].pitch + 3),
        bearing: LEVEL_CAMERA[data.level].bearing + 3,
        duration: 760,
        essential: true,
      });
    }
    const animate = (now: number) => {
      const progress = activeEvent ? clamp((now - startedAt) / duration) : 1;
      deck.overlay.setProps({
        layers: buildDeckLayers(deck.constructors, runtimeRef.current, progress, hoverSetterRef),
      });
      if (progress < 1) frameRef.current = requestAnimationFrame(animate);
      else {
        frameRef.current = null;
        if (currentCollection) fitMap(map, currentCollection.features, data.level);
      }
    };
    frameRef.current = requestAnimationFrame(animate);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    };
  }, [activeEvent, currentCollection, data.level, eventPlaybackKey, mapReady, visibleEvents]);

  const accessibleRegions = useMemo(
    () =>
      currentCollection?.features.map((feature, index) => ({
        code: String(feature.properties.adcode ?? index),
        name: feature.properties.name ?? "当前区域",
      })) ?? [],
    [currentCollection],
  );

  const selectAccessibleRegion = (code: string, name: string) => {
    const feature = currentCollection?.features.find(
      (item) => String(item.properties.adcode) === code,
    );
    if (data.level === "country") {
      onNavigationPathChange([{ code, name, level: "province" }]);
    } else if (
      data.level === "province" &&
      feature?.properties.level !== "district" &&
      code !== data.code
    ) {
      onNavigationPathChange([...navigationPath, { code, name, level: "city" }]);
    } else {
      onLockedRegionChange(emptyRegion(data, currentCollection, code, name));
      if (feature && mapRef.current) fitMap(mapRef.current, [feature], data.level, true);
    }
  };

  const returnOneLevel = () => {
    if (lockedRegion) {
      onLockedRegionChange(null);
      if (currentCollection && mapRef.current) {
        fitMap(mapRef.current, currentCollection.features, data.level);
      }
    } else {
      onNavigationPathChange(navigationPath.slice(0, -1));
    }
  };

  const updatedAt = new Date(
    activeEvent?.timestamp ?? visibleEvents.at(-1)?.timestamp ?? data.updatedAt,
  );

  return (
    <section className={`${styles.panel} ${styles.mapPanel}`} aria-labelledby="exposure-map-title">
      <header className={styles.mapHeader}>
        <div>
          <h2 id="exposure-map-title">{data.name}曝光态势地图</h2>
          <span className={styles.levelBadge}>{levelLabel(data)}</span>
          {!data.events.length ? (
            <span className={styles.neutralBadge}>暂无地域传播事件</span>
          ) : null}
        </div>
        <span className={styles.updatedAt}>数据更新时间：{updatedAt.toLocaleString("zh-CN")}</span>
      </header>

      <nav className={styles.mapBreadcrumb} aria-label="地图层级">
        {!navigationPath.length ? (
          <strong>全国</strong>
        ) : (
          <button type="button" onClick={() => onNavigationPathChange([])}>
            全国
          </button>
        )}
        {navigationPath.map((scope, index) => {
          const last = index === navigationPath.length - 1 && !lockedRegion;
          return (
            <span className={styles.breadcrumbPart} key={scope.code}>
              <span>›</span>
              {last ? (
                <strong>{scope.name}</strong>
              ) : (
                <button
                  type="button"
                  onClick={() => onNavigationPathChange(navigationPath.slice(0, index + 1))}
                >
                  {scope.name}
                </button>
              )}
            </span>
          );
        })}
        {lockedRegion ? (
          <span className={styles.breadcrumbPart}>
            <span>›</span>
            <strong>{lockedRegion.name}</strong>
          </span>
        ) : null}
      </nav>

      {navigationPath.length || lockedRegion ? (
        <button
          type="button"
          className={styles.mapBackButton}
          aria-label="返回上一级"
          onClick={returnOneLevel}
        >
          <ArrowLeftOutlined /> 返回上一级
        </button>
      ) : null}

      <div
        ref={hostRef}
        className={`${styles.mapViewport} ${styles[`mapLevel${data.level}`]}`}
        data-width={hostWidth}
      >
        <div className={styles.vacuumGrid} aria-hidden="true" />
        <div className={styles.hudArcTop} aria-hidden="true" />
        <div className={styles.hudArcBottom} aria-hidden="true" />
        <div className={styles.mapEnergyBase} aria-hidden="true" />

        {!currentCollection && !mapError ? (
          <div className={styles.mapStatus}>
            <LoadingOutlined spin /> 正在载入区域地图
          </div>
        ) : null}
        {mapError ? (
          <div className={styles.mapStatus}>
            <EnvironmentOutlined />
            <span>{mapError}</span>
            <button type="button" onClick={() => window.location.reload()}>
              重新加载
            </button>
          </div>
        ) : null}

        <div className={styles.mapTools} aria-label="地图操作">
          <button type="button" aria-label="放大地图" onClick={() => mapRef.current?.zoomIn()}>
            <PlusOutlined />
          </button>
          <button type="button" aria-label="缩小地图" onClick={() => mapRef.current?.zoomOut()}>
            <MinusOutlined />
          </button>
          <button
            type="button"
            aria-label="还原地图"
            onClick={() => {
              onLockedRegionChange(null);
              if (currentCollection && mapRef.current) {
                fitMap(mapRef.current, currentCollection.features, data.level);
              }
            }}
          >
            <AimOutlined />
          </button>
        </div>

        <div className={styles.mapLegend}>
          <span>
            <i className={styles.legendNeutral} /> 未发生曝光
          </span>
          <span>
            <i className={styles.legendHistorical} /> 历史曝光
          </span>
          <span>
            <i className={styles.legendSource} /> 主体源点
          </span>
          <span>
            <i className={styles.legendTarget} /> 当前传播
          </span>
        </div>

        {data.level === "city" && !data.events.length ? (
          <div className={styles.cityEmptyNotice}>当前仅展示真实行政区边界，暂无区级曝光记录。</div>
        ) : null}
        {hoverInfo ? (
          <GeoTooltip
            region={hoverInfo.region}
            position={{
              x: Math.min(Math.max(12, hoverInfo.x), Math.max(12, hostWidth - 238)),
              y: Math.max(70, hoverInfo.y),
            }}
          />
        ) : null}
        <div className={styles.accessibleMapRegions} aria-label="可选择区域">
          {accessibleRegions.map((region) => (
            <button
              key={region.code}
              type="button"
              aria-label={`${region.name}区域`}
              onClick={() => selectAccessibleRegion(region.code, region.name)}
            >
              {region.name}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
