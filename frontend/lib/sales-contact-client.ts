import { get, getCsrfToken, readEnvelope, write } from "./auth-client";
import { publicEnvironment } from "./env";

export type SalesContactConfiguration = Readonly<{
  scope: "global" | "agent";
  configured: boolean;
  enabled: boolean;
  qr_code_url: string | null;
  updated_at: string | null;
}>;

export type ResolvedSalesContact = Readonly<{
  configured: boolean;
  qr_code_url?: string;
  message?: string;
}>;

export const getSalesContact = () => get<ResolvedSalesContact>("/sales-contact");

export const getAdminSalesContact = () =>
  get<SalesContactConfiguration>("/admin/sales-contact", { cache: "no-store" });

export async function uploadAdminSalesContact(qrCode: File, enabled = true) {
  const csrfToken = await getCsrfToken();
  const body = new FormData();
  body.append("qr_code", qrCode);
  body.append("enabled", enabled ? "true" : "false");
  const response = await fetch(`${publicEnvironment.apiBaseUrl}/admin/sales-contact`, {
    method: "PUT",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "X-CSRFToken": csrfToken,
    },
    body,
  });
  return readEnvelope<SalesContactConfiguration>(response);
}

export const setAdminSalesContactEnabled = (enabled: boolean) =>
  write<SalesContactConfiguration>("PATCH", "/admin/sales-contact", { enabled });
