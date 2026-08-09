import type { Status } from "../../types";

const LABELS: Record<Status, string> = {
  approved: "Recommended",
  revision: "Needs revision",
  rejected: "Not recommended",
  pending: "Pending",
  evaluating: "Evaluating",
  human_review: "Human review",
  adjudication: "Adjudication",
  committee_review: "Committee review",
  withdrawn: "Withdrawn",
  error: "Processing error",
  completed: "Assessment ready",
};

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`status-badge ${status}`}>{LABELS[status]}</span>;
}
