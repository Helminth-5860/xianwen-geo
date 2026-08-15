import { get, post, write } from "./auth-client";

export type KeywordStructureType = "short" | "long_tail" | "general";
export type KeywordRegionLevel = "country" | "province" | "city" | "district" | "custom";

export type KeywordItem = Readonly<{
  id?: string;
  text: string;
  structure_type: KeywordStructureType;
  is_regional: boolean;
  region_level: KeywordRegionLevel | null;
  region_text: string | null;
  sort_order: number;
}>;

export type KeywordSubjectVersion = Readonly<{
  id: string;
  version_no: number;
  official_name: string;
}>;

export type KeywordDraftState = Readonly<{
  version: number;
  subject_version: KeywordSubjectVersion | null;
  draft_subject_version: KeywordSubjectVersion | null;
  current_keyword_version_no: number | null;
  can_write: boolean;
  read_only_reason: string | null;
  items: KeywordItem[];
}>;

export type KeywordVersion = Readonly<{
  id: string;
  version_no: number;
  subject_version: KeywordSubjectVersion;
  item_count: number;
  created_at: string;
  items?: KeywordItem[];
}>;

export const getKeywordDraft = (subjectId: string) =>
  get<KeywordDraftState>(`/subjects/${subjectId}/keywords/draft`);

export const saveKeywordDraft = (
  subjectId: string,
  input: {
    expectedVersion: number;
    expectedSubjectVersionId: string;
    items: KeywordItem[];
  },
) =>
  write<KeywordDraftState>("PATCH", `/subjects/${subjectId}/keywords/draft`, {
    expected_version: input.expectedVersion,
    expected_subject_version_id: input.expectedSubjectVersionId,
    items: input.items.map((item) => ({
      text: item.text,
      structure_type: item.structure_type,
      is_regional: item.is_regional,
      region_level: item.region_level ?? "",
      region_text: item.region_text ?? "",
    })),
  });

export const commitKeywords = (
  subjectId: string,
  expectedVersion: number,
  expectedSubjectVersionId: string,
) =>
  post<{ version: KeywordVersion }>(`/subjects/${subjectId}/keywords/commit`, {
    expected_version: expectedVersion,
    expected_subject_version_id: expectedSubjectVersionId,
  });

export const getKeywordVersions = (subjectId: string) =>
  get<{ versions: KeywordVersion[] }>(`/subjects/${subjectId}/keywords/versions`);

export const getKeywordVersion = (subjectId: string, versionId: string) =>
  get<KeywordVersion>(`/subjects/${subjectId}/keywords/versions/${versionId}`);
