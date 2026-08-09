import { apiFetch } from "./client";

export interface ReviewerAssignmentResponse {
  id: string;
  proposal_id: string;
  proposal_version_id: string;
  proposal_version_number: number;
  reviewer_id: string;
  validation_case_id?: string | null;
  is_shadow_validation?: boolean;
  validation_study_name?: string | null;
  role: string;
  status: string;
  is_blind: boolean;
  conflict_declared?: boolean | null;
  conflict_notes?: string | null;
  assigned_at: string;
  completed_at?: string | null;
}

export interface AssignmentListResponse {
  assignments: ReviewerAssignmentResponse[];
}

export interface ReviewAssignResponse {
  assignment: ReviewerAssignmentResponse;
  status: string;
  message: string;
}

export interface CriterionScoreResponse {
  criterion_id: string;
  criterion_key?: string | null;
  criterion: string;
  maximum: number;
  score: number;
  confidence?: number | null;
  evidence_coverage?: number | null;
  rationale?: string | null;
  page_references: number[];
}

export interface ExpertReviewResponse {
  id: string;
  assignment_id: string;
  reviewer_id: string;
  reviewer_role: string;
  proposal_version_id: string;
  proposal_version_number: number;
  total_score?: number | null;
  recommendation?: string | null;
  notes?: string | null;
  submitted_at?: string | null;
  criterion_scores: CriterionScoreResponse[];
}

export interface ProposalReviewsResponse {
  proposal_id: string;
  reviews: ExpertReviewResponse[];
}

export interface ReviewSubmitResponse {
  assignment_id: string;
  status: string;
  message: string;
}

export async function listReviewAssignments(): Promise<AssignmentListResponse> {
  return apiFetch<AssignmentListResponse>("/reviews/assignments");
}

export async function assignReviewer(
  proposalId: string,
  reviewerEmail: string,
  role = "technical",
): Promise<ReviewAssignResponse> {
  return apiFetch<ReviewAssignResponse>("/reviews/assignments", {
    method: "POST",
    body: JSON.stringify({
      proposal_id: proposalId,
      reviewer_email: reviewerEmail,
      role,
    }),
  });
}

export async function submitReview(
  assignmentId: string,
  body: {
    total_score: number;
    recommendation: string;
    notes?: string | null;
    criterion_scores: Array<Record<string, unknown>>;
  },
): Promise<ReviewSubmitResponse> {
  return apiFetch<ReviewSubmitResponse>(`/reviews/${assignmentId}/submit`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listProposalReviews(
  proposalId: string,
): Promise<ProposalReviewsResponse> {
  return apiFetch<ProposalReviewsResponse>(`/reviews/proposals/${proposalId}`);
}

export async function declareReviewConflict(
  assignmentId: string,
  notes: string,
): Promise<{ assignment_id: string; status: string }> {
  return apiFetch<{ assignment_id: string; status: string }>(
    `/reviews/${assignmentId}/conflict`,
    {
      method: "POST",
      body: JSON.stringify({ notes }),
    },
  );
}

export async function resolveReviewConflict(
  assignmentId: string,
  resolution: "cleared" | "cancelled",
  notes: string,
): Promise<{ assignment_id: string; status: string }> {
  return apiFetch<{ assignment_id: string; status: string }>(
    `/reviews/${assignmentId}/conflict/resolve`,
    {
      method: "POST",
      body: JSON.stringify({ resolution, notes }),
    },
  );
}
