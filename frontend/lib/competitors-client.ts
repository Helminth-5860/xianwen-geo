import { get, post, remove, write } from "./auth-client";

export type Competitor = Readonly<{
  id: string;
  name: string;
  website: string;
  domain: string;
  source: "manual" | "smart";
  position: number;
  version: number;
  created_at: string;
  updated_at: string;
}>;

export type CompetitorList = Readonly<{
  subject: Readonly<{
    id: string;
    name: string;
  }>;
  items: Competitor[];
  count: number;
  max_count: number;
}>;

export type CompetitorMetricValue = number | null;

export type CompetitorComparisonEntity = Readonly<{
  id: string;
  kind: "subject" | "competitor";
  name: string;
  website: string;
  metrics: Readonly<{
    mention_count: CompetitorMetricValue;
    mention_rate: CompetitorMetricValue;
    question_coverage_count: CompetitorMetricValue;
    question_coverage_rate: CompetitorMetricValue;
    shared_question_count: CompetitorMetricValue;
    gap_question_count: CompetitorMetricValue;
    recommendation_rate: CompetitorMetricValue;
    citation_count: CompetitorMetricValue;
  }>;
}>;

export type CompetitorOpportunity = Readonly<{
  question_id: string;
  question: string;
  competitor_ids: string[];
  competitor_names: string[];
}>;

export type CompetitorComparison = Readonly<{
  subject_id: string;
  subject_name: string;
  status: "no_competitors" | "no_detection_data" | "ready";
  competitor_count: number;
  report_id: string | null;
  detection_id: string | null;
  generated_at: string | null;
  valid_answer_count: number;
  question_count: number;
  entities: CompetitorComparisonEntity[];
  opportunities: CompetitorOpportunity[];
  detail_url: string | null;
}>;

export const getSubjectCompetitors = (subjectId: string, signal?: AbortSignal) =>
  get<CompetitorList>(`/subjects/${subjectId}/competitors`, { signal });

export const createSubjectCompetitor = (
  subjectId: string,
  input: Readonly<{ name: string; website: string }>,
) => post<{ competitor: Competitor }>(`/subjects/${subjectId}/competitors`, input);

export const updateSubjectCompetitor = (
  subjectId: string,
  competitor: Pick<Competitor, "id" | "version">,
  input: Readonly<{ name: string; website: string }>,
) =>
  write<{ competitor: Competitor }>(
    "PATCH",
    `/subjects/${subjectId}/competitors/${competitor.id}`,
    {
      ...input,
      expected_version: competitor.version,
    },
  );

export const removeSubjectCompetitor = (subjectId: string, competitorId: string) =>
  remove<void>(`/subjects/${subjectId}/competitors/${competitorId}`);

export const getCompetitorComparison = (subjectId: string, signal?: AbortSignal) =>
  get<CompetitorComparison>(`/subjects/${subjectId}/competitors/comparison`, { signal });
