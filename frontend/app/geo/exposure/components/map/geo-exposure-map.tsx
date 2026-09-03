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

const LEVEL_LABELS: Record<ExposureMapLevel, string> = {
  country: "全国视图",
  province: "省级视图（广东）",
  city: "市级视图（广州）",
};

const LEVEL_CAMERA: Record<
  ExposureMapLevel,
  Readonly<{ pitch: number; bearing: number; maxZoom: number; extrusion: number }>
> = {
  country: { pitch: 31, bearing: -4, maxZoom: 3.7, extrusion: 18_000 },
  province: { pitch: 20, bearing: -2, maxZoom: 6.5, extrusion: 3_200 },
  city: { pitch: 7, bearing: 0, maxZoom: 9.8, extrusion: 480 },
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
  onLockedRegionChange: (region: RegionExposure | null) => void;
  onLevelChange: (level: ExposureMapLevel) => void;
}>;

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
    pitch: compact ? 3 : camera.pitch,
    bearing: compact ? 0 : camera.bearing,
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
        "fill-color": "#7aa6e8",
        "fill-opacity": 0.12,
        "fill-translate": [0, 12],
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
        "fill-extrusion-color": "#a9c9f3",
        "fill-extrusion-opacity": 0.56,
        "fill-extrusion-vertical-gradient": true,
      },
    });
    map.addLayer({
      id: BOUNDARY_SURFACE_ID,
      type: "fill",
      source: BOUNDARY_SOURCE_ID,
      paint: {
        "fill-color": [
          "interpolate",
          ["linear"],
          ["coalesce", ["get", "adcode"], 0],
          100000,
          "#f9fcff",
          900000,
          "#e2efff",
        ],
        "fill-opacity": 0.9,
      },
    });
    map.addLayer({
      id: BOUNDARY_SELECTED_ID,
      type: "fill",
      source: BOUNDARY_SOURCE_ID,
      filter: ["==", "adcode", -1],
      paint: { "fill-color": "#cfe3ff", "fill-opacity": 0.68 },
    });
    map.addLayer({
      id: BOUNDARY_LINE_ID,
      type: "line",
      source: BOUNDARY_SOURCE_ID,
      paint: {
        "line-color": "#84b8f3",
        "line-width": ["interpolate", ["linear"], ["zoom"], 2, 0.8, 9, 1.5],
        "line-opacity": 0.82,
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
  const historicalCodes = new Set(
    visibleEvents
      .filter((event) => event.id !== activeEvent?.id)
      .map((event) => event.targetRegionCode),
  );
  const historicalRegions = data.regions.filter((region) => historicalCodes.has(region.code));
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
    new Set(data.regions.flatMap((region) => Array.from(region.name))),
  );
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
      data: [...data.regions],
      pickable: true,
      radiusUnits: "pixels",
      getRadius: 3.3,
      radiusMinPixels: 2.5,
      radiusMaxPixels: 5,
      getPosition: (region) => region.coordinates,
      getFillColor: [100, 116, 139, 118],
      stroked: true,
      getLineColor: [230, 240, 252, 210],
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
      data: [data.sourceCity],
      pickable: false,
      radiusUnits: "pixels",
      getRadius: progress < 0.2 && activeEvent ? 14 + progress * 22 : 11,
      getPosition: (region) => region.coordinates,
      getFillColor: [255, 86, 76, activeEvent && progress < 0.22 ? 48 : 19],
    }),
    new ScatterplotLayer<RegionExposure>({
      id: "source-core",
      data: [data.sourceCity],
      pickable: true,
      radiusUnits: "pixels",
      getRadius: activeEvent && progress < 0.22 ? 6.2 : 4.5,
      getPosition: (region) => region.coordinates,
      getFillColor: [21, 31, 52, 245],
      stroked: true,
      getLineColor: [255, 106, 96, 120],
      getLineWidth: 2,
      lineWidthUnits: "pixels",
      onHover: onRegionHover,
      onClick: () => runtime.onLockedRegionChange(data.sourceCity),
    }),
    crossRegion
      ? new ArcLayer<ExposureEvent>({
          id: `active-arc-${crossRegion.id}`,
          data: [crossRegion],
          greatCircle: true,
          numSegments: 72,
          getSourcePosition: (event) => event.sourceCoordinates,
          getTargetPosition: (event) => event.targetCoordinates,
          getSourceColor: [255, 91, 78, arcOpacity],
          getTargetColor: [255, 126, 105, Math.round(arcOpacity * 0.72)],
          getWidth: 2.1,
          widthUnits: "pixels",
          getHeight: data.level === "country" ? 0.48 : data.level === "province" ? 0.28 : 0.14,
        })
      : null,
    crossRegion && progress >= 0.08 && progress <= 0.72
      ? new ScatterplotLayer<ExposureEvent>({
          id: `travelling-pulse-${crossRegion.id}`,
          data: [crossRegion],
          pickable: false,
          radiusUnits: "pixels",
          getRadius: 5.5,
          getPosition: (event) => particlePosition(event, travelProgress),
          getFillColor: [255, 255, 255, 255],
          stroked: true,
          getLineColor: [255, 72, 64, 255],
          getLineWidth: 3,
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
    new TextLayer<RegionExposure>({
      id: "region-labels",
      data: [...data.regions],
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
      outlineColor: [247, 251, 255, 245],
    }),
  ].filter(Boolean);
}

