import type { CSSProperties } from "react";

import type { ExposureSummary, RegionExposure } from "../types";
import styles from "../exposure-command-center.module.css";

function displayNumber(value: number | null) {
  return value === null ? "—" : Math.round(value).toLocaleString("zh-CN");
}

function trendPath(values: readonly number[]) {
  const safeValues = values.length > 1 ? values : [0, values[0] ?? 0];
  const min = Math.min(...safeValues);
  const max = Math.max(...safeValues);
  const span = Math.max(1, max - min);
  return safeValues
    .map((value, index) => {
      const x = (index / (safeValues.length - 1)) * 240;
      const y = 78 - ((value - min) / span) * 60;
      return `${x},${y}`;
    })
    .join(" ");
}

export function KeywordExposurePanel({
  summary,
  selectedRegion,
}: Readonly<{
  summary: ExposureSummary;
  selectedRegion: RegionExposure | null;
}>) {
  const hasRegionFacts = selectedRegion ? selectedRegion.keywordHits !== null : true;
  const keywordHits = selectedRegion ? selectedRegion.keywordHits : summary.keywordHits;
  const estimatedExposure = selectedRegion
    ? selectedRegion.estimatedExposure
    : summary.estimatedExposure;
  const hitRate = hasRegionFacts ? summary.hitRate : null;
  const points = trendPath(summary.trend);
  return (
    <section
      className={`${styles.panel} ${styles.keywordPanel}`}
      aria-labelledby="keyword-exposure-title"
    >
      <div className={styles.metricTabs} role="tablist" aria-label="曝光指标">
        <button type="button" className={styles.metricTabActive} role="tab" aria-selected="true">
          关键词命中
        </button>
        <button type="button" role="tab" aria-selected="false">
          预计曝光
        </button>
      </div>
      <div className={styles.summaryMetrics}>
        <div>
          <span>{selectedRegion ? `${selectedRegion.name}关键词` : "关键词总数"}</span>
          <strong>{displayNumber(keywordHits)}</strong>
        </div>
        <div
          className={styles.hitDonut}
          style={{ "--hit-rate": `${(hitRate ?? 0) * 3.6}deg` } as CSSProperties}
        >
          <span>命中率</span>
          <strong>{hitRate === null ? "—" : `${hitRate.toFixed(1)}%`}</strong>
        </div>
        <div>
          <span>预计曝光</span>
          <strong>{displayNumber(estimatedExposure)}</strong>
          {!selectedRegion && summary.changeRate !== null && (
            <small className={summary.changeRate >= 0 ? styles.positive : styles.negative}>
              较上次 {summary.changeRate >= 0 ? "▲" : "▼"} {Math.abs(summary.changeRate).toFixed(1)}
              %
            </small>
          )}
        </div>
      </div>
      <div className={styles.miniTrend}>
        <h3 id="keyword-exposure-title">近 7 次趋势</h3>
        {hasRegionFacts ? (
          <svg viewBox="0 0 240 92" role="img" aria-label="近七次曝光趋势">
            <defs>
              <linearGradient id="exposure-trend-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#2d6fff" stopOpacity="0.24" />
                <stop offset="1" stopColor="#2d6fff" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={`M ${points} L 240,88 L 0,88 Z`} fill="url(#exposure-trend-fill)" />
            <polyline points={points} fill="none" stroke="#2869f5" strokeWidth="2.4" />
            {points.split(" ").map((point, index) => {
              const [cx, cy] = point.split(",");
              return (
                <circle
                  key={`${cx}-${index}`}
                  cx={cx}
                  cy={cy}
                  r="3"
                  fill="#fff"
                  stroke="#2869f5"
                  strokeWidth="2"
                />
              );
            })}
          </svg>
        ) : (
          <div className={styles.compactEmpty}>该区域趋势数据尚未接入</div>
        )}
      </div>
    </section>
  );
}
