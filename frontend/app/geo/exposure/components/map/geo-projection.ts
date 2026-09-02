import type { GeoJsonCollection, GeoJsonFeature, GeoPosition } from "../../types";

export type ProjectedPoint = Readonly<{ x: number; y: number }>;

export type GeoProjection = Readonly<{
  project: (position: GeoPosition) => ProjectedPoint;
  featurePath: (feature: GeoJsonFeature) => string;
  featureCenter: (feature: GeoJsonFeature) => ProjectedPoint;
}>;

function visitCoordinates(value: unknown, visit: (point: GeoPosition) => void) {
  if (!Array.isArray(value)) return;
  if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
    visit([value[0], value[1]]);
    return;
  }
  value.forEach((item) => visitCoordinates(item, visit));
}

function featureRings(feature: GeoJsonFeature): number[][][] {
  if (feature.geometry.type === "Polygon") {
    return feature.geometry.coordinates as number[][][];
  }
  return (feature.geometry.coordinates as number[][][][]).flatMap((polygon) => polygon);
}

export function createGeoProjection(
  collection: GeoJsonCollection,
  width = 960,
  height = 600,
): GeoProjection {
  let minLongitude = Number.POSITIVE_INFINITY;
  let maxLongitude = Number.NEGATIVE_INFINITY;
  let minLatitude = Number.POSITIVE_INFINITY;
  let maxLatitude = Number.NEGATIVE_INFINITY;

  collection.features.forEach((feature) => {
    visitCoordinates(feature.geometry.coordinates, ([longitude, latitude]) => {
      minLongitude = Math.min(minLongitude, longitude);
      maxLongitude = Math.max(maxLongitude, longitude);
      minLatitude = Math.min(minLatitude, latitude);
      maxLatitude = Math.max(maxLatitude, latitude);
    });
  });

  const paddingX = width * 0.055;
  const paddingY = height * 0.075;
  const longitudeSpan = Math.max(0.001, maxLongitude - minLongitude);
  const latitudeSpan = Math.max(0.001, maxLatitude - minLatitude);
  const centerLatitude = (minLatitude + maxLatitude) / 2;
  const longitudeCorrection = Math.cos((centerLatitude * Math.PI) / 180);
  const scale = Math.min(
    (width - paddingX * 2) / (longitudeSpan * longitudeCorrection),
    (height - paddingY * 2) / latitudeSpan,
  );
  const mapWidth = longitudeSpan * longitudeCorrection * scale;
  const mapHeight = latitudeSpan * scale;
  const offsetX = (width - mapWidth) / 2;
  const offsetY = (height - mapHeight) / 2;

  const project = ([longitude, latitude]: GeoPosition): ProjectedPoint => ({
    x: offsetX + (longitude - minLongitude) * longitudeCorrection * scale,
    y: offsetY + (maxLatitude - latitude) * scale,
  });

  const featurePath = (feature: GeoJsonFeature) =>
    featureRings(feature)
      .map(
        (ring) =>
          ring
            .map((position, index) => {
              const point = project([position[0], position[1]]);
              return `${index === 0 ? "M" : "L"}${point.x.toFixed(2)},${point.y.toFixed(2)}`;
            })
            .join(" ") + " Z",
      )
      .join(" ");

  const featureCenter = (feature: GeoJsonFeature) => {
    const preferred = feature.properties.centroid ?? feature.properties.center;
    if (preferred?.length === 2) return project([preferred[0], preferred[1]]);
    let longitude = 0;
    let latitude = 0;
    let count = 0;
    visitCoordinates(feature.geometry.coordinates, ([nextLongitude, nextLatitude]) => {
      longitude += nextLongitude;
      latitude += nextLatitude;
      count += 1;
    });
    return project([longitude / Math.max(1, count), latitude / Math.max(1, count)]);
  };

  return { project, featurePath, featureCenter };
}
