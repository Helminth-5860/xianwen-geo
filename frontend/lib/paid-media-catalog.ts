export const PAID_MEDIA_PAGE_SIZE = 20;

export type PaidMediaCatalogRecord = {
  id: string;
  name: string;
  url: string | null;
  source_url_raw: string;
  domain: string | null;
  logo_path: string | null;
  price_cents: number;
  source_price_text: string;
  category?: string;
  portal_type?: string;
  region?: string;
};

export type PaidMediaCatalogItem = {
  id: string;
  name: string;
  url: string | null;
  sourceUrlRaw: string;
  domain: string | null;
  logoPath: string | null;
  priceCents: number;
  sourcePriceText: string;
  category: string;
  portalType: string;
  region: string;
};

export function mapPaidMediaCatalogRecord(record: PaidMediaCatalogRecord): PaidMediaCatalogItem {
  return {
    id: record.id,
    name: record.name,
    url: record.url,
    sourceUrlRaw: record.source_url_raw,
    domain: record.domain,
    logoPath: record.logo_path,
    priceCents: record.price_cents,
    sourcePriceText: record.source_price_text,
    category: record.category ?? "",
    portalType: record.portal_type ?? "",
    region: record.region ?? "",
  };
}

export function formatPaidMediaPrice(priceCents: number): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(priceCents / 100);
}

export function getPaidMediaExternalUrl(url: string | null): string | null {
  if (!url) {
    return null;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

export function getPaidMediaLogoFallback(name: string): string {
  return Array.from(name.trim())[0] ?? "媒";
}
