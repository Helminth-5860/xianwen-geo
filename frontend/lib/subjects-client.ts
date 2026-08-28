import { get, post, write } from "./auth-client";

export type SubjectFieldType =
  | "text"
  | "textarea"
  | "number"
  | "date"
  | "single"
  | "multi"
  | "select"
  | "url"
  | "image"
  | "file";

export type SubjectFieldOption = Readonly<{
  id: string;
  option_key: string;
  label: string;
  enabled: boolean;
  sort_order: number;
  version: number;
}>;

export type SubjectFieldConfig = Readonly<{
  id: string;
  field_key: string;
  field_type: SubjectFieldType;
  scope: "common" | "custom";
  is_builtin?: boolean;
  label: string;
  description: string;
  required: boolean;
  default_value: unknown;
  sort_order: number;
  enabled?: boolean;
  used_for_ai: boolean;
  name_role: "none" | "official_name" | "alias" | "english_name" | "product";
  version?: number;
  options: SubjectFieldOption[];
}>;

export type SubjectType = Readonly<{
  id: string;
  key: string;
  name: string;
  description: string;
  icon_key: string;
  status?: "active" | "inactive";
  sort_order: number;
  is_builtin?: boolean;
  schema_version: number;
  version?: number;
  fields?: SubjectFieldConfig[];
}>;

export const getSubjectTypes = () => get<SubjectType[]>("/subject-types");
export const getSubjectFormSchema = (id: string) =>
  get<SubjectType & { fields: SubjectFieldConfig[] }>(`/subject-types/${id}/form-schema`);

export const getAdminSubjectTypes = (status = "", keyword = "") => {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (keyword) query.set("keyword", keyword);
  const suffix = query.size ? `?${query.toString()}` : "";
  return get<SubjectType[]>(`/admin/subject-types${suffix}`);
};

export const createSubjectType = (input: {
  key: string;
  name: string;
  description: string;
  icon_key: string;
  sort_order: number;
}) => post<SubjectType & { fields: SubjectFieldConfig[] }>("/admin/subject-types", input);

export const getAdminSubjectType = (id: string) =>
  get<SubjectType & { fields: SubjectFieldConfig[] }>(`/admin/subject-types/${id}`);

export const updateSubjectType = (
  id: string,
  expectedVersion: number,
  expectedSchemaVersion: number,
  input: Partial<Pick<SubjectType, "name" | "description" | "icon_key" | "sort_order">>,
) =>
  write<SubjectType & { fields: SubjectFieldConfig[] }>("PATCH", `/admin/subject-types/${id}`, {
    expected_version: expectedVersion,
    expected_schema_version: expectedSchemaVersion,
    ...input,
  });

export const changeSubjectTypeStatus = (
  id: string,
  action: "enable" | "disable",
  expectedVersion: number,
  expectedSchemaVersion: number,
) =>
  post<SubjectType & { fields: SubjectFieldConfig[] }>(`/admin/subject-types/${id}/${action}`, {
    expected_version: expectedVersion,
    expected_schema_version: expectedSchemaVersion,
  });

export const createSubjectField = (
  subjectTypeId: string,
  expectedSchemaVersion: number,
  input: {
    field_key: string;
    field_type: SubjectFieldType;
    label: string;
    description?: string;
    required?: boolean;
    enabled?: boolean;
    used_for_ai?: boolean;
    name_role?: SubjectFieldConfig["name_role"];
    options?: { option_key: string; label: string; enabled?: boolean; sort_order?: number }[];
  },
) =>
  post<SubjectFieldConfig>(`/admin/subject-types/${subjectTypeId}/fields`, {
    expected_schema_version: expectedSchemaVersion,
    ...input,
  });

export const updateSubjectField = (
  field: SubjectFieldConfig,
  expectedSchemaVersion: number,
  input: Partial<
    Pick<
      SubjectFieldConfig,
      | "label"
      | "description"
      | "required"
      | "default_value"
      | "sort_order"
      | "enabled"
      | "used_for_ai"
      | "name_role"
    >
  >,
) =>
  write<SubjectFieldConfig>("PATCH", `/admin/subject-type-fields/${field.id}`, {
    expected_schema_version: expectedSchemaVersion,
    expected_version: field.version,
    ...input,
  });

export const createSubjectFieldOption = (
  field: SubjectFieldConfig,
  expectedSchemaVersion: number,
  input: { option_key: string; label: string; enabled?: boolean; sort_order?: number },
) =>
  post<SubjectFieldOption>(`/admin/subject-type-fields/${field.id}/options`, {
    expected_schema_version: expectedSchemaVersion,
    expected_config_version: field.version,
    ...input,
  });

