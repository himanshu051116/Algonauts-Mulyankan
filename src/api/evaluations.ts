import { apiFetch } from "./client";

export interface EvaluationResponse {
  proposal_id: string; status: string; model_run_id?: string | null;
  rule_evaluation?: Record<string, unknown> | null;
  scoring?: Record<string, unknown> | null;
  document_audit?: Record<string, unknown> | null;
  document_gate?: Record<string, unknown> | null;
  prior_project_check?: Record<string, unknown> | null;
  engine_version?: string | null; input_checksum?: string | null; output_checksum?: string | null;
  started_at?: string | null; completed_at?: string | null;
  error_message?: string | null;
}

export interface EvaluationRerunResponse {
  proposal_id: string; status: string; message: string;
}

export async function getEvaluation(proposalId: string): Promise<EvaluationResponse> {
  return apiFetch<EvaluationResponse>(`/evaluations/${proposalId}`);
}

export async function rerunEvaluation(proposalId: string): Promise<EvaluationRerunResponse> {
  return apiFetch<EvaluationRerunResponse>(`/evaluations/${proposalId}/rerun`, { method: "POST" });
}
