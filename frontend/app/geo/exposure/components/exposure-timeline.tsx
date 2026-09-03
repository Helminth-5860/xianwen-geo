import { CaretRightFilled, PauseOutlined } from "@ant-design/icons";
import type { CSSProperties } from "react";

import type { ExposureEvent } from "../types";
import styles from "../exposure-command-center.module.css";

export function ExposureTimeline({
  events,
  playing,
  mode,
  speed,
  progress,
  currentTime,
  onPlayingChange,
  onModeChange,
  onSpeedChange,
  onProgressChange,
}: Readonly<{
  events: readonly ExposureEvent[];
  playing: boolean;
  mode: "live" | "replay";
  speed: 1 | 2;
  progress: number;
  currentTime: string;
  onPlayingChange: (playing: boolean) => void;
  onModeChange: (mode: "live" | "replay") => void;
  onSpeedChange: (speed: 1 | 2) => void;
  onProgressChange: (progress: number) => void;
}>) {
  const firstEventAt = events[0] ? Date.parse(events[0].timestamp) : 0;
  const lastEventAt = events.at(-1) ? Date.parse(events.at(-1)!.timestamp) : firstEventAt;
  const eventPosition = (timestamp: string) => {
    if (lastEventAt <= firstEventAt) return 0;
    return ((Date.parse(timestamp) - firstEventAt) / (lastEventAt - firstEventAt)) * 100;
  };

  return (
    <section className={`${styles.panel} ${styles.timelinePanel}`} aria-labelledby="timeline-title">
      <div className={styles.timelineTitle}>
        <h2 id="timeline-title">时间轴</h2>
        <span className={mode === "live" ? styles.livePill : styles.replayPill}>
          {mode === "live" ? "实时" : "回放"}
        </span>
      </div>
      <button
        type="button"
        className={styles.playButton}
        aria-label={playing ? "暂停曝光回放" : "播放曝光回放"}
        onClick={() => onPlayingChange(!playing)}
      >
        {playing ? <PauseOutlined /> : <CaretRightFilled />}
      </button>
      <div className={styles.timelineStatus}>
        <strong>{mode === "live" ? "实时" : "历史回放"}</strong>
        <time>{currentTime}</time>
      </div>
      <div className={styles.timelineTrackArea}>
        <output className={styles.timeBubble} style={{ left: `${progress}%` }}>
          {currentTime}
        </output>
        <div className={styles.eventTicks} aria-hidden="true">
          {events.map((event) => (
            <i key={event.id} style={{ left: `${eventPosition(event.timestamp)}%` }} />
          ))}
        </div>
        <input
          aria-label="曝光回放时间"
          className={styles.timelineRange}
          type="range"
          min="0"
          max="100"
          step="0.1"
          value={progress}
          style={{ "--timeline-progress": `${progress}%` } as CSSProperties}
          onChange={(event) => onProgressChange(Number(event.target.value))}
        />
        <div className={styles.timelineScale} aria-hidden="true">
          {Array.from({ length: 9 }, (_, index) => (
            <span key={index}>{String(index * 3).padStart(2, "0")}:00</span>
          ))}
        </div>
      </div>
      <div className={styles.timelineControls}>
        <button type="button" onClick={() => onSpeedChange(speed === 1 ? 2 : 1)}>
          {speed}x
        </button>
        <button
          type="button"
          className={mode === "replay" ? styles.controlActive : undefined}
          onClick={() => onModeChange("replay")}
        >
          回放
        </button>
        <button
          type="button"
          className={mode === "live" ? styles.controlActive : undefined}
          onClick={() => onModeChange("live")}
        >
          实时
        </button>
      </div>
    </section>
  );
}
