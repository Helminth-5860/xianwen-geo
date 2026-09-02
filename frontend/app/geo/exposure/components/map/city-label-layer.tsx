import type { RegionExposure } from "../../types";
import styles from "../../exposure-command-center.module.css";
import type { GeoProjection } from "./geo-projection";

const LABEL_OFFSETS: Readonly<Record<string, readonly [number, number]>> = {
  "440103": [-48, 16],
  "440104": [4, -6],
  "440105": [-42, 34],
  "440106": [34, 17],
  "440111": [-28, -28],
  "440112": [58, -8],
};

export function CityLabelLayer({
  regions,
  projection,
}: Readonly<{ regions: readonly RegionExposure[]; projection: GeoProjection }>) {
  return (
    <g className={styles.cityLabels} aria-hidden="true">
      {regions.map((region) => {
        const point = projection.project(region.coordinates);
        const [offsetX, offsetY] = LABEL_OFFSETS[region.code] ?? [0, -15];
        return (
          <text key={region.code} x={point.x + offsetX} y={point.y + offsetY} textAnchor="middle">
            {region.name}
          </text>
        );
      })}
    </g>
  );
}
