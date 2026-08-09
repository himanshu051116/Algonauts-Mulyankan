import { useMemo, useState } from "react";
import {
  ArrowDownUp,
  ChevronRight,
  FileText,
  Filter,
  History,
  Search,
  X,
} from "lucide-react";
import type {
  Submission,
  Evaluation,
  EvaluationReview,
  Status,
} from "../../types";
import { StatusBadge } from "../../components/shared/StatusBadge";
import { EmptyMini } from "../../components/shared/EmptyMini";
import { LoadingPanel } from "../../components/shared/LoadingPanel";
import { ReportModal } from "../reviews/ReportModal";
import type { ReviewerAssignmentResponse } from "../../api/reviews";

const evaluationScore = (evaluation?: Evaluation): number | null =>
  evaluation?.stream_total_score ?? evaluation?.total_score ?? null;

type SortOption = "newest" | "oldest" | "score-high" | "score-low";

export function SubmissionHistory({
  userId,
  userRole,
  submissions,
  evaluationMap,
  reviewMap,
  assignments,
  loading,
  statusOf,
  onReviewSaved,
}: {
  userId: string;
  userRole: string;
  submissions: Submission[];
  evaluationMap: Map<string, Evaluation>;
  reviewMap: Map<string, EvaluationReview[]>;
  assignments: ReviewerAssignmentResponse[];
  loading: boolean;
  statusOf: (submission: Submission) => Status;
  onReviewSaved: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | Status>("all");
  const [sort, setSort] = useState<SortOption>("newest");
  const [selected, setSelected] = useState<Submission | null>(null);

  const filtered = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return submissions
      .filter((submission) => {
        const matchesQuery = `${submission.title} ${submission.description ?? ""}`
          .toLowerCase()
          .includes(normalizedQuery);
        return matchesQuery && (filter === "all" || statusOf(submission) === filter);
      })
      .sort((left, right) => {
        const leftDate = new Date(left.created_at ?? 0).getTime();
        const rightDate = new Date(right.created_at ?? 0).getTime();
        const leftScore = evaluationScore(evaluationMap.get(left.id)) ?? -1;
        const rightScore = evaluationScore(evaluationMap.get(right.id)) ?? -1;
        if (sort === "oldest") return leftDate - rightDate;
        if (sort === "score-high") return rightScore - leftScore;
        if (sort === "score-low") return leftScore - rightScore;
        return rightDate - leftDate;
      });
  }, [evaluationMap, filter, query, sort, statusOf, submissions]);

  if (loading) return <LoadingPanel />;

  return (
    <div className="page-stack">
      <section className="history-header">
        <div>
          <span className="eyebrow">
            <History size={15} /> Records
          </span>
          <h1>Submission history</h1>
          <p>
            Search, sort, and inspect previous preliminary scrutiny results and
            human-review records.
          </p>
        </div>
      </section>
      <section className="panel history-panel">
        <div className="history-tools">
          <label className="search-box">
            <Search size={18} aria-hidden="true" />
            <span className="sr-only">Search proposals</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search title or summary…"
              type="search"
            />
            {query && (
              <button
                type="button"
                className="clear-search"
                onClick={() => setQuery("")}
                aria-label="Clear proposal search"
              >
                <X size={16} />
              </button>
            )}
          </label>
          <label className="filter-box">
            <Filter size={17} aria-hidden="true" />
            <span className="sr-only">Filter by status</span>
            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value as "all" | Status)}
            >
              <option value="all">All statuses</option>
              <option value="approved">Recommended</option>
              <option value="revision">Needs revision</option>
              <option value="rejected">Not recommended</option>
              <option value="pending">Pending</option>
              <option value="evaluating">Evaluating</option>
              <option value="human_review">Human review</option>
              <option value="adjudication">Adjudication</option>
              <option value="committee_review">Committee review</option>
              <option value="completed">Assessment ready</option>
              <option value="withdrawn">Withdrawn</option>
              <option value="error">Processing error</option>
            </select>
          </label>
          <label className="filter-box sort-box">
            <ArrowDownUp size={17} aria-hidden="true" />
            <span className="sr-only">Sort proposals</span>
            <select
              value={sort}
              onChange={(event) => setSort(event.target.value as SortOption)}
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="score-high">Highest score</option>
              <option value="score-low">Lowest score</option>
            </select>
          </label>
        </div>
        <div className="history-count" aria-live="polite">
          Showing {filtered.length} of {submissions.length}{" "}
          {submissions.length === 1 ? "proposal" : "proposals"}
        </div>
        {filtered.length ? (
          <div className="history-list">
            {filtered.map((submission) => {
              const evaluation = evaluationMap.get(submission.id);
              const status = statusOf(submission);
              const score = evaluationScore(evaluation);
              return (
                <button
                  type="button"
                  className="history-row"
                  key={submission.id}
                  onClick={() => setSelected(submission)}
                  aria-label={`Open report for ${submission.title}`}
                >
                  <div className="document-icon" aria-hidden="true">
                    <FileText />
                  </div>
                  <div className="history-main">
                    <strong>{submission.title}</strong>
                    <span>{submission.description ?? "No executive summary provided"}</span>
                    <small>
                      {(submission.document_file_name ?? submission.submission_type ?? "proposal").toUpperCase()}{" "}
                      • {submission.created_at
                        ? new Date(submission.created_at).toLocaleDateString(undefined, {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })
                        : "Recently"}
                    </small>
                    <span className="history-mobile-meta">
                      <StatusBadge status={status} />
                      <b>{score == null ? "Not scored" : `${score}/100`}</b>
                    </span>
                  </div>
                  <StatusBadge status={status} />
                  <div className="row-score" aria-label={score == null ? "Not scored" : `Score ${score} out of 100`}>
                    <strong>{score ?? "—"}</strong>
                    <span>/100</span>
                  </div>
                  <ChevronRight size={20} aria-hidden="true" />
                </button>
              );
            })}
          </div>
        ) : (
          <EmptyMini text="No proposals match the current search and filters." />
        )}
      </section>
      {selected && (
        <ReportModal
          userId={userId}
          userRole={userRole}
          submission={selected}
          evaluation={evaluationMap.get(selected.id)}
          reviews={(reviewMap.get(selected.id) ?? []).filter(
            (review) =>
              !review.proposal_version_number ||
              review.proposal_version_number === selected.current_version,
          )}
          assignments={assignments.filter(
            (assignment) =>
              assignment.proposal_id === selected.id &&
              assignment.proposal_version_number === selected.current_version,
          )}
          status={statusOf(selected)}
          onReviewSaved={onReviewSaved}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
