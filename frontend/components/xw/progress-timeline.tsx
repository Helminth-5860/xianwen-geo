import { useId } from "react";

import styles from "./xw-components.module.css";
import { XwDataStateView } from "./data-state";
import type { XwDataState, XwStateMessages } from "./types";

export type ProgressTimelineStatus = "completed" | "current" | "upcoming";

export interface ProgressTimelineStep {
  key: string;
  title: string;
  description?: string;
  meta?: string;
  status: ProgressTimelineStatus;
  href?: string;
  actionLabel?: string;
}

export interface ProgressTimelineProps {
  steps?: readonly ProgressTimelineStep[];
  title?: string;
  orientation?: "horizontal" | "vertical";
  state?: XwDataState;
  messages?: XwStateMessages;
  className?: string;
}

const STATUS_LABELS: Record<ProgressTimelineStatus, string> = {
  completed: "已完成",
  current: "进行中",
  upcoming: "待完成",
};

function joinClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function ProgressTimeline({
  steps = [],
  title = "成长进度",
  orientation = "vertical",
  state = "ready",
  messages,
  className,
}: ProgressTimelineProps) {
  const titleId = useId();
  const resolvedState = state === "ready" && steps.length === 0 ? "empty" : state;

  return (
    <section
      className={joinClassNames(styles.timelineSection, className)}
      aria-labelledby={titleId}
    >
      <h2 className={styles.sectionTitle} id={titleId}>
        {title}
      </h2>
      <XwDataStateView
        state={resolvedState}
        loading={messages?.loading ?? "正在整理进度…"}
        empty={messages?.empty ?? "暂无可展示的进度"}
        error={messages?.error ?? "进度暂时无法显示，请稍后再试。"}
        skeletonLines={3}
      >
        <ol
          className={joinClassNames(
            styles.timeline,
            orientation === "horizontal" && styles.timelineHorizontal,
          )}
        >
          {steps.map((step, index) => (
            <li
              className={styles.timelineStep}
              data-status={step.status}
              aria-current={step.status === "current" ? "step" : undefined}
              key={step.key}
            >
              <div className={styles.timelineRail} aria-hidden="true">
                <span className={styles.timelineMarker}>
                  {step.status === "completed" ? (
                    <svg viewBox="0 0 20 20" focusable="false">
                      <path d="m5.4 10.2 2.8 2.8 6.4-6.4" />
                    </svg>
                  ) : (
                    <span>{index + 1}</span>
                  )}
                </span>
                <span className={styles.timelineConnector} />
              </div>
              <div className={styles.timelineContent}>
                <div className={styles.timelineTitleRow}>
                  <h3>{step.title}</h3>
                  <span className={styles.timelineStatus}>{STATUS_LABELS[step.status]}</span>
                </div>
                {step.description ? <p>{step.description}</p> : null}
                {step.meta ? <span className={styles.timelineMeta}>{step.meta}</span> : null}
                {step.href ? (
                  <a className={styles.timelineAction} href={step.href}>
                    {step.actionLabel ?? "查看详情"}
                    <span aria-hidden="true" />
                  </a>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      </XwDataStateView>
    </section>
  );
}
