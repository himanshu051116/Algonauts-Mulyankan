import { useMemo } from "react";
import {
  BarChart3,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Clock3,
  FileText,
  Gauge,
  Sparkles,
  XCircle,
} from "lucide-react";
import type { Submission, Evaluation, Status } from "../../types";
import { StatCard } from "../../components/shared/StatCard";
import { StatusBadge } from "../../components/shared/StatusBadge";
import { EmptyMini } from "../../components/shared/EmptyMini";
import { LoadingPanel } from "../../components/shared/LoadingPanel";

const evaluationScore = (evaluation?: Evaluation): number | null =>
  evaluation?.stream_total_score ?? evaluation?.total_score ?? null;

function SubmissionRow({
  submission,
  status,
  onOpen,
}: {
  submission: Submission;
  status: Status;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      className="submission-row"
      onClick={onOpen}
      aria-label={`Open ${submission.title} in submission history`}
    >
      <div className="document-icon" aria-hidden="true">
        <FileText />
      </div>
      <div>
        <strong>{submission.title}</strong>
        <span>
          {submission.created_at
            ? new Date(submission.created_at).toLocaleDateString(undefined, {
                day: "numeric",
                month: "short",
                year: "numeric",
              })
            : "Recently"}
        </span>
      </div>
      <StatusBadge status={status} />
      <ChevronRight className="row-chevron" size={17} aria-hidden="true" />
    </button>
  );
}

export function Overview({
  submissions,
  evaluations,
  loading,
  statusOf,
  onSubmit,
  onHistory,
}: {
  submissions: Submission[];
  evaluations: Evaluation[];
  loading: boolean;
  statusOf: (submission: Submission) => Status;
  onSubmit: () => void;
  onHistory: () => void;
}) {
  const statuses = useMemo(
    () => submissions.map(statusOf),
    [submissions, statusOf],
  );
  const stats = useMemo(
    () => ({
      total: submissions.length,
      approved: statuses.filter((status) => status === "approved").length,
      revision: statuses.filter((status) => status === "revision").length,
      rejected: statuses.filter((status) => status === "rejected").length,
      pending: statuses.filter((status) => status === "pending").length,
      evaluating: statuses.filter((status) => status === "evaluating").length,
      humanReview: statuses.filter((status) => status === "human_review").length,
      adjudication: statuses.filter((status) => status === "adjudication").length,
      committeeReview: statuses.filter((status) => status === "committee_review").length,
      withdrawn: statuses.filter((status) => status === "withdrawn").length,
      errors: statuses.filter((status) => status === "error").length,
      completed: statuses.filter((status) => status === "completed").length,
    }),
    [submissions.length, statuses],
  );

  const chartData = [
    { name: "Recommended", value: stats.approved, color: "#43c68b" },
    { name: "Needs revision", value: stats.revision, color: "#f4b942" },
    { name: "Not recommended", value: stats.rejected, color: "#f06b65" },
    {
      name: "Automated evaluation",
      value: stats.pending + stats.evaluating,
      color: "#63a8ff",
    },
    {
      name: "Human review",
      value:
        stats.humanReview +
        stats.adjudication +
        stats.committeeReview +
        stats.completed,
      color: "#9b87f5",
    },
    { name: "Withdrawn", value: stats.withdrawn, color: "#7f898f" },
    { name: "Processing error", value: stats.errors, color: "#ff8e5c" },
  ].filter((item) => item.value > 0);

  let cursor = 0;
  const segments = chartData.map((item) => {
    const start = cursor;
    cursor += stats.total ? (item.value / stats.total) * 100 : 0;
    return `${item.color} ${start}% ${cursor}%`;
  });
  const distributionStyle = {
    background: `conic-gradient(${segments.join(", ")})`,
  };

  const scored = evaluations
    .map(evaluationScore)
    .filter((score): score is number => score != null);
  const average = scored.length
    ? Math.round(scored.reduce((sum, score) => sum + score, 0) / scored.length)
    : null;

  if (loading) return <LoadingPanel />;

  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div>
          <span className="eyebrow">
            <Sparkles size={15} /> Preliminary scrutiny overview
          </span>
          <h1>Standardise coal R&amp;D proposal review.</h1>
          <p>
            Track advisory assessments, identify proposals requiring attention,
            and move each submission through a traceable human-review workflow.
          </p>
          <div className="hero-actions">
            <button
              type="button"
              className="primary-button compact"
              onClick={onSubmit}
            >
              <ClipboardCheck size={18} /> Start scrutiny
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={onHistory}
            >
              Review history <ChevronRight size={17} />
            </button>
          </div>
        </div>
        <div className="score-orbit" aria-label="Portfolio average score">
          <div>
            <span>Portfolio score</span>
            <strong>{average ?? "—"}</strong>
            <small>{average == null ? "No scored proposals" : "/ 100 average"}</small>
          </div>
        </div>
      </section>
      <section className="stat-grid" aria-label="Portfolio summary">
        <StatCard
          label="Total proposals"
          value={stats.total}
          change="All submissions"
          icon={<FileText />}
          tone="amber"
        />
        <StatCard
          label="In progress"
          value={
            stats.pending +
            stats.evaluating +
            stats.humanReview +
            stats.adjudication +
            stats.committeeReview +
            stats.completed
          }
          change="Evaluation or human review"
          icon={<Clock3 />}
          tone="blue"
        />
        <StatCard
          label="Recommended"
          value={stats.approved}
          change={`${stats.total ? Math.round((stats.approved / stats.total) * 100) : 0}% of portfolio`}
          icon={<CheckCircle2 />}
          tone="green"
        />
        <StatCard
          label="Needs attention"
          value={stats.revision + stats.rejected + stats.errors}
          change="Revision, rejection, or error"
          icon={stats.rejected + stats.errors > stats.revision ? <XCircle /> : <Gauge />}
          tone="yellow"
        />
      </section>
      <section className="dashboard-grid">
        <div className="panel chart-panel">
          <div className="panel-heading">
            <div>
              <span>PORTFOLIO</span>
              <h2>Current workflow distribution</h2>
            </div>
            <BarChart3 size={20} aria-hidden="true" />
          </div>
          {stats.total ? (
            <div className="distribution-chart">
              <div
                className="donut-chart"
                style={distributionStyle}
                role="img"
                aria-label={chartData
                  .map((item) => `${item.name}: ${item.value}`)
                  .join(", ")}
              >
                <div className="donut-hole">
                  <strong>{stats.total}</strong>
                  <span>proposals</span>
                </div>
              </div>
              <div className="chart-legend">
                {chartData.map((item) => (
                  <div key={item.name}>
                    <i style={{ background: item.color }} />
                    <span>{item.name}</span>
                    <strong>{item.value}</strong>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <EmptyMini text="Distribution will appear after the first preliminary scrutiny." />
          )}
        </div>
        <div className="panel recent-panel">
          <div className="panel-heading">
            <div>
              <span>RECENT ACTIVITY</span>
              <h2>Latest proposals</h2>
            </div>
            <button type="button" onClick={onHistory}>
              View all
            </button>
          </div>
          {submissions.length ? (
            submissions
              .slice(0, 5)
              .map((submission) => (
                <SubmissionRow
                  key={submission.id}
                  submission={submission}
                  status={statusOf(submission)}
                  onOpen={onHistory}
                />
              ))
          ) : (
            <EmptyMini text="No proposals submitted yet." />
          )}
        </div>
      </section>
    </div>
  );
}
