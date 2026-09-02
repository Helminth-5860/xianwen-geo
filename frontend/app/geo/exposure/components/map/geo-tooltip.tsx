import type { RegionExposure } from "../../types";
import styles from "../../exposure-command-center.module.css";

function metric(value: number | null, suffix = "") {
  return value === null ? "暂无区域数据" : `${value.toLocaleString("zh-CN")}${suffix}`;
}

export function GeoTooltip({
  region,
  position,
}: Readonly<{
  region: RegionExposure;
  position: Readonly<{ x: number; y: number }>;
}>) {
  return (
    <div className={styles.geoTooltip} style={{ left: position.x, top: position.y }} role="status">
      <strong>{region.name}</strong>
      <dl>
        <div>
          <dt>曝光指数</dt>
          <dd>{metric(region.exposureIndex)}</dd>
        </div>
        <div>
          <dt>关键词命中</dt>
          <dd>{metric(region.keywordHits)}</dd>
        </div>
        <div>
          <dt>预计曝光</dt>
          <dd>{metric(region.estimatedExposure)}</dd>
        </div>
        <div>
          <dt>推荐率</dt>
          <dd>{metric(region.recommendationRate, "%")}</dd>
        </div>
        <div>
          <dt>涉及模型</dt>
          <dd>{metric(region.modelCount, " 个")}</dd>
        </div>
        <div>
          <dt>最新命中</dt>
          <dd>
            {region.latestHitAt ? new Date(region.latestHitAt).toLocaleString("zh-CN") : "暂无"}
          </dd>
        </div>
      </dl>
    </div>
  );
}
