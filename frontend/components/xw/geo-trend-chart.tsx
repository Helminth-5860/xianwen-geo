"use client";

import { useId, useMemo, useRef, useState } from "react";

import styles from "./geo-trend-chart.module.css";

export type GeoTrendPoint = Readonly<{
  id: string;
  label: string;
  score: number;
  detail?: string;
}>;

export type GeoTrendChartProps = Readonly<{
  points: readonly GeoTrendPoint[];
  loading?: boolean;
  error?: boolean;
  title?: string;
}>;

type PositionedPoint = GeoTrendPoint &
  Readonly<{
    sourceIndex: number;
    x: number;
    y: number;
  }>;

const chartWidth = 640;
const chartHeight = 260;
const chartPadding = { top: 24, right: 24, bottom: 48, left: 48 } as const;
const plotWidth = chartWidth - chartPadding.left - chartPadding.right;
const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom;
const scoreTicks = [100, 50, 0] as const;

function clampScore(score: number) {
  return Math.min(100, Math.max(0, score));
}

function formatScore(score: number) {
  return score.toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 0,
  });
}

function xFor(index: number, count: number) {
  if (count <= 1) return chartPadding.left + plotWidth / 2;
  return chartPadding.left + (index / (count - 1)) * plotWidth;
}

function yFor(score: number) {
  return chartPadding.top + ((100 - score) / 100) * plotHeight;
}

function visibleLabelIndexes(count: number) {
  if (count <= 5) return Array.from({ length: count }, (_, index) => index);
  return [0, Math.round((count - 1) / 2), count - 1];
}

function labelAnchor(index: number, count: number) {
  if (index === 0) return "start";
  if (index === count - 1) return "end";
  return "middle";
}

