import { useId } from "react";

import styles from "./xw-components.module.css";
import { XwDataStateView } from "./data-state";
import { GlassSurface } from "./glass-surface";
import type { XwDataState, XwLinkAction, XwStateMessages, XwTone } from "./types";

export interface InsightCardItem {
  text: string;
  tone?: XwTone;
}

export interface InsightCardProps {
  title?: string;
  headline?: string | null;
  summary?: string | null;
  items?: readonly InsightCardItem[];
  priorityLabel?: string;
  action?: XwLinkAction;
  state?: XwDataState;
  messages?: XwStateMessages;
  className?: string;
}

function joinClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function InsightCard({
  title = "智能洞察",
  headline,
  summary,
  items = [],
  priorityLabel,
  action,
  state = "ready",
  messages,
  className,
}: InsightCardProps) {
  const titleId = useId();
  const hasData = Boolean(headline?.trim() || summary?.trim() || items.length > 0);
  const resolvedState = state === "ready" && !hasData ? "empty" : state;

  return (
    <GlassSurface
      as="article"
      level="ai"
      className={joinClassNames(styles.insightCard, className)}
      aria-labelledby={titleId}
    >
      <div className={styles.insightHeading}>
        <span className={styles.insightIcon} aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M12 2.8c.7 4.6 2.7 6.6 7.3 7.3-4.6.7-6.6 2.7-7.3 7.3-.7-4.6-2.7-6.6-7.3-7.3C9.3 9.4 11.3 7.4 12 2.8Z" />
            <path d="M18.3 15.2c.3 2.1 1.3 3.1 3.4 3.4-2.1.3-3.1 1.3-3.4 3.4-.3-2.1-1.3-3.1-3.4-3.4 2.1-.3 3.1-1.3 3.4-3.4Z" />
          </svg>
        </span>
        <h2 id={titleId}>{title}</h2>
        {priorityLabel ? (
          <span className={styles.statusBadge} data-tone="ai">
            {priorityLabel}
          </span>
        ) : null}
      </div>

      <XwDataStateView
        state={resolvedState}
        loading={messages?.loading ?? "正在整理洞察…"}
        empty={messages?.empty ?? "生成优化洞察后，可在这里查看。"}
        error={messages?.error ?? "洞察暂时无法显示，请稍后再试。"}
        skeletonLines={3}
      >
        <div className={styles.insightBody}>
          {headline ? <p className={styles.insightHeadline}>{headline}</p> : null}
          {summary ? <p className={styles.insightSummary}>{summary}</p> : null}
          {items.length > 0 ? (
            <ul className={styles.insightList}>
              {items.map((item, index) => (
                <li data-tone={item.tone ?? "ai"} key={`${item.text}-${index}`}>
                  <span aria-hidden="true" />
                  <span>{item.text}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </XwDataStateView>
      {action && resolvedState !== "loading" && resolvedState !== "error" ? (
        <a className={styles.insightAction} href={action.href} aria-label={action.accessibleLabel}>
          {action.label}
          <span aria-hidden="true" />
        </a>
      ) : null}
    </GlassSurface>
  );
}
