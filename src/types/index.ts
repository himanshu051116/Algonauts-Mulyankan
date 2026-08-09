import type { Session } from "@supabase/supabase-js";
import type {
  EvaluationStreamId,
  StreamEvaluationOutput,
} from "../lib/evaluation-types";

export type View =
  | "overview"
  | "submit"
  | "history"
  | "validation"
  | "shadow-review"
  | "users";
export type Status =
  | "approved"
  | "revision"
  | "rejected"
  | "pending"
  | "evaluating"
  | "human_review"
  | "adjudication"
  | "committee_review"
  | "withdrawn"
  | "error"
  | "completed";

export interface Submission {
  id: string;
  user_id?: string;
  owner_id?: string;
  title: string;
  description?: string | null;
  submission_type?: string;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
  file_url?: string | null;
  document_id?: string | null;
  document_file_name?: string | null;
  link_url?: string | null;
  scheme_id?: string;
  current_version?: number;
  stream_id?: EvaluationStreamId;
}

export interface Evaluation {
  id: string;
  submission_id: string;
  total_score: number | null;
  stream_total_score?: number | null;
  stream_id?: EvaluationStreamId;
  combined_reasoning?: string | null;
  future_suggestions?: string | null;
  evaluated_by?: string;
  gpt_evaluation?: unknown;
  uniqueness_score?: number | null;
  patent_potential_score?: number | null;
  indigenization_score?: number | null;
  technical_clarity_score?: number | null;
  technology_readiness_score?: number | null;
  infrastructure_score?: number | null;
  team_track_record_score?: number | null;
  workplan_milestones_score?: number | null;
  adoption_likelihood_score?: number | null;
  economic_benefit_score?: number | null;
  safety_environment_score?: number | null;
  strategic_fit_score?: number | null;
  sc_st_participation_score?: number | null;
  women_researchers_score?: number | null;
  startup_rural_score?: number | null;
  multi_agency_collaboration_score?: number | null;
  budget_realism_score?: number | null;
  phased_funding_score?: number | null;
  roi_realism_score?: number | null;
  manpower_cost_ratio_score?: number | null;
  dependencies_listed_score?: number | null;
  mitigation_plans_score?: number | null;
  compliance_readiness_score?: number | null;
}

export interface EvaluationReview {
  id: string;
  submission_id: string;
  evaluation_id: string;
  reviewer_id: string;
  proposal_version_number?: number;
  expert_score: number;
  recommendation: "approved" | "revision" | "rejected";
  notes: string | null;
  criterion_scores: Record<string, number>;
  created_at: string;
}

export type { Session, StreamEvaluationOutput };
