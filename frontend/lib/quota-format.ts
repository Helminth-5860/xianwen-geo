const UNLIMITED_QUOTA_THRESHOLD = Number.MAX_SAFE_INTEGER;

export function isUnlimitedQuotaAmount(
  value: number | null | undefined,
  explicitUnlimited = false,
) {
  return (
    explicitUnlimited ||
    value === Number.POSITIVE_INFINITY ||
    (typeof value === "number" && value >= UNLIMITED_QUOTA_THRESHOLD)
  );
}

export function formatQuotaAmount(value: number | null | undefined, explicitUnlimited = false) {
  if (isUnlimitedQuotaAmount(value, explicitUnlimited)) return "不限";
  const normalized = typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0;
  return normalized.toLocaleString("zh-CN");
}
