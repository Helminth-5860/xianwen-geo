"use client";

import { useEffect, useId, useRef, useState } from "react";

import styles from "./xw-components.module.css";
import { XwDataStateView } from "./data-state";
import { clampNumber, formatXwNumber } from "./format";
import type { XwDataState, XwStateMessages, XwTone } from "./types";

export interface GeoScoreStatus {
  label: string;
  tone: XwTone;
}

export interface GeoScoreRingProps {
  value?: number | null;
  change?: number | null;
  previousValue?: number | null;
  label?: string;
  description?: string;
  statusLabel?: string;
  statusTone?: XwTone;
  state?: XwDataState;
  messages?: XwStateMessages;
  animationDuration?: number;
  className?: string;
}

export function getGeoScoreStatus(value: number): GeoScoreStatus {
  if (value >= 80) return { label: "优秀", tone: "positive" };
  if (value >= 60) return { label: "良好", tone: "primary" };
  if (value >= 40) return { label: "待提升", tone: "warning" };
  return { label: "风险", tone: "danger" };
}

function joinClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function describeChange(change: number) {
  const absolute = formatXwNumber(Math.abs(change));
  if (change > 0) return `较上次提升 ${absolute} 分`;
  if (change < 0) return `较上次下降 ${absolute} 分`;
  return "与上次持平";
}

export function GeoScoreRing({
  value,
  change,
  previousValue,
  label = "综合评分",
  description,
  statusLabel,
  statusTone,
  state = "ready",
  messages,
  animationDuration = 720,
  className,
}: GeoScoreRingProps) {
  const titleId = useId();
  const numericValue = typeof value === "number" && Number.isFinite(value) ? value : null;
  const targetValue = numericValue === null ? 0 : clampNumber(numericValue, 0, 100);
  const resolvedState = state === "ready" && numericValue === null ? "empty" : state;
  const [displayedValue, setDisplayedValue] = useState(0);
  const displayedValueRef = useRef(0);

  useEffect(() => {
    if (resolvedState !== "ready") return;

    const reduceMotion =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const startValue = reduceMotion ? targetValue : displayedValueRef.current;
    const distance = targetValue - startValue;
    const duration = clampNumber(animationDuration, 0, 1200);
    let animationFrame = 0;
    let startTime: number | undefined;

    const updateValue = (nextValue: number) => {
      displayedValueRef.current = nextValue;
      setDisplayedValue(nextValue);
    };

    if (
      reduceMotion ||
      duration === 0 ||
      Math.abs(distance) < 0.05 ||
      typeof window.requestAnimationFrame !== "function"
    ) {
      const timeout = window.setTimeout(() => updateValue(targetValue), 0);
      return () => window.clearTimeout(timeout);
    }

    const animate = (time: number) => {
      startTime ??= time;
      const progress = clampNumber((time - startTime) / duration, 0, 1);
      const easedProgress = 1 - Math.pow(1 - progress, 3);
      updateValue(startValue + distance * easedProgress);

      if (progress < 1) animationFrame = window.requestAnimationFrame(animate);
    };

    animationFrame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [animationDuration, resolvedState, targetValue]);

  const calculatedStatus = getGeoScoreStatus(targetValue);
  const status = {
    label: statusLabel ?? calculatedStatus.label,
    tone: statusTone ?? calculatedStatus.tone,
  };
  const explicitChange =
    typeof change === "number" && Number.isFinite(change)
      ? change
      : typeof previousValue === "number" && Number.isFinite(previousValue) && numericValue !== null
        ? numericValue - previousValue
        : null;
  const displayText = formatXwNumber(displayedValue);
  const accessibleText = `${label} ${formatXwNumber(targetValue)} 分，${status.label}`;

  return (
    <div className={joinClassNames(styles.scoreShell, className)}>
      <XwDataStateView
        state={resolvedState}
        loading={messages?.loading ?? "正在整理评分…"}
        empty={messages?.empty ?? "完成检测后即可查看评分"}
        error={messages?.error ?? "评分暂时无法显示，请稍后再试。"}
        skeletonLines={2}
      >
        <section className={styles.scoreContent} aria-labelledby={titleId}>
          <div className={styles.scoreRing} role="img" aria-label={accessibleText}>
            <svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">
              <circle className={styles.scoreTrack} cx="60" cy="60" r="52" pathLength="100" />
              <circle
                className={styles.scoreProgress}
                cx="60"
                cy="60"
                r="52"
                pathLength="100"
                strokeDasharray="100"
                strokeDashoffset={100 - displayedValue}
                data-tone={status.tone}
              />
            </svg>
            <span className={styles.scoreNumber}>{displayText}</span>
            <span className={styles.scoreUnit}>满分 100</span>
          </div>

          <div className={styles.scoreDetails}>
            <p className={styles.componentLabel} id={titleId}>
              {label}
            </p>
            <span className={styles.statusBadge} data-tone={status.tone}>
              {status.label}
            </span>
            {explicitChange !== null ? (
              <p className={styles.scoreChange} data-direction={Math.sign(explicitChange)}>
                {describeChange(explicitChange)}
              </p>
            ) : null}
            {description ? <p className={styles.componentDescription}>{description}</p> : null}
          </div>
        </section>
      </XwDataStateView>
    </div>
  );
}
