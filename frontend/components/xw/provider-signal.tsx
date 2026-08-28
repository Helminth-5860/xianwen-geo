import { useId, type ReactNode } from "react";

import styles from "./xw-components.module.css";
import { XwDataStateView } from "./data-state";
import { clampNumber, formatXwNumber } from "./format";
import type { XwDataState, XwStateMessages, XwTone } from "./types";

export interface ProviderSignalFact {
  label: string;
  value: string;
  tone?: XwTone;
}

export interface ProviderStatusBadgeProps {
  label: string;
  tone?: XwTone;
  className?: string;
}

export interface ProviderSignalProps {
  name: string;
  value?: number | null;
  maximum?: number;
  valueLabel?: string;
  valueSuffix?: string;
  logo?: ReactNode;
  brandMentioned?: boolean | null;
  activelyRecommended?: boolean | null;
  rank?: number | null;
  facts?: readonly ProviderSignalFact[];
  description?: string;
  tone?: XwTone;
  state?: XwDataState;
  messages?: XwStateMessages;
  className?: string;
}

function joinClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function ProviderStatusBadge({
  label,
  tone = "neutral",
  className,
}: ProviderStatusBadgeProps) {
  return (
    <span className={joinClassNames(styles.statusBadge, className)} data-tone={tone}>
      {label}
    </span>
  );
}

function booleanFact(
  label: string,
  value: boolean | null | undefined,
  positiveLabel: string,
  negativeLabel: string,
) {
  if (typeof value !== "boolean") return null;
  return {
    label,
    value: value ? positiveLabel : negativeLabel,
    tone: value ? ("positive" as const) : ("neutral" as const),
  };
}

export function ProviderSignal({
  name,
  value,
  maximum = 100,
  valueLabel,
  valueSuffix = "分",
  logo,
  brandMentioned,
  activelyRecommended,
  rank,
  facts = [],
  description,
  tone = "primary",
  state = "ready",
  messages,
  className,
}: ProviderSignalProps) {
  const titleId = useId();
  const detailId = useId();
  const validMaximum = Number.isFinite(maximum) && maximum > 0 ? maximum : 100;
  const validValue = typeof value === "number" && Number.isFinite(value) ? value : null;
  const normalizedValue =
    validValue === null ? null : clampNumber((validValue / validMaximum) * 100, 0, 100);
  const derivedFacts = [
    booleanFact("品牌提及", brandMentioned, "已出现", "未出现"),
    booleanFact("主动推荐", activelyRecommended, "已推荐", "未推荐"),
    typeof rank === "number" && Number.isFinite(rank) && rank > 0
      ? { label: "推荐位置", value: `第 ${Math.trunc(rank)} 位`, tone: "primary" as const }
      : null,
    ...facts,
  ].filter((fact): fact is ProviderSignalFact => fact !== null);
  const hasData = validValue !== null || derivedFacts.length > 0 || Boolean(description);
  const hasDetails = derivedFacts.length > 0 || Boolean(description);
  const resolvedState = state === "ready" && !hasData ? "empty" : state;
  const shownValue =
    valueLabel ??
    (validValue === null ? "暂无评分" : `${formatXwNumber(validValue)}${valueSuffix}`);

  return (
    <article
      className={joinClassNames(styles.providerSignal, className)}
      aria-labelledby={resolvedState === "ready" ? titleId : undefined}
      aria-label={resolvedState === "ready" ? undefined : name}
    >
      <XwDataStateView
        state={resolvedState}
        compact
        loading={messages?.loading ?? `正在准备${name}的检测结果…`}
        empty={messages?.empty ?? `${name}暂无足够数据`}
        error={messages?.error ?? `${name}表现暂时无法显示`}
        skeletonLines={1}
      >
        <div className={styles.providerMain}>
          <div className={styles.providerIdentity}>
            <span className={styles.providerLogo} aria-hidden="true">
              {logo ?? name.trim().slice(0, 1)}
            </span>
            <div className={styles.providerNameBlock}>
              <h3 id={titleId}>{name}</h3>
              <span>{shownValue}</span>
            </div>
          </div>

          <div className={styles.signalArea}>
            {normalizedValue === null ? (
              <div className={joinClassNames(styles.signalTrack, styles.signalTrackEmpty)} />
            ) : (
              <div
                className={styles.signalTrack}
                role="progressbar"
                aria-label={`${name}表现`}
                aria-valuemin={0}
                aria-valuemax={validMaximum}
                aria-valuenow={
                  validValue === null ? undefined : clampNumber(validValue, 0, validMaximum)
                }
                aria-valuetext={shownValue}
              >
                <span
                  className={styles.signalFill}
                  data-tone={tone}
                  style={{ width: `${normalizedValue}%` }}
                />
              </div>
            )}
          </div>

          {hasDetails ? (
            <details className={styles.providerDetails}>
              <summary aria-controls={detailId}>
                <span aria-hidden="true">查看详情</span>
                <span className={styles.visuallyHidden}>查看{name}详细表现</span>
              </summary>
              <div className={styles.providerPopover} id={detailId}>
                {derivedFacts.length > 0 ? (
                  <dl>
                    {derivedFacts.map((fact, index) => (
                      <div key={`${fact.label}-${index}`}>
                        <dt>{fact.label}</dt>
                        <dd>
                          <ProviderStatusBadge label={fact.value} tone={fact.tone} />
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
                {description ? <p>{description}</p> : null}
              </div>
            </details>
          ) : null}
        </div>
      </XwDataStateView>
    </article>
  );
}
