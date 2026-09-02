"use client";

import {
  CalendarOutlined,
  DownloadOutlined,
  GlobalOutlined,
  RadarChartOutlined,
} from "@ant-design/icons";
import { Button, Select } from "antd";
import { useEffect, useMemo, useState } from "react";

import type { GeoReport } from "@/lib/geo-report-client";

import styles from "../exposure-command-center.module.css";
import type { ExposureCockpitData, ExposureMapLevel, RegionExposure } from "../types";
import { CompetitorIndexPanel } from "./competitor-index-panel";
import { ExposureTimeline } from "./exposure-timeline";
import { GeoExposureMap } from "./map/geo-exposure-map";
import { KeywordExposurePanel } from "./keyword-exposure-panel";
import { ModelScorePanel } from "./model-score-panel";
import { TrendingQuestionsPanel } from "./trending-questions-panel";

function reportLabel(report: GeoReport) {
  const date = new Date(report.generated_at);
  return `${date.toLocaleDateString("zh-CN")} · 曝光 ${Number(
    report.summary.exposure.exposure_index,
  ).toFixed(1)}`;
}

function shortTime(timestamp: string | undefined) {
  if (!timestamp) return "--:--:--";
  return new Date(timestamp).toLocaleTimeString("zh-CN", { hour12: false });
}

export function ExposureCockpitPage({
  data,
  reports,
  subjectName,
  selectedReportId,
  onReportChange,
}: Readonly<{
  data: ExposureCockpitData;
  reports: readonly GeoReport[];
  subjectName: string;
  selectedReportId: string;
  onReportChange: (reportId: string) => void;
}>) {
  const [level, setLevel] = useState<ExposureMapLevel>("country");
  const [selectedModel, setSelectedModel] = useState("");
  const [lockedRegion, setLockedRegion] = useState<RegionExposure | null>(null);
  const [mode, setMode] = useState<"live" | "replay">("live");
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<1 | 2>(1);
  const [progress, setProgress] = useState(100);
  const [liveIndex, setLiveIndex] = useState(0);
  const currentMap = data.maps[level];
  const events = useMemo(
    () =>
      [...currentMap.events]
        .filter(
          (event) =>
            !selectedModel || event.model.toLowerCase().includes(selectedModel.toLowerCase()),
        )
        .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp)),
    [currentMap.events, selectedModel],
  );

  useEffect(() => {
    if (!playing || mode !== "live" || events.length <= 1) return;
    const timer = window.setInterval(
      () => setLiveIndex((current) => (current + 1) % events.length),
      speed === 2 ? 1350 : 2700,
    );
    return () => window.clearInterval(timer);
  }, [events.length, mode, playing, speed]);

  useEffect(() => {
    if (!playing || mode !== "replay") return;
    const timer = window.setInterval(() => {
      setProgress((current) => {
        const next = current + (speed === 2 ? 1.6 : 0.8);
        if (next >= 100) {
          window.clearInterval(timer);
          setPlaying(false);
          return 100;
        }
        return next;
      });
    }, 120);
    return () => window.clearInterval(timer);
  }, [mode, playing, speed]);

  const replayIndex = events.length
    ? Math.min(events.length - 1, Math.floor((progress / 100) * events.length))
    : -1;
  const activeEvent =
    events.length === 0
      ? null
      : mode === "live"
        ? events[liveIndex % events.length]
        : events[Math.max(0, replayIndex)];
  const visibleEvents = mode === "live" ? events : events.slice(0, Math.max(0, replayIndex + 1));
  const panelRegion =
    lockedRegion ??
    (level === "country"
      ? null
      : {
          ...currentMap.sourceCity,
          code: currentMap.code,
          name: currentMap.name,
          exposureIndex: null,
          keywordHits: null,
          estimatedExposure: null,
          recommendationRate: null,
          modelCount: null,
          latestHitAt: null,
          cumulativeIntensity: 0,
        });

  const changeLevel = (nextLevel: ExposureMapLevel) => {
    setLevel(nextLevel);
    setLockedRegion(null);
    setLiveIndex(0);
  };

  return (
    <main className={styles.page}>
      <header className={styles.cockpitHeader}>
        <div className={styles.brandTitle}>
          <span className={styles.brandOrb} aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <div>
            <span>显问 AI</span>
            <h1>GEO 曝光态势中心</h1>
          </div>
        </div>
        <div className={styles.headerControl} title={subjectName}>
          <RadarChartOutlined />
          <span>监测主体：</span>
          <strong>{subjectName}</strong>
        </div>
        <Select
          className={styles.headerSelect}
          aria-label="筛选模型"
          value={selectedModel}
          onChange={setSelectedModel}
          options={[
            { value: "", label: "全部模型" },
            ...data.modelScores.map((item) => ({ value: item.key, label: item.name })),
          ]}
          prefix={<GlobalOutlined />}
        />
        <Select
          className={`${styles.headerSelect} ${styles.reportSelect}`}
          aria-label="选择检测报告"
          value={selectedReportId}
          onChange={onReportChange}
          options={reports.map((report) => ({ value: report.id, label: reportLabel(report) }))}
          prefix={<CalendarOutlined />}
        />
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          href={`/geo/reports/${data.report.id}`}
          className={styles.reportButton}
        >
          生成报告
        </Button>
      </header>

      <section className={styles.cockpitGrid}>
        <aside className={styles.leftRail}>
          <ModelScorePanel
            items={data.modelScores}
            selectedModel={selectedModel}
            onSelect={setSelectedModel}
          />
          <CompetitorIndexPanel items={data.competitors} />
        </aside>

        <GeoExposureMap
          key={currentMap.level}
          data={currentMap}
          visibleEvents={visibleEvents}
          activeEvent={activeEvent}
          lockedRegion={lockedRegion}
          onLockedRegionChange={setLockedRegion}
          onLevelChange={changeLevel}
        />

        <aside className={styles.rightRail}>
          <KeywordExposurePanel summary={data.summary} selectedRegion={panelRegion} />
          <TrendingQuestionsPanel
            items={data.questions}
            selectedModel={selectedModel}
            selectedRegionName={panelRegion?.name ?? null}
            regionalFactsAvailable={!panelRegion || currentMap.hasRegionalFacts}
          />
        </aside>
      </section>

      <ExposureTimeline
        events={events}
        playing={playing}
        mode={mode}
        speed={speed}
        progress={progress}
        currentTime={shortTime(activeEvent?.timestamp)}
        onPlayingChange={setPlaying}
        onModeChange={(nextMode) => {
          setMode(nextMode);
          setPlaying(nextMode === "live");
          setProgress(nextMode === "live" ? 100 : 0);
        }}
        onSpeedChange={setSpeed}
        onProgressChange={(nextProgress) => {
          setMode("replay");
          setPlaying(false);
          setProgress(nextProgress);
        }}
      />

      <div className={styles.accessibleMetrics}>
        <span>综合曝光指数</span>
        <span>提及率</span>
        <span>推荐率</span>
        <span>排名表现</span>
        <span>模型覆盖率</span>
      </div>
    </main>
  );
}
