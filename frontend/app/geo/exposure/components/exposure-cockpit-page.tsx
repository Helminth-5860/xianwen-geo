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
    let frame = 0;
    let previous = performance.now();
    let elapsed = 0;
    const interval = speed === 2 ? 1_450 : 2_900;
    const advance = (now: number) => {
      elapsed += now - previous;
      previous = now;
      if (elapsed >= interval) {
        elapsed %= interval;
        setLiveIndex((current) => (current + 1) % events.length);
      }
      frame = requestAnimationFrame(advance);
    };
    frame = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(frame);
  }, [events.length, mode, playing, speed]);

  useEffect(() => {
    if (!playing || mode !== "replay") return;
    let frame = 0;
    let previous = performance.now();
    const advance = (now: number) => {
      const elapsed = now - previous;
      if (elapsed >= 70) {
        previous = now;
        setProgress((current) => {
          const next = current + (elapsed / 1_000) * (speed === 2 ? 15 : 7.5);
          if (next >= 100) {
            setPlaying(false);
            return 100;
          }
          return next;
        });
      }
      frame = requestAnimationFrame(advance);
    };
    frame = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(frame);
  }, [mode, playing, speed]);

  const firstEventAt = events[0] ? Date.parse(events[0].timestamp) : 0;
  const lastEventAt = events.at(-1) ? Date.parse(events.at(-1)!.timestamp) : firstEventAt;
  const replayCutoff = firstEventAt + (lastEventAt - firstEventAt) * (progress / 100);
  const liveEventIndex = events.length ? liveIndex % events.length : -1;
  const replayVisibleEvents = events.filter((event) => Date.parse(event.timestamp) <= replayCutoff);
  const activeEvent =
    events.length === 0
      ? null
      : mode === "live"
        ? events[liveEventIndex]
        : (replayVisibleEvents.at(-1) ?? null);
  const visibleEvents = mode === "live" ? events.slice(0, liveEventIndex + 1) : replayVisibleEvents;
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
          data={currentMap}
          visibleEvents={visibleEvents}
          activeEvent={activeEvent}
          eventPlaybackKey={`${mode}-${level}-${mode === "live" ? liveIndex : Math.round(progress)}`}
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
