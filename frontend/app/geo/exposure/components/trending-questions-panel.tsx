import type { TrendingQuestionItem } from "../types";
import styles from "../exposure-command-center.module.css";

function relativeTime(value: string) {
  const minutes = Math.max(1, Math.round((Date.now() - new Date(value).getTime()) / 60_000));
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  return `${Math.round(hours / 24)}天前`;
}

export function TrendingQuestionsPanel({
  items,
  selectedModel,
  selectedRegionName,
  regionalFactsAvailable,
}: Readonly<{
  items: readonly TrendingQuestionItem[];
  selectedModel: string;
  selectedRegionName: string | null;
  regionalFactsAvailable: boolean;
}>) {
  const filtered = regionalFactsAvailable
    ? items.filter(
        (item) => !selectedModel || item.model.toLowerCase().includes(selectedModel.toLowerCase()),
      )
    : [];
  return (
    <section
      className={`${styles.panel} ${styles.questionsPanel}`}
      aria-labelledby="trending-questions-title"
    >
      <header className={styles.panelHeader}>
        <h2 id="trending-questions-title">
          {selectedRegionName ? `${selectedRegionName}热门问题` : "动态热门问题"}
        </h2>
        <span className={styles.livePill}>实时</span>
      </header>
      <ol className={styles.questionList}>
        {filtered.slice(0, 8).map((item, index) => (
          <li key={item.id}>
            <span className={styles.questionRank}>{index + 1}</span>
            <span className={styles.questionText} title={item.question}>
              {item.question}
            </span>
            <span className={styles.modelPill}>{item.model}</span>
            <time dateTime={item.timestamp}>{relativeTime(item.timestamp)}</time>
          </li>
        ))}
      </ol>
      {!filtered.length && <div className={styles.compactEmpty}>当前范围暂无热门问题</div>}
    </section>
  );
}
