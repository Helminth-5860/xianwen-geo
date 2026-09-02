import type { CompetitorIndexItem } from "../types";
import styles from "../exposure-command-center.module.css";

export function CompetitorIndexPanel({
  items,
}: Readonly<{ items: readonly CompetitorIndexItem[] }>) {
  return (
    <section
      className={`${styles.panel} ${styles.competitorPanel}`}
      aria-labelledby="competitor-index-title"
    >
      <header className={styles.panelHeader}>
        <h2 id="competitor-index-title">竞品指数</h2>
        <span className={styles.infoMark} title="当前主体与已设置竞品的相对曝光表现">
          i
        </span>
      </header>
      <ol className={styles.competitorList}>
        {items.slice(0, 6).map((item, index) => (
          <li key={item.id} className={item.current ? styles.currentCompetitor : undefined}>
            <span className={styles.rank}>{index + 1}</span>
            <div className={styles.competitorBody}>
              <div className={styles.competitorMeta}>
                <span title={item.name}>
                  {item.name}
                  {item.current && <small>本主体</small>}
                </span>
                <strong>{item.score.toFixed(index === 0 ? 0 : 1)}</strong>
              </div>
              <span className={styles.competitorTrack} aria-hidden="true">
                <i style={{ width: `${item.score}%` }} />
              </span>
            </div>
          </li>
        ))}
      </ol>
      {!items.length && <div className={styles.compactEmpty}>尚未设置竞品</div>}
    </section>
  );
}
