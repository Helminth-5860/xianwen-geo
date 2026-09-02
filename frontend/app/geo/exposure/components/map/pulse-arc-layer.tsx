import type { ExposureEvent } from "../../types";
import styles from "../../exposure-command-center.module.css";
import type { GeoProjection } from "./geo-projection";

export function PulseArcLayer({
  event,
  projection,
}: Readonly<{ event: ExposureEvent | null; projection: GeoProjection }>) {
  if (!event || event.sourceCityCode === event.targetCityCode) return null;
  const from = projection.project(event.sourceCoordinates);
  const to = projection.project(event.targetCoordinates);
  const distance = Math.hypot(to.x - from.x, to.y - from.y);
  const controlX = (from.x + to.x) / 2;
  const controlY = (from.y + to.y) / 2 - Math.min(118, Math.max(30, distance * 0.3));
  const path = `M ${from.x} ${from.y} Q ${controlX} ${controlY} ${to.x} ${to.y}`;
  return (
    <g className={styles.arcLayer} aria-hidden="true">
      <path className={styles.arcGlow} d={path} />
      <path className={styles.arcLine} d={path} pathLength="1" />
      <circle className={styles.arcParticle} r="5">
        <animateMotion dur="1.35s" repeatCount="1" path={path} />
      </circle>
    </g>
  );
}
