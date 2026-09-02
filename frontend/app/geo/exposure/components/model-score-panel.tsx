import { ArrowDownOutlined, ArrowUpOutlined, RobotOutlined } from "@ant-design/icons";
import Image from "next/image";

import type { ModelScoreItem } from "../types";
import styles from "../exposure-command-center.module.css";

export function ModelScorePanel({
  items,
  selectedModel,
  onSelect,
}: Readonly<{
  items: readonly ModelScoreItem[];
  selectedModel: string;
  onSelect: (modelKey: string) => void;
}>) {
  return (
    <section className={`${styles.panel} ${styles.modelPanel}`} aria-labelledby="model-score-title">
      <header className={styles.panelHeader}>
        <h2 id="model-score-title">模型评分</h2>
        <span className={styles.infoMark} title="当前检测中各模型的综合表现">
          i
        </span>
      </header>
      <div className={styles.scoreList}>
        {items.slice(0, 7).map((item) => {
          const active = !selectedModel || selectedModel === item.key;
          return (
            <button
              key={item.id}
              type="button"
              className={`${styles.scoreRow} ${active ? styles.scoreRowActive : ""}`}
              onClick={() => onSelect(selectedModel === item.key ? "" : item.key)}
              aria-pressed={selectedModel === item.key}
            >
              <span className={styles.modelLogo}>
                {item.logo ? (
                  <Image src={item.logo} alt="" width={28} height={28} sizes="28px" />
                ) : (
                  <RobotOutlined />
                )}
              </span>
              <span className={styles.scoreName}>{item.name}</span>
              <span className={styles.scoreTrack} aria-hidden="true">
                <i style={{ width: `${item.score}%` }} />
              </span>
              <strong>{item.score.toFixed(1)}</strong>
              <span
                className={`${styles.scoreTrend} ${
                  item.trend === null || item.trend >= 0 ? styles.trendUp : styles.trendDown
                }`}
                aria-label={
                  item.trend === null ? "暂无对比" : `较上次${item.trend >= 0 ? "上升" : "下降"}`
                }
              >
                {item.trend === null ? null : item.trend >= 0 ? (
                  <ArrowUpOutlined />
                ) : (
                  <ArrowDownOutlined />
                )}
              </span>
            </button>
          );
        })}
      </div>
      {!items.length && <div className={styles.compactEmpty}>暂无模型评分</div>}
    </section>
  );
}
