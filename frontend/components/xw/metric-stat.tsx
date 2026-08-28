import { useId } from "react";

import styles from "./xw-components.module.css";
import { XwDataStateView } from "./data-state";
import { formatXwNumber } from "./format";
import type { XwDataState, XwStateMessages, XwTone } from "./types";

export interface MetricStatStatus {
  label: string;
  tone?: XwTone;
}

export interface MetricStatChange {
  value: number;
  label?: string;
  unit?: string;
  tone?: XwTone;
}

export interface MetricStatProps {
  label: string;
  value?: number | string | null;
  valueLabel?: string;
  prefix?: string;
  suffix?: string;
  precision?: number;
  status?: MetricStatStatus;
  change?: MetricStatChange | null;
  description?: string;
  state?: XwDataState;
  messages?: XwStateMessages;
  className?: string;
}

function joinClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function hasMetricValue(value: MetricStatProps["value"], valueLabel: string | undefined) {
  if (valueLabel?.trim()) return true;
  if (typeof value === "number") return Number.isFinite(value);
  return typeof value === "string" && value.trim().length > 0;
}

function describeMetricChange(change: MetricStatChange) {
  const amount = `${formatXwNumber(Math.abs(change.value))}${change.unit ?? ""}`;
  const lead = change.label?.trim() || "较上次";
  if (change.value > 0) return `${lead}提升 ${amount}`;
  if (change.value < 0) return `${lead}下降 ${amount}`;
  return `${lead}持平`;
}

export function MetricStat({
  label,
  value,
  valueLabel,
  prefix,
  suffix,
  precision = 1,
  status,
  change,
  description,
  state = "ready",
  messages,
  className,
}: MetricStatProps) {
  const titleId = useId();
  const available = hasMetricValue(value, valueLabel);
  const resolvedState = state === "ready" && !available ? "empty" : state;
  const formattedValue =
    valueLabel ??
    (typeof value === "number"
      ? formatXwNumber(value, Math.max(0, Math.min(3, Math.trunc(precision))))
      : value);

  return (
    <article
      className={joinClassNames(styles.metricStat, className)}
      aria-labelledby={resolvedState === "ready" ? titleId : undefined}
      aria-label={resolvedState === "ready" ? undefined : label}
    >
      <XwDataStateView
        state={resolvedState}
        compact
        loading={messages?.loading ?? `正在准备${label}…`}
        empty={messages?.empty ?? `${label}暂无数据`}
        error={messages?.error ?? `${label}暂时无法显示`}
        skeletonLines={2}
      >
        <div className={styles.metricHeader}>
          <h3 className={styles.componentLabel} id={titleId}>
            {label}
          </h3>
          {status ? (
            <span className={styles.statusBadge} data-tone={status.tone ?? "neutral"}>
              {status.label}
            </span>
          ) : null}
        </div>
        <p className={styles.metricValue}>
          {prefix ? <span className={styles.metricAffix}>{prefix}</span> : null}
          <span>{formattedValue}</span>
          {suffix ? <span className={styles.metricAffix}>{suffix}</span> : null}
        </p>
        {change && Number.isFinite(change.value) ? (
          <p
            className={styles.metricChange}
            data-tone={change.tone ?? (change.value >= 0 ? "positive" : "danger")}
          >
            {describeMetricChange(change)}
          </p>
        ) : null}
        {description ? <p className={styles.componentDescription}>{description}</p> : null}
      </XwDataStateView>
    </article>
  );
}
