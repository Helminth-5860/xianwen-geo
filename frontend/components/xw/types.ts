export type XwDataState = "ready" | "loading" | "empty" | "error";

export type XwTone = "primary" | "positive" | "warning" | "danger" | "ai" | "neutral";

export type XwSurfaceLevel = "soft" | "strong" | "ai";

export interface XwLinkAction {
  label: string;
  href: string;
  accessibleLabel?: string;
}

export interface XwStateMessages {
  loading?: string;
  empty?: string;
  error?: string;
}
