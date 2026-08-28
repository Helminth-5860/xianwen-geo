import { get, post, write } from "./auth-client";

export type AdminImageSize = Readonly<{
  id: string;
  key: string;
  name: string;
  aspect_ratio: string;
  width: number;
  height: number;
  provider_params: Record<string, unknown>;
  applicable_channels: string[];
  applicable_roles: string[];
  status: "active" | "disabled";
  sort_order: number;
  version: number;
}>;

export type AdminImageStyle = Readonly<{
  id: string;
  key: string;
  name: string;
  description: string;
  prompt_template: string;
  applicable_roles: string[];
  status: "active" | "disabled";
  sort_order: number;
  version: number;
}>;

export type ImageCapabilityRuntime = Readonly<{
  id: string;
  model_id: string;
  model_key: string;
  provider_key: string;
  capability: string;
  provider_model_id: string;
  api_version: string;
  enabled: boolean;
  paused: boolean;
  pause_reason: string;
  timeout_seconds: number;
  max_retries: number;
  retry_base_seconds: number;
  version: number;
}>;

export type ImageCredentialBinding = Readonly<{
  id: string;
  provider_key: string;
  capability: string;
  environment: "staging" | "production";
  enabled: boolean;
  version: number;
}>;

export const getAdminImageSizes = () => get<AdminImageSize[]>("/admin/image-sizes");
export const getAdminImageStyles = () => get<AdminImageStyle[]>("/admin/image-styles");
export const getImageCapabilityRuntimes = () =>
  get<ImageCapabilityRuntime[]>("/admin/ai-capability-runtimes");
export const getImageCredentialBindings = () =>
  get<ImageCredentialBinding[]>("/admin/api-credential-bindings/doubao");

export const createAdminImageSize = (input: Omit<AdminImageSize, "id" | "version">) =>
  post<AdminImageSize>("/admin/image-sizes", input);
export const updateAdminImageSize = (row: AdminImageSize, input: Partial<AdminImageSize>) =>
  write<AdminImageSize>("PATCH", `/admin/image-sizes/${row.id}`, {
    expected_version: row.version,
    ...input,
  });
export const createAdminImageStyle = (input: Omit<AdminImageStyle, "id" | "version">) =>
  post<AdminImageStyle>("/admin/image-styles", input);
export const updateAdminImageStyle = (row: AdminImageStyle, input: Partial<AdminImageStyle>) =>
  write<AdminImageStyle>("PATCH", `/admin/image-styles/${row.id}`, {
    expected_version: row.version,
    ...input,
  });
export const updateImageCapabilityRuntime = (
  row: ImageCapabilityRuntime,
  input: Partial<ImageCapabilityRuntime>,
) =>
  write<ImageCapabilityRuntime>("PATCH", `/admin/ai-capability-runtimes/${row.id}`, {
    expected_version: row.version,
    ...input,
  });
export const setImageCredentialBinding = (
  environment: ImageCredentialBinding["environment"],
  enabled: boolean,
  current?: ImageCredentialBinding,
) =>
  write<ImageCredentialBinding>("PUT", "/admin/api-credential-bindings/doubao", {
    capability: "image_generation",
    environment,
    enabled,
    ...(current ? { expected_version: current.version } : {}),
  });
