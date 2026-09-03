import { NextResponse } from "next/server";

const DATA_SOURCE = "https://geo.datav.aliyun.com/areas_v3/bound";

function isBoundaryCollection(value: unknown) {
  if (!value || typeof value !== "object") return false;
  const candidate = value as { type?: unknown; features?: unknown };
  return candidate.type === "FeatureCollection" && Array.isArray(candidate.features);
}

async function fetchBoundary(url: string) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      next: { revalidate: 60 * 60 * 24 * 30 },
    });
    if (!response.ok) return null;
    const value: unknown = await response.json();
    return isBoundaryCollection(value) ? value : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

export async function GET(
  _request: Request,
  context: Readonly<{ params: Promise<{ adcode: string }> }>,
) {
  const { adcode } = await context.params;
  if (!/^\d{6}$/.test(adcode) || adcode === "100000") {
    return NextResponse.json({ message: "区域编号无效" }, { status: 400 });
  }

  const expanded = await fetchBoundary(`${DATA_SOURCE}/${adcode}_full.json`);
  const collection = expanded ?? (await fetchBoundary(`${DATA_SOURCE}/${adcode}.json`));
  if (!collection) {
    return NextResponse.json({ message: "区域地图暂时无法载入" }, { status: 502 });
  }

  return NextResponse.json(collection, {
    headers: { "Cache-Control": "public, max-age=86400, stale-while-revalidate=2592000" },
  });
}
