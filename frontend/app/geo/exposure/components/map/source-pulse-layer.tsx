import type { RegionExposure } from "../../types";
import styles from "../../exposure-command-center.module.css";
import type { GeoProjection } from "./geo-projection";

export function SourcePulseLayer({
  source,
  projection,
}: Readonly<{ source: RegionExposure; projection: GeoProjection }>) {
  const point = projection.project(source.coordinates);
  return (
    <g className={styles.sourcePulse} transform={`translate(${point.x} ${point.y})`}>
      <circle className={styles.sourceHaloLarge} r="42" />
      <circle className={styles.sourceHalo} r="25" />
      <circle className={styles.sourceRing} r="14" />
      <circle className={styles.sourceCore} r="6" />
      <text y="31" textAnchor="middle">
        {source.name}
      </text>
    </g>
  );
}