export const updateSubjectFieldOption = (
  option: SubjectFieldOption,
  expectedSchemaVersion: number,
  input: Partial<Pick<SubjectFieldOption, "label" | "enabled" | "sort_order">>,
) =>
  write<SubjectFieldOption>("PATCH", `/admin/subject-field-options/${option.id}`, {
    expected_schema_version: expectedSchemaVersion,
    expected_version: option.version,
    ...input,
  });

export const reorderSubjectFields = (
  subjectTypeId: string,
  expectedSchemaVersion: number,
  fields: SubjectFieldConfig[],
) =>
  write<SubjectType & { fields: SubjectFieldConfig[] }>(
    "PUT",
    `/admin/subject-types/${subjectTypeId}/field-order`,
    {
      expected_schema_version: expectedSchemaVersion,
      fields: fields.map((field) => ({ id: field.id, expected_version: field.version })),
    },
  );

export type SubjectStatus = "draft" | "active" | "archived";

export type PersistedSubjectFieldOption = Readonly<{
  option_key: string;
  label: string;
  sort_order: number;
}>;

export type PersistedSubjectField = Readonly<{
  field_key: string;
  field_type: SubjectFieldType;
  scope: "common" | "custom";
  label: string;
  description: string;
  required: boolean;
  default_value: unknown;
  sort_order: number;
  used_for_ai: boolean;
  name_role: SubjectFieldConfig["name_role"];
  options: PersistedSubjectFieldOption[];
}>;

export type PersistedFormSchema = Readonly<{
  id: string;
  key: string;
  name: string;
  description: string;
  icon_key: string;
  schema_version: number;
  fields: PersistedSubjectField[];
}>;

export type SubjectSummary = Readonly<{
  id: string;
  subject_type: Readonly<{
    id: string;
    key: string;
    name: string;
    icon_key: string;
  }>;
  status: SubjectStatus;
  version: number;
  is_current: boolean;
  current_version_no: number | null;
  official_name: string | null;
  service_regions: string;
  retest_required: boolean;
  created_at: string;
  updated_at: string;
}>;

export type SubjectSocialChannels = Readonly<{
  douyin: string;
  wechat_channels: string;
  wechat_official_account: string;
  xiaohongshu: string;
  kuaishou: string;
  ecommerce_urls: string;
  other_public_urls: string;
}>;

export type SubjectBusinessProfile = Readonly<{
  legal_entity_type: "" | "company" | "individual_business";
  contact_name: string;
  contact_phone: string;
  business_address: string;
  primary_business: string;
  brand_name: string;
  social_channels: SubjectSocialChannels;
}>;

export const emptySubjectBusinessProfile = (): SubjectBusinessProfile => ({
  legal_entity_type: "",
  contact_name: "",
  contact_phone: "",
  business_address: "",
  primary_business: "",
  brand_name: "",
  social_channels: {
    douyin: "",
    wechat_channels: "",
    wechat_official_account: "",
    xiaohongshu: "",
    kuaishou: "",
    ecommerce_urls: "",
    other_public_urls: "",
  },
});

export type SubjectDetail = SubjectSummary &
  Readonly<{
    schema_version: number;
    draft_values: Record<string, unknown>;
    business_profile: SubjectBusinessProfile;
    form_schema: PersistedFormSchema;
    product_candidates: ReadonlyArray<{
      candidate_key: string;
      display_value: string;
      source_field_key: string;
    }>;
    has_uncommitted_changes: boolean;
    risk: Readonly<{
      status:
        | "not_assessed"
        | "unavailable"
        | "clear"
        | "restricted"
        | "review_required"
        | "pending"
        | "approved"
        | "rejected"
        | "superseded";
      review_id: string | null;
      public_reason: string;
    }>;
  }>;

export type SubjectProductConfirmation = Readonly<{
  candidate_key: string;
  uniqueness_confirmed: boolean;
  include_in_mention: boolean;
}>;

export type SubjectVersionSummary = Readonly<{
  id: string;
  version_no: number;
  official_name: string;
  created_at: string;
}>;

export type SubjectVersionDetail = SubjectVersionSummary &
  Readonly<{
    schema_version: number;
    field_values: Record<string, unknown>;
    form_schema: PersistedFormSchema;
    names: ReadonlyArray<{
      role: "official_name" | "alias" | "english_name";
      display_value: string;
      source_field_key: string;
    }>;
    products: ReadonlyArray<{
      candidate_key: string;
      display_value: string;
      source_field_key: string;
      uniqueness_confirmed: boolean;
      include_in_mention: boolean;
    }>;
  }>;

