import type { MouseEventHandler } from "react";

import styles from "./xw-components.module.css";

export type HeatmapCellStatus = "recommended" | "mentioned" | "missing" | "negative" | "unknown";

export interface HeatmapCellProps {
  status: HeatmapCellStatus;
  label?: string;
  detail?: string;
  onClick?: MouseEventHandler<HTMLButtonElement>;
  className?: string;
}

const STATUS_LABELS: Record<HeatmapCellStatus, string> = {
  recommended: "已推荐",
  mentioned: "已提及",
  missing: "未出现",
  negative: "存在负面表现",
  unknown: "暂无结果",
};

function joinClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function HeatmapCell({ status, label, detail, onClick, className }: HeatmapCellProps) {
  const visibleLabel = label || STATUS_LABELS[status];
  const accessibleLabel = detail ? `${visibleLabel}，${detail}` : visibleLabel;
  const content = (
    <>
      <span className={styles.heatmapMark} aria-hidden="true" />
      <span>{visibleLabel}</span>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className={joinClassNames(styles.heatmapCell, className)}
        data-status={status}
        aria-label={accessibleLabel}
        onClick={onClick}
      >
        {content}
      </button>
    );
  }

  return (
    <span
      className={joinClassNames(styles.heatmapCell, className)}
      data-status={status}
      aria-label={accessibleLabel}
    >
      {content}
    </span>
  );
}