export function GeoExposureMap({
  data,
  visibleEvents,
  activeEvent,
  eventPlaybackKey,
  lockedRegion,
  onLockedRegionChange,
  onLevelChange,
}: Readonly<{
  data: ExposureMapData;
  visibleEvents: readonly ExposureEvent[];
  activeEvent: ExposureEvent | null;
  eventPlaybackKey: string;
  lockedRegion: RegionExposure | null;
  onLockedRegionChange: (region: RegionExposure | null) => void;
  onLevelChange: (level: ExposureMapLevel) => void;
}>) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const deckRef = useRef<DeckRuntime | null>(null);
  const frameRef = useRef<number | null>(null);
  const runtimeRef = useRef<MapRuntimeState>({
    data,
    collection: null,
    visibleEvents,
    activeEvent,
    lockedRegion,
    onLockedRegionChange,
    onLevelChange,
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
      onLockedRegionChange,
      onLevelChange,
    };
  }, [
    activeEvent,
    currentCollection,
    data,
    lockedRegion,
    onLevelChange,
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
        maxPitch: 48,
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
        const runtime = runtimeRef.current;
        const code = String(feature.properties?.adcode ?? "");
        const name = String(feature.properties?.name ?? "当前区域");
        if (runtime.data.level === "country" && code === "440000") {
          runtime.onLevelChange("province");
          return;
        }
        if (runtime.data.level === "province" && code === "440100") {
          runtime.onLevelChange("city");
          return;
        }
        const region = emptyRegion(runtime.data, runtime.collection, code, name);
        runtime.onLockedRegionChange(region);
        if (runtime.data.level === "city") {
          fitMap(map, [feature as unknown as GeoJsonFeature], "city", true);
        }
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
        if (runtime.data.level !== "country") runtime.onLevelChange("country");
      };
      const semanticZoom = () => {
        const runtime = runtimeRef.current;
        const center = map.getCenter();
        if (
          runtime.data.level === "country" &&
          map.getZoom() >= 4.15 &&
          center.lng >= 108.8 &&
          center.lng <= 117.4 &&
          center.lat >= 19.5 &&
          center.lat <= 25.7
        ) {
          runtime.onLevelChange("province");
        } else if (
          runtime.data.level === "province" &&
          map.getZoom() >= 7.2 &&
          center.lng >= 112.6 &&
          center.lng <= 114.1 &&
          center.lat >= 22.5 &&
          center.lat <= 23.9
        ) {
          runtime.onLevelChange("city");
        }
      };
      map.on("click", BOUNDARY_SURFACE_ID, selectFeature);
      map.on("mousemove", BOUNDARY_SURFACE_ID, hoverFeature);
      map.on("mouseleave", BOUNDARY_SURFACE_ID, clearHover);
      map.on("click", clearSelectionOnBlank);
      map.on("zoomend", semanticZoom);
    });
    return () => {
      cancelled = true;
    };
  }, [currentCollection]);

  useEffect(
    () => () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
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
    const deck = deckRef.current;
    if (!deck || !mapReady) return;
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    const duration =
      activeEvent?.sourceRegionCode === activeEvent?.targetRegionCode ? 1_550 : 2_750;
    const startedAt = performance.now();
    const animate = (now: number) => {
      const progress = activeEvent ? clamp((now - startedAt) / duration) : 1;
      deck.overlay.setProps({
        layers: buildDeckLayers(deck.constructors, runtimeRef.current, progress, hoverSetterRef),
      });
      if (progress < 1) frameRef.current = requestAnimationFrame(animate);
      else frameRef.current = null;
    };
    frameRef.current = requestAnimationFrame(animate);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    };
  }, [activeEvent, eventPlaybackKey, mapReady, visibleEvents]);

  const accessibleRegions = useMemo(
    () =>
      currentCollection?.features.map((feature, index) => ({
        code: String(feature.properties.adcode ?? index),
        name: feature.properties.name ?? "当前区域",
      })) ?? [],
    [currentCollection],
  );

  const selectAccessibleRegion = (code: string, name: string) => {
    if (data.level === "country" && code === "440000") onLevelChange("province");
    else if (data.level === "province" && code === "440100") onLevelChange("city");
    else if (data.level === "city") {
      const region = emptyRegion(data, currentCollection, code, name);
      onLockedRegionChange(region);
      const feature = currentCollection?.features.find(
        (item) => String(item.properties.adcode) === code,
      );
      if (feature && mapRef.current) fitMap(mapRef.current, [feature], "city", true);
    }
  };

  const returnOneLevel = () => {
    if (data.level === "city" && lockedRegion) {
      onLockedRegionChange(null);
      if (currentCollection && mapRef.current) {
        fitMap(mapRef.current, currentCollection.features, "city");
      }
    } else if (data.level === "city") onLevelChange("province");
    else if (data.level === "province") onLevelChange("country");
  };

  const updatedAt = new Date(
    activeEvent?.timestamp ?? visibleEvents.at(-1)?.timestamp ?? data.updatedAt,
  );

  return (
    <section className={`${styles.panel} ${styles.mapPanel}`} aria-labelledby="exposure-map-title">
      <header className={styles.mapHeader}>
        <div>
          <h2 id="exposure-map-title">{data.name}曝光态势地图</h2>
          <span className={styles.levelBadge}>{LEVEL_LABELS[data.level]}</span>
          {!data.events.length ? (
            <span className={styles.neutralBadge}>暂无地域传播事件</span>
          ) : null}
        </div>
        <span className={styles.updatedAt}>数据更新时间：{updatedAt.toLocaleString("zh-CN")}</span>
      </header>

      <nav className={styles.mapBreadcrumb} aria-label="地图层级">
        {data.level === "country" ? (
          <strong>全国</strong>
        ) : (
          <button type="button" onClick={() => onLevelChange("country")}>
            全国
          </button>
        )}
        {data.level !== "country" ? <span>›</span> : null}
        {data.level === "province" ? (
          <strong>广东省</strong>
        ) : data.level === "city" ? (
          <button type="button" onClick={() => onLevelChange("province")}>
            广东省
          </button>
        ) : null}
        {data.level === "city" ? <span>›</span> : null}
        {data.level === "city" && lockedRegion ? (
          <>
            <button
              type="button"
              onClick={() => {
                onLockedRegionChange(null);
                if (currentCollection && mapRef.current) {
                  fitMap(mapRef.current, currentCollection.features, "city");
                }
              }}
            >
              广州市
            </button>
            <span>›</span>
            <strong>{lockedRegion.name}</strong>
          </>
        ) : data.level === "city" ? (
          <strong>广州市</strong>
        ) : null}
      </nav>

      {data.level !== "country" || lockedRegion ? (
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
