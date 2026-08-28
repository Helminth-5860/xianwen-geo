import type { ReactNode } from "react";

import styles from "./xw-components.module.css";
import type { XwDataState, XwStateMessages } from "./types";

export interface XwDataStateViewProps extends XwStateMessages {
  state: XwDataState;
  children: ReactNode;
  compact?: boolean;
  skeletonLines?: number;
  className?: string;
}

const DEFAULT_MESSAGES = {
  loading: "正在准备内容…",
  empty: "暂无可展示内容",
  error: "暂时无法显示，请稍后再试。",
} as const;

function joinClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function XwDataStateView({
  state,
  children,
  compact = false,
  skeletonLines = 2,
  className,
  loading = DEFAULT_MESSAGES.loading,
  empty = DEFAULT_MESSAGES.empty,
  error = DEFAULT_MESSAGES.error,
}: XwDataStateViewProps) {
  if (state === "ready") return children;

  if (state === "loading") {
    const lineCount = Math.max(1, Math.min(4, Math.trunc(skeletonLines)));

    return (
      <div
        className={joinClassNames(styles.dataState, compact && styles.dataStateCompact, className)}
        role="status"
        aria-live="polite"
        aria-label={loading}
      >
        <span className={styles.visuallyHidden}>{loading}</span>
        <span className={styles.skeletonLead} aria-hidden="true" />
        {Array.from({ length: lineCount }, (_, index) => (
          <span
            className={joinClassNames(styles.skeletonLine, index === lineCount - 1 && styles.short)}
            aria-hidden="true"
            key={index}
          />
        ))}
      </div>
    );
  }

  const isError = state === "error";
  const message = isError ? error : empty;

  return (
    <div
      className={joinClassNames(
        styles.dataState,
        styles.dataStateMessage,
        compact && styles.dataStateCompact,
        isError && styles.dataStateError,
        className,
      )}
      role={isError ? "alert" : "status"}
    >
      <span className={styles.stateMark} aria-hidden="true">
        <span />
      </span>
      <span>{message}</span>
    </div>
  );
}
