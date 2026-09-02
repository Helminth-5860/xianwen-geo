import type { GeoJsonCollection } from "../../types";
import styles from "../../exposure-command-center.module.css";
import type { GeoProjection } from "./geo-projection";

export function GeoBoundaryLayer({
  collection,
  projection,
  depth,
  lockedCode,
  onHover,
  onLeave,
  onSelect,
}: Readonly<{
  collection: GeoJsonCollection;
  projection: GeoProjection;
  depth: number;
  lockedCode: string;
  onHover: (code: string, name: string) => void;
  onLeave: () => void;
  onSelect: (code: string, name: string) => void;
}>) {
  return (
    <g className={styles.boundaryLayer}>
      <g className={styles.mapDepth} transform={`translate(0 ${depth})`} aria-hidden="true">
        {collection.features.map((feature, index) => (
          <path
            key={`depth-${feature.properties.adcode ?? index}`}
            d={projection.featurePath(feature)}
          />
        ))}
      </g>
      <g className={styles.mapSurfacePaths}>
        {collection.features.map((feature, index) => {
          const code = String(feature.properties.adcode ?? index);
          const name = feature.properties.name ?? "未知区域";
          return (
            <path
              key={code}
              d={projection.featurePath(feature)}
              className={lockedCode === code ? styles.lockedRegion : undefined}
              tabIndex={0}
              role="button"
              aria-label={`${name}区域`}
              onMouseEnter={() => onHover(code, name)}
              onMouseLeave={onLeave}
              onFocus={() => onHover(code, name)}
              onBlur={onLeave}
              onClick={() => onSelect(code, name)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onSelect(code, name);
              }}
            />
          );
        })}
      </g>
    </g>
  );
}
