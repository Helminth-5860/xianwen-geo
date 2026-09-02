import { get } from "./auth-client";

export type BusinessDataResource =
  "subjects" | "questions" | "detections" | "reports" | "articles" | "images";

export type BusinessDataItem = Readonly<{
  id: string;
  resource_type: BusinessDataResource;
  title: string;
  status: string;
  status_label: string;
  user_id: string;
  user_name: string;
  user_phone_masked: string;
  tenant_id: string | null;
  tenant_name: string | null;
  subject_id: string | null;
  subject_name: string | null;
  created_at: string;
  updated_at: string;
  metadata: Readonly<Record<string, string | number | boolean | null>>;
}>;

export type BusinessDataResult = Readonly<{
  resource: BusinessDataResource;
  query: string;
  items: BusinessDataItem[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}>;

export async function getAdminBusinessData(
  params: Readonly<{
    resource: BusinessDataResource;
    query?: string;
    page?: number;
    signal?: AbortSignal;
  }>,
): Promise<BusinessDataResult> {
  const search = new URLSearchParams({
    resource: params.resource,
    page: String(params.page ?? 1),
  });
  if (params.query?.trim()) search.set("q", params.query.trim());
  return get<BusinessDataResult>(`/admin/business-data?${search.toString()}`, {
    signal: params.signal,
    cache: "no-store",
  });
}
