import { apiDownload, apiFetch } from "./client";

export interface ValidationStudyResponse {
  id: string;
  name: string;
  description?: string | null;
  scheme_id: string;
  scheme_code: string;
  rubric_version_id: string;
  rubric_version: string;
  model_version_id: string;
  model_name: string;
  model_version: string;
  model_artifact_hash: string;
  rubric_definition_hash: string;
  protocol_version: string;
  annotation_rulebook_version: string;
  status: string;
  shadow_mode: boolean;
  minimum_reviews_per_case: number;
  recommendation_policy: Record<string, unknown>;
  created_by: string;
  created_at: string;
  activated_at?: string | null;
  frozen_at?: string | null;
  completed_at?: string | null;
  case_count: number;
  compared_case_count: number;
}

export interface ValidationStudyListResponse {
  studies: ValidationStudyResponse[];
}

export interface ValidationCaseResponse {
  id: string;
  study_id: string;
  proposal_id: string;
  proposal_version_id: string;
  proposal_version_number: number;
  proposal_title: string;
  model_run_id: string;
  partition: string;
  status: string;
  exclusion_reason?: string | null;
  included_by: string;
  included_at: string;
  comparison_ready_at?: string | null;
  assigned_reviewers: number;
  completed_reviews: number;
  minimum_reviews_required: number;
  model_output_blinded: boolean;
}

export interface ValidationCaseListResponse {
  study_id: string;
  cases: ValidationCaseResponse[];
}

export interface ValidationMetricResponse {
  name: string;
  value?: number | null;
  sample_size: number;
  details: Record<string, unknown>;
}

export interface ValidationReadinessResponse {
  scientifically_validated: boolean;
  status: string;
  warnings: string[];
  total_cases: number;
  compared_cases: number;
  completed_reviews: number;
  minimum_reviews_per_case: number;
  partitions: Record<string, number>;
}

export interface ValidationStudySummaryResponse {
  study: ValidationStudyResponse;
  readiness: ValidationReadinessResponse;
  snapshot_group_id?: string | null;
  metrics: ValidationMetricResponse[];
  computed_at?: string | null;
}

export interface ValidationComputeResponse {
  study_id: string;
  snapshot_group_id: string;
  compared_cases: number;
  metrics_written: number;
  warnings: string[];
  message: string;
}

export interface ValidationCriterionFormItem {
  criterion_id: string;
  criterion_key?: string | null;
  category: string;
  criterion: string;
  maximum: number;
  description?: string | null;
  order: number;
}

export interface ValidationReviewFormResponse {
  assignment_id: string;
  proposal_id: string;
  proposal_version_id: string;
  proposal_version_number: number;
  proposal_title: string;
  reviewer_role: string;
  validation_case_id?: string | null;
  study_name?: string | null;
  protocol_version?: string | null;
  annotation_rulebook_version?: string | null;
  shadow_mode: boolean;
  model_output_hidden: boolean;
  rubric_version: string;
  total_marks: number;
  criteria: ValidationCriterionFormItem[];
}

export async function listValidationStudies(): Promise<ValidationStudyListResponse> {
  return apiFetch<ValidationStudyListResponse>("/validation/studies");
}

export async function createValidationStudy(body: {
  name: string;
  description?: string | null;
  scheme_code: string;
  protocol_version: string;
  annotation_rulebook_version: string;
  shadow_mode: boolean;
  minimum_reviews_per_case: number;
  recommendation_policy?: Record<string, unknown>;
}): Promise<ValidationStudyResponse> {
  return apiFetch<ValidationStudyResponse>("/validation/studies", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getValidationStudy(
  studyId: string,
): Promise<ValidationStudySummaryResponse> {
  return apiFetch<ValidationStudySummaryResponse>(`/validation/studies/${studyId}`);
}

export async function updateValidationStudyStatus(
  studyId: string,
  status: string,
): Promise<ValidationStudyResponse> {
  return apiFetch<ValidationStudyResponse>(
    `/validation/studies/${studyId}/status`,
    { method: "PATCH", body: JSON.stringify({ status }) },
  );
}

export async function listValidationCases(
  studyId: string,
): Promise<ValidationCaseListResponse> {
  return apiFetch<ValidationCaseListResponse>(
    `/validation/studies/${studyId}/cases`,
  );
}

export async function addValidationCase(
  studyId: string,
  body: {
    proposal_id: string;
    proposal_version_number?: number | null;
    partition: string;
  },
): Promise<ValidationCaseResponse> {
  return apiFetch<ValidationCaseResponse>(`/validation/studies/${studyId}/cases`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function excludeValidationCase(
  caseId: string,
  reason: string,
): Promise<ValidationCaseResponse> {
  return apiFetch<ValidationCaseResponse>(
    `/validation/cases/${caseId}/exclude`,
    { method: "PATCH", body: JSON.stringify({ reason }) },
  );
}

export async function assignShadowReviewer(
  caseId: string,
  reviewerEmail: string,
  role: "technical" | "financial",
): Promise<{ assignment_id: string; message: string }> {
  return apiFetch<{ assignment_id: string; message: string }>(
    `/validation/cases/${caseId}/assignments`,
    {
      method: "POST",
      body: JSON.stringify({ reviewer_email: reviewerEmail, role }),
    },
  );
}

export async function getValidationReviewForm(
  assignmentId: string,
): Promise<ValidationReviewFormResponse> {
  return apiFetch<ValidationReviewFormResponse>(
    `/validation/assignments/${assignmentId}/form`,
  );
}

export async function computeValidationMetrics(
  studyId: string,
): Promise<ValidationComputeResponse> {
  return apiFetch<ValidationComputeResponse>(
    `/validation/studies/${studyId}/compute`,
    { method: "POST" },
  );
}

export async function downloadValidationDataset(
  studyId: string,
  includeEvidence = false,
): Promise<Blob> {
  return apiDownload(
    `/validation/studies/${studyId}/export?include_evidence=${includeEvidence}`,
  );
}
