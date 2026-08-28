import { get, post, write } from "./auth-client";

export type QuestionCatalogStatus = "active" | "inactive";

type QuestionCatalogBase = Readonly<{
  id: string;
  key: string;
  name: string;
  description: string;
  status: QuestionCatalogStatus;
  sort_order: number;
  is_builtin: boolean;
  version: number;
  applicable_subject_type_ids: string[];
  can_delete: false;
  created_at: string;
  updated_at: string;
}>;

export type QuestionCategory = QuestionCatalogBase &
  Readonly<{
    generation_guidance: string;
  }>;

export type QuestionTag = QuestionCatalogBase;

export type PublicQuestionCatalog = Readonly<{
  categories: Array<
    Pick<
      QuestionCategory,
      | "id"
      | "key"
      | "name"
      | "description"
      | "generation_guidance"
      | "sort_order"
      | "applicable_subject_type_ids"
    >
  >;
  tags: Array<
    Pick<
      QuestionTag,
      "id" | "key" | "name" | "description" | "sort_order" | "applicable_subject_type_ids"
    >
  >;
}>;

export type QuestionCatalogInput = {
  key: string;
  name: string;
  description: string;
  sort_order: number;
  applicable_subject_type_ids: string[];
};

const catalogQuery = (status = "", keyword = "") => {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (keyword) query.set("keyword", keyword);
  return query.size ? `?${query.toString()}` : "";
};

export const getQuestionCatalog = (subjectTypeId = "") =>
  get<PublicQuestionCatalog>(
    `/question-categories${subjectTypeId ? `?subject_type_id=${encodeURIComponent(subjectTypeId)}` : ""}`,
  );

export const getAdminQuestionCategories = (status = "", keyword = "") =>
  get<QuestionCategory[]>(`/admin/question-categories${catalogQuery(status, keyword)}`);

export const getAdminQuestionTags = (status = "", keyword = "") =>
  get<QuestionTag[]>(`/admin/question-tags${catalogQuery(status, keyword)}`);

export const createQuestionCategory = (
  input: QuestionCatalogInput & { generation_guidance: string },
) => post<QuestionCategory>("/admin/question-categories", { ...input });

export const createQuestionTag = (input: QuestionCatalogInput) =>
  post<QuestionTag>("/admin/question-tags", { ...input });

export const updateQuestionCategory = (
  category: QuestionCategory,
  input: Omit<QuestionCatalogInput, "key"> & { generation_guidance: string },
) =>
  write<QuestionCategory>("PATCH", `/admin/question-categories/${category.id}`, {
    expected_version: category.version,
    ...input,
  });

export const updateQuestionTag = (tag: QuestionTag, input: Omit<QuestionCatalogInput, "key">) =>
  write<QuestionTag>("PATCH", `/admin/question-tags/${tag.id}`, {
    expected_version: tag.version,
    ...input,
  });

export const changeQuestionCategoryStatus = (
  category: QuestionCategory,
  action: "enable" | "disable",
) =>
  post<QuestionCategory>(`/admin/question-categories/${category.id}/${action}`, {
    expected_version: category.version,
  });

export const changeQuestionTagStatus = (tag: QuestionTag, action: "enable" | "disable") =>
  post<QuestionTag>(`/admin/question-tags/${tag.id}/${action}`, {
    expected_version: tag.version,
  });