export function GeoTrendChart({
  points,
  loading = false,
  error = false,
  title = "综合得分趋势",
}: GeoTrendChartProps) {
  const headingId = useId();
  const descriptionId = useId();
  const gradientId = useId().replaceAll(":", "");
  const [chosenId, setChosenId] = useState<string | null>(null);
  const pointRefs = useRef<Array<SVGGElement | null>>([]);

  const positionedPoints = useMemo<PositionedPoint[]>(() => {
    const usablePoints = points.filter((point) => Number.isFinite(point.score));
    return usablePoints.map((point, index) => {
      const score = clampScore(point.score);
      return {
        ...point,
        score,
        sourceIndex: index,
        x: xFor(index, usablePoints.length),
        y: yFor(score),
      };
    });
  }, [points]);

  const hasTrend = positionedPoints.length >= 2;
  const chosenIndex = chosenId ? positionedPoints.findIndex((point) => point.id === chosenId) : -1;
  const activeIndex = chosenIndex >= 0 ? chosenIndex : positionedPoints.length - 1;
  const activePoint = positionedPoints[activeIndex];
  const linePath = positionedPoints
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
  const areaPath = activePoint
    ? `${linePath} L ${positionedPoints.at(-1)?.x ?? chartPadding.left} ${
        chartPadding.top + plotHeight
      } L ${positionedPoints[0].x} ${chartPadding.top + plotHeight} Z`
    : "";
  const labelIndexes = visibleLabelIndexes(positionedPoints.length);

  const choosePoint = (index: number) => {
    setChosenId(positionedPoints[index]?.id ?? null);
  };

  const moveByKeyboard = (event: React.KeyboardEvent<SVGGElement>, index: number) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choosePoint(index);
      return;
    }

    let nextIndex: number | undefined;
    if (event.key === "ArrowLeft") nextIndex = Math.max(0, index - 1);
    if (event.key === "ArrowRight") {
      nextIndex = Math.min(positionedPoints.length - 1, index + 1);
    }
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = positionedPoints.length - 1;
    if (nextIndex === undefined) return;

    event.preventDefault();
    choosePoint(nextIndex);
    pointRefs.current[nextIndex]?.focus();
  };

  return (
    <section className={styles.root} aria-labelledby={headingId}>
      <div className={styles.header}>
        <div>
          <h3 className={styles.title} id={headingId}>
            {title}
          </h3>
          {hasTrend && <p className={styles.count}>共 {positionedPoints.length} 次检测</p>}
        </div>
        {hasTrend && activePoint && (
          <output className={styles.readout} aria-live="polite">
            <span>{activePoint.detail || activePoint.label}</span>
            <strong>{formatScore(activePoint.score)} 分</strong>
          </output>
        )}
      </div>

      {loading ? (
        <div className={styles.state} role="status">
          <span className={styles.loadingMark} aria-hidden="true" />
          <strong>正在整理得分变化</strong>
          <p>请稍候，趋势很快就会显示。</p>
        </div>
      ) : error ? (
        <div className={`${styles.state} ${styles.errorState}`} role="alert">
          <span className={styles.errorMark} aria-hidden="true">
            ！
          </span>
          <strong>趋势暂时无法显示</strong>
          <p>暂时无法查看得分变化，请稍后再试。</p>
        </div>
      ) : !hasTrend ? (
        <div className={styles.state} role="status">
          <span className={styles.emptyMark} aria-hidden="true" />
          <strong>{positionedPoints.length === 1 ? "已记录首次得分" : "趋势还在积累"}</strong>
          <p>完成至少两次检测后，这里会显示综合得分的变化趋势。</p>
          {positionedPoints[0] && (
            <span className={styles.firstScore}>
              当前记录为 {formatScore(positionedPoints[0].score)} 分
            </span>
          )}
        </div>
      ) : (
        <>
          <div className={styles.chartWrap}>
            <svg
              className={styles.chart}
              viewBox={`0 0 ${chartWidth} ${chartHeight}`}
              preserveAspectRatio="xMidYMid meet"
              role="group"
              aria-label={`${title}图，得分范围为零到一百分；可使用鼠标或键盘逐个查看数据点`}
              aria-describedby={descriptionId}
            >
              <desc id={descriptionId}>
                横轴表示检测时间，纵轴表示综合得分。当前共记录{positionedPoints.length}
                次检测。
              </desc>
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop className={styles.areaStart} offset="0%" />
                  <stop className={styles.areaEnd} offset="100%" />
                </linearGradient>
              </defs>

              {scoreTicks.map((tick) => {
                const y = yFor(tick);
                return (
                  <g key={tick} aria-hidden="true">
                    <line
                      className={styles.gridLine}
                      x1={chartPadding.left}
                      x2={chartWidth - chartPadding.right}
                      y1={y}
                      y2={y}
                    />
                    <text
                      className={styles.axisText}
                      x={chartPadding.left - 12}
                      y={y + 4}
                      textAnchor="end"
                    >
                      {tick}
                    </text>
                  </g>
                );
              })}

              <text
                className={styles.axisTitle}
                x={chartPadding.left}
                y={chartPadding.top - 10}
                aria-hidden="true"
              >
                得分
              </text>
              <text
                className={styles.axisTitle}
                x={chartWidth - chartPadding.right}
                y={chartHeight - 8}
                textAnchor="end"
                aria-hidden="true"
              >
                检测时间
              </text>

              <path className={styles.area} d={areaPath} fill={`url(#${gradientId})`} />
              <path className={styles.line} d={linePath} pathLength={1} />

              {activePoint && (
                <line
                  className={styles.guide}
                  x1={activePoint.x}
                  x2={activePoint.x}
                  y1={activePoint.y}
                  y2={chartPadding.top + plotHeight}
                  aria-hidden="true"
                />
              )}

              {labelIndexes.map((index) => {
                const point = positionedPoints[index];
                return (
                  <text
                    className={styles.axisText}
                    x={point.x}
                    y={chartPadding.top + plotHeight + 24}
                    textAnchor={labelAnchor(index, positionedPoints.length)}
                    aria-hidden="true"
                    key={`${point.id}-标签`}
                  >
                    {point.label}
                  </text>
                );
              })}

              {positionedPoints.map((point, index) => {
                const selected = index === activeIndex;
                const pointName = `第 ${index + 1} 次检测，${point.detail || point.label}，得分 ${formatScore(
                  point.score,
                )} 分`;
                return (
                  <g
                    className={styles.point}
                    key={`${point.id}-${point.sourceIndex}`}
                    ref={(element) => {
                      pointRefs.current[index] = element;
                    }}
                    role="button"
                    tabIndex={selected ? 0 : -1}
                    aria-label={pointName}
                    aria-pressed={selected}
                    onFocus={() => choosePoint(index)}
                    onMouseEnter={() => choosePoint(index)}
                    onPointerDown={() => choosePoint(index)}
                    onKeyDown={(event) => moveByKeyboard(event, index)}
                  >
                    <circle className={styles.pointHit} cx={point.x} cy={point.y} r={18} />
                    <circle
                      className={styles.pointHalo}
                      cx={point.x}
                      cy={point.y}
                      r={selected ? 9 : 6}
                    />
                    <circle className={styles.pointCore} cx={point.x} cy={point.y} r={3.5} />
                  </g>
                );
              })}
            </svg>
          </div>
          <p className={styles.hint}>将鼠标移到数据点上，或使用键盘逐个查看。</p>
        </>
      )}
    </section>
  );
}
