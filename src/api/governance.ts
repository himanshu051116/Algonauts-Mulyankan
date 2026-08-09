import { apiFetch } from "./client";

export interface AdjudicationResponse {
  id: string;
  proposal_id: string;
  proposal_version_id: string;
  adjudicator_id: string;
  criterion_id?: string | null;
  reason: string;
  resolved_score?: number | null;
  created_at: string;
}

export interface AdjudicationListResponse {
  proposal_id: string;
  adjudications: AdjudicationResponse[];
}

export interface CommitteeDecisionResponse {
  id: string;
  proposal_id: string;
  proposal_version_id: string;
  decision: "approved" | "rejected" | "revision_required";
  decision_notes?: string | null;
  decided_by: string;
  model_score_at_decision?: number | null;
  expert_score_at_decision?: number | null;
  decided_at: string;
}

export async function listAdjudications(
  proposalId: string,
): Promise<AdjudicationListResponse> {
  return apiFetch<AdjudicationListResponse>(
    `/governance/proposals/${proposalId}/adjudications`,
  );
}

export async function createAdjudication(
  proposalId: string,
  body: {
    criterion_id?: string | null;
    reason: string;
    resolved_score?: number | null;
  },
): Promise<AdjudicationResponse> {
  return apiFetch<AdjudicationResponse>(
    `/governance/proposals/${proposalId}/adjudications`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export async function getCommitteeDecision(
  proposalId: string,
): Promise<CommitteeDecisionResponse> {
  return apiFetch<CommitteeDecisionResponse>(
    `/governance/proposals/${proposalId}/committee-decision`,
  );
}

export async function createCommitteeDecision(
  proposalId: string,
  body: {
    decision: "approved" | "rejected" | "revision_required";
    decision_notes: string;
  },
): Promise<CommitteeDecisionResponse> {
  return apiFetch<CommitteeDecisionResponse>(
    `/governance/proposals/${proposalId}/committee-decision`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}