export type SubjectContext = Readonly<{
  current_subject_id: string | null;
  version: number;
}>;

export type SubjectList = Readonly<{
  subjects: SubjectSummary[];
  context: SubjectContext;
}>;

export const SUBJECT_CONTEXT_UPDATED_EVENT = "xianwen:subject-context-updated";

export function notifySubjectContextUpdated() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SUBJECT_CONTEXT_UPDATED_EVENT));
  }
}

export function reloadWorkspaceAfterSubjectChange() {
  if (typeof window !== "undefined") window.location.reload();
}

export function subjectSwitchTargetPath(pathname: string, nextSubjectId: string) {
  const subjectRoute = pathname.match(/^\/subjects\/[^/]+(\/.*)?$/);
  if (subjectRoute) {
    const suffix = subjectRoute[1] ?? "";
    if (suffix.startsWith("/versions")) return `/subjects/${nextSubjectId}`;
    return `/subjects/${nextSubjectId}${suffix}`;
  }
  if (/^\/geo\/detections\/[^/]+/.test(pathname)) return "/geo/detections";
  if (/^\/geo\/reports\/history\/?$/.test(pathname) || pathname.startsWith("/geo/exposure")) {
    return pathname;
  }
  if (/^\/geo\/reports\/[^/]+/.test(pathname)) {
    return pathname.includes("/strategy") ? "/geo/strategy" : "/geo/reports";
  }
  if (/^\/geo\/strategy\/[^/]+/.test(pathname)) return "/geo/strategy";
  return pathname;
}

export function navigateWorkspaceAfterSubjectChange(pathname: string, nextSubjectId: string) {
  if (typeof window !== "undefined") {
    window.location.assign(subjectSwitchTargetPath(pathname, nextSubjectId));
  }
}

export const getSubjects = (status = "") =>
  get<SubjectList>(`/subjects${status ? `?status=${encodeURIComponent(status)}` : ""}`);

export const createSubject = (
  subjectTypeId: string,
  expectedSchemaVersion: number,
  initialValues: Record<string, unknown> = {},
) =>
  post<SubjectDetail>("/subjects", {
    subject_type_id: subjectTypeId,
    expected_schema_version: expectedSchemaVersion,
    initial_values: initialValues,
  });

export const getSubject = (id: string) => get<SubjectDetail>(`/subjects/${id}`);

export const saveSubject = (
  subject: Pick<SubjectDetail, "id" | "version">,
  values: Record<string, unknown>,
  profileValues: SubjectBusinessProfile,
) =>
  write<{
    subject: SubjectDetail;
    version: SubjectVersionDetail;
    version_created: boolean;
  }>("PUT", `/subjects/${subject.id}`, {
    expected_version: subject.version,
    values,
    profile_values: profileValues,
  });

export const updateSubjectDraft = (
  subject: Pick<SubjectDetail, "id" | "version">,
  values: Record<string, unknown>,
  profileValues?: SubjectBusinessProfile,
) =>
  write<SubjectDetail>("PATCH", `/subjects/${subject.id}/draft`, {
    expected_version: subject.version,
    values,
    ...(profileValues ? { profile_values: profileValues } : {}),
  });

export const archiveSubject = (subject: Pick<SubjectSummary, "id" | "version">) =>
  post<SubjectDetail>(`/subjects/${subject.id}/archive`, {
    expected_version: subject.version,
  });

export const deleteSubject = archiveSubject;

export const activateSubject = (subject: Pick<SubjectSummary, "id" | "version">) =>
  post<SubjectDetail>(`/subjects/${subject.id}/activate`, {
    expected_version: subject.version,
  });

export const setCurrentSubject = (subjectId: string, expectedVersion: number) =>
  write<SubjectContext>("PUT", "/subjects/current", {
    subject_id: subjectId,
    expected_version: expectedVersion,
  });

export const commitSubject = (
  subject: Pick<SubjectDetail, "id" | "version">,
  products: SubjectProductConfirmation[],
) =>
  post<{ subject: SubjectDetail; version: SubjectVersionDetail }>(
    `/subjects/${subject.id}/commit`,
    { expected_version: subject.version, products },
  );

export const getSubjectVersions = (subjectId: string) =>
  get<{ versions: SubjectVersionSummary[] }>(`/subjects/${subjectId}/versions`);

export const getSubjectVersion = (subjectId: string, versionId: string) =>
  get<SubjectVersionDetail>(`/subjects/${subjectId}/versions/${versionId}`);
