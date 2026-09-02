import type { ExposureEvent, RegionExposure } from "../../types";
import styles from "../../exposure-command-center.module.css";
import type { GeoProjection } from "./geo-projection";

export function TargetPulseLayer({
  regions,
  projection,
  activeEvent,
  onHover,
  onLeave,
  onSelect,
}: Readonly<{
  regions: readonly RegionExposure[];
  projection: GeoProjection;
  activeEvent: ExposureEvent | null;
  onHover: (region: RegionExposure) => void;
  onLeave: () => void;
  onSelect: (region: RegionExposure) => void;
}>) {
  return (
    <g className={styles.targetLayer}>
      {regions.map((region) => {
        const point = projection.project(region.coordinates);
        const active = activeEvent?.targetCityCode === region.code;
        const radius = 4 + Math.max(0, region.cumulativeIntensity) / 30;
        return (
          <g
            key={region.code}
            className={active ? styles.activeTarget : undefined}
            transform={`translate(${point.x} ${point.y})`}
            role="button"
            tabIndex={0}
            aria-label={`查看${region.name}曝光数据`}
            onMouseEnter={() => onHover(region)}
            onMouseLeave={onLeave}
            onFocus={() => onHover(region)}
            onBlur={onLeave}
            onClick={() => onSelect(region)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") onSelect(region);
            }}
          >
            <circle className={styles.targetHeat} r={radius * 3.4} />
            {active && <circle className={styles.targetArrival} r={radius * 2.2} />}
            <circle className={styles.targetDotRing} r={radius + 3} />
            <circle className={styles.targetDot} r={radius} />
          </g>
        );
      })}
    </g>
  );
}
