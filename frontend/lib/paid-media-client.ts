import { get, post, remove, write } from "./auth-client";

export type PaidMediaCatalogItem = Readonly<{
  id: string;
  name: string;
  price_cents: number;
  url: string | null;
  domain: string | null;
  logo_path: string | null;
}>;

export type PaidMediaPagination = Readonly<{
  page: number;
  page_size: number;
  count: number;
  total_pages: number;
}>;

export type PaidMediaCatalogPage = Readonly<{
  items: PaidMediaCatalogItem[];
  pagination: PaidMediaPagination;
}>;

export type PaidMediaInquiryStatus = "pending" | "contacted" | "completed" | "cancelled";

export type PaidMediaInquiry = Readonly<{
  id: string;
  subject_id: string;
  selected_media: ReadonlyArray<
    Readonly<{
      id: string;
      name: string;
      price: string;
      price_cents: number;
      url: string | null;
      domain: string | null;
      logo_path?: string | null;
    }>
  >;
  item_count: number;
  total_price: string;
  status: PaidMediaInquiryStatus;
  version: number;
  created_at: string;
  updated_at: string;
}>;

export type PaidMediaInquiryPage = Readonly<{
  items: PaidMediaInquiry[];
  pagination: PaidMediaPagination;
}>;

export type AdminPaidMediaInquiry = Omit<PaidMediaInquiry, "subject_id"> &
  Readonly<{
    user: Readonly<{
      id: string;
      nickname: string;
      phone: string;
    }>;
    subject: Readonly<{
      id: string;
      name: string;
    }>;
  }>;

export type AdminPaidMediaInquiryPage = Readonly<{
  items: AdminPaidMediaInquiry[];
  pagination: PaidMediaPagination;
}>;

type CreatePaidMediaInquiryResponse = PaidMediaInquiry | Readonly<{ inquiry: PaidMediaInquiry }>;

export function getPaidMediaCatalog(search: string, page = 1, signal?: AbortSignal) {
  const query = new URLSearchParams({
    page: String(page),
    page_size: "20",
  });
  const normalizedSearch = search.trim();
  if (normalizedSearch) query.set("search", normalizedSearch);
  return get<PaidMediaCatalogPage>(`/paid-media-catalog?${query.toString()}`, {
    signal,
    cache: "no-store",
  });
}

export async function createPaidMediaInquiry(
  subjectId: string,
  mediaIds: string[],
  idempotencyKey: string,
) {
  const response = await post<CreatePaidMediaInquiryResponse>(
    `/subjects/${subjectId}/paid-media-inquiries`,
    { media_ids: mediaIds },
    { "Idempotency-Key": idempotencyKey },
  );
  return "inquiry" in response ? response.inquiry : response;
}

export function getPaidMediaInquiries(subjectId: string, page = 1) {
  return get<PaidMediaInquiryPage>(
    `/subjects/${subjectId}/paid-media-inquiries?page=${page}&page_size=20`,
    { cache: "no-store" },
  );
}

export function cancelPaidMediaInquiry(inquiryId: string) {
  return remove<PaidMediaInquiry>(`/paid-media-inquiries/${inquiryId}`);
}

export function getAdminPaidMediaInquiries(params: {
  page?: number;
  status?: string;
  search?: string;
  signal?: AbortSignal;
}) {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: "20",
  });
  if (params.status) query.set("status", params.status);
  if (params.search?.trim()) query.set("search", params.search.trim());
  return get<AdminPaidMediaInquiryPage>(`/admin/paid-media-inquiries?${query.toString()}`, {
    signal: params.signal,
    cache: "no-store",
  });
}

export function getAdminPaidMediaInquiry(inquiryId: string) {
  return get<AdminPaidMediaInquiry>(`/admin/paid-media-inquiries/${inquiryId}`, {
    cache: "no-store",
  });
}

export function updateAdminPaidMediaInquiry(
  inquiryId: string,
  status: "contacted" | "cancelled" | "completed",
  expectedVersion: number,
) {
  return write<AdminPaidMediaInquiry>("PATCH", `/admin/paid-media-inquiries/${inquiryId}`, {
    status,
    expected_version: expectedVersion,
  });
}
