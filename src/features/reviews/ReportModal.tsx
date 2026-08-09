import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  FileText,
  Loader2,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import type {
  Submission,
  Evaluation,
  EvaluationReview,
  Status,
  StreamEvaluationOutput,
} from "../../types";
import { StatusBadge } from "../../components/shared/StatusBadge";
import { EmptyMini } from "../../components/shared/EmptyMini";
import { ExplainabilityCard } from "../../components/shared/ExplainabilityCard";
import * as api from "../../lib/api";

function getStructuredEvaluation(
  evaluation?: Evaluation,
): StreamEvaluationOutput | null {
  if (
    !evaluation?.gpt_evaluation ||
    typeof evaluation.gpt_evaluation !== "object"
  )
    return null;
  const candidate =
    evaluation.gpt_evaluation as Partial<StreamEvaluationOutput>;
  return typeof candidate.schemaVersion === "string" &&
    typeof candidate.engine === "string"
    ? (candidate as StreamEvaluationOutput)
    : null;
}

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  if (
    error &&
    typeof error === "object" &&
    "message" in error &&
    typeof error.message === "string"
  )
    return error.message;
  return "Something went wrong.";
}

export function ReportModal({
  userId,
  userRole,
  submission,
  evaluation,
  reviews,
  assignments,
  status,
  onReviewSaved,
  onClose,
}: {
  userId: string;
  userRole: string;
  submission: Submission;
  evaluation?: Evaluation;
  reviews: EvaluationReview[];
  assignments: api.ReviewerAssignmentResponse[];
  status: Status;
  onReviewSaved: () => Promise<void>;
  onClose: () => void;
}) {
  const structured = getStructuredEvaluation(evaluation);
  const reviewCriteria = structured
    ? structured.detailedScores.map((s) => ({
        key: s.key,
        label: s.criterion,
        maximum: s.maximum,
      }))
    : [];
  const [reviewRecommendation, setReviewRecommendation] = useState<
    "approved" | "revision" | "rejected"
  >("revision");
  const [reviewNotes, setReviewNotes] = useState("");
  const [criterionScores, setCriterionScores] = useState<
    Record<string, string>
  >(() => Object.fromEntries(reviewCriteria.map((s) => [s.key, ""])));
  const [reviewSaving, setReviewSaving] = useState(false);
  const [reviewMessage, setReviewMessage] = useState("");
  const [documentOpening, setDocumentOpening] = useState(false);
  const [documentMessage, setDocumentMessage] = useState("");
  const [reviewerEmail, setReviewerEmail] = useState("");
  const [reviewerRole, setReviewerRole] = useState<"technical" | "financial">(
    "technical",
  );
  const [conflictNotes, setConflictNotes] = useState("");
  const [adjudications, setAdjudications] = useState<
    api.AdjudicationResponse[]
  >([]);
  const [committeeDecision, setCommitteeDecision] =
    useState<api.CommitteeDecisionResponse | null>(null);
  const [adjudicationReason, setAdjudicationReason] = useState("");
  const [resolvedScore, setResolvedScore] = useState("");
  const [decisionValue, setDecisionValue] = useState<
    "approved" | "rejected" | "revision_required"
  >("revision_required");
  const [decisionNotes, setDecisionNotes] = useState("");
  const [governanceSaving, setGovernanceSaving] = useState(false);
  const [governanceMessage, setGovernanceMessage] = useState("");
  const categories =
    structured?.categoryScores.map((c) => ({
      name: c.name,
      score: c.awarded,
      max: c.maximum,
      released: c.released,
    })) ?? [];
  const officialAutomatedScore =
    structured?.totalScore ?? evaluation?.total_score ?? null;
  const automatedScoreReleased = officialAutomatedScore !== null;
  const documentGateAccepted = structured?.documentGate.accepted === true;
  const hardScreenPassed = structured?.hardScreening.result === "pass";
  const expertScore = reviewCriteria.reduce((sum, s) => {
    const v = Number(criterionScores[s.key]);
    return sum + (Number.isFinite(v) ? v : 0);
  }, 0);
  const suggestions =
    structured?.improvementSuggestions ??
    evaluation?.future_suggestions?.split(/\n[•-]?\s*/).filter(Boolean) ??
    [];
  const currentAssignment = assignments.find((a) => a.reviewer_id === userId);
  const coordinatorRoles = new Set([
    "administrator",
    "scrutiny_officer",
    "committee_secretariat",
  ]);
  const canAssignReviewers = coordinatorRoles.has(userRole);
  const canAdjudicate = ["senior_adjudicator", "administrator"].includes(
    userRole,
  );
  const canRecordCommitteeDecision = [
    "committee_secretariat",
    "administrator",
  ].includes(userRole);
  const canSubmitReview = Boolean(
    currentAssignment &&
    !["completed", "cancelled", "conflict_declared"].includes(
      currentAssignment.status,
    ) &&
    currentAssignment.conflict_declared !== true,
  );
  const completedReviewCount = Math.max(
    reviews.length,
    assignments.filter((a) => a.status === "completed").length,
  );
  const isOwner = (submission.owner_id ?? submission.user_id) === userId;
  const requiredReviewers = structured?.humanReview.minimumReviewers ?? 1;
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const reportTitleId = `report-title-${submission.id}`;

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, []);

  useEffect(() => {
    let active = true;
    const load = async () => {
      const [adjudicationResult, decisionResult] = await Promise.all([
        api
          .listAdjudications(submission.id)
          .catch(() => ({ proposal_id: submission.id, adjudications: [] })),
        api.getCommitteeDecision(submission.id).catch(() => null),
      ]);
      if (!active) return;
      setAdjudications(adjudicationResult.adjudications);
      setCommitteeDecision(decisionResult);
    };
    void load();
    return () => {
      active = false;
    };
  }, [submission.id]);

  const refreshGovernance = async () => {
    const [adjudicationResult, decisionResult] = await Promise.all([
      api.listAdjudications(submission.id),
      api.getCommitteeDecision(submission.id).catch(() => null),
    ]);
    setAdjudications(adjudicationResult.adjudications);
    setCommitteeDecision(decisionResult);
  };

  const saveReview = async () => {
    if (!evaluation || !structured) return;
    if (isOwner) {
      setReviewMessage(
        "Proposal owners cannot submit reviews for their own proposals.",
      );
      return;
    }
    const invalidCriterion = reviewCriteria.find((s) => {
      const v = Number(criterionScores[s.key]);
      return (
        criterionScores[s.key] === "" ||
        !Number.isFinite(v) ||
        v < 0 ||
        v > s.maximum
      );
    });
    if (invalidCriterion) {
      setReviewMessage(
        `Score 0-${invalidCriterion.maximum} for ${invalidCriterion.label}.`,
      );
      return;
    }
    if (!currentAssignment) {
      setReviewMessage("No reviewer assignment found.");
      return;
    }
    if (!canSubmitReview) {
      setReviewMessage("This assignment is not available for submission.");
      return;
    }
    setReviewSaving(true);
    setReviewMessage("");
    try {
      const result = await api.submitReview(currentAssignment.id, {
        total_score: Math.round(expertScore),
        recommendation: reviewRecommendation,
        notes: reviewNotes.trim() || null,
        criterion_scores: reviewCriteria.map((s) => ({
          criterion_id: s.key,
          score: Number(criterionScores[s.key]),
          evidence_coverage: null,
          rationale: null,
          page_references: [],
        })),
      });
      setReviewMessage(result.message);
      await onReviewSaved();
    } catch (e) {
      setReviewMessage(errorMessage(e));
    } finally {
      setReviewSaving(false);
    }
  };

  const assignReviewer = async () => {
    if (!reviewerEmail.trim()) return setReviewMessage("Enter reviewer email.");
    setReviewSaving(true);
    try {
      const result = await api.assignReviewer(
        submission.id,
        reviewerEmail.trim(),
        reviewerRole,
      );
      setReviewMessage(result.message);
      setReviewerEmail("");
      await onReviewSaved();
    } catch (e) {
      setReviewMessage(errorMessage(e));
    } finally {
      setReviewSaving(false);
    }
  };

  const declareConflict = async () => {
    if (!currentAssignment) return;
    if (conflictNotes.trim().length < 3) {
      setReviewMessage("Explain the conflict before declaring it.");
      return;
    }
    setReviewSaving(true);
    setReviewMessage("");
    try {
      await api.declareReviewConflict(
        currentAssignment.id,
        conflictNotes.trim(),
      );
      setConflictNotes("");
      setReviewMessage(
        "Conflict declared. A coordinator must resolve or reassign it.",
      );
      await onReviewSaved();
    } catch (e) {
      setReviewMessage(errorMessage(e));
    } finally {
      setReviewSaving(false);
    }
  };

  const resolveConflict = async (
    assignmentId: string,
    resolution: "cleared" | "cancelled",
  ) => {
    const notes = window.prompt(
      resolution === "cleared"
        ? "Why is the conflict cleared?"
        : "Why is this assignment cancelled?",
    );
    if (!notes?.trim()) return;
    setReviewSaving(true);
    setReviewMessage("");
    try {
      await api.resolveReviewConflict(assignmentId, resolution, notes.trim());
      setReviewMessage(`Conflict ${resolution}.`);
      await onReviewSaved();
    } catch (e) {
      setReviewMessage(errorMessage(e));
    } finally {
      setReviewSaving(false);
    }
  };

  const submitAdjudication = async () => {
    if (adjudicationReason.trim().length < 10) {
      setGovernanceMessage(
        "Record a clear adjudication reason of at least 10 characters.",
      );
      return;
    }
    const score = resolvedScore.trim() ? Number(resolvedScore) : null;
    if (
      score !== null &&
      (!Number.isFinite(score) || score < 0 || score > 100)
    ) {
      setGovernanceMessage("Resolved score must be between 0 and 100.");
      return;
    }
    setGovernanceSaving(true);
    setGovernanceMessage("");
    try {
      await api.createAdjudication(submission.id, {
        reason: adjudicationReason.trim(),
        resolved_score: score,
      });
      setAdjudicationReason("");
      setResolvedScore("");
      setGovernanceMessage("Adjudication recorded.");
      await refreshGovernance();
      await onReviewSaved();
    } catch (e) {
      setGovernanceMessage(errorMessage(e));
    } finally {
      setGovernanceSaving(false);
    }
  };

  const submitCommitteeDecision = async () => {
    if (decisionNotes.trim().length < 10) {
      setGovernanceMessage(
        "Record committee reasons of at least 10 characters.",
      );
      return;
    }
    setGovernanceSaving(true);
    setGovernanceMessage("");
    try {
      const result = await api.createCommitteeDecision(submission.id, {
        decision: decisionValue,
        decision_notes: decisionNotes.trim(),
      });
      setCommitteeDecision(result);
      setDecisionNotes("");
      setGovernanceMessage(
        "Committee decision recorded and proposal status updated.",
      );
      await onReviewSaved();
    } catch (e) {
      setGovernanceMessage(errorMessage(e));
    } finally {
      setGovernanceSaving(false);
    }
  };

  const openProposalDocument = async () => {
    if (!submission.document_id) return;
    setDocumentOpening(true);
    setDocumentMessage("");
    try {
      const result = await api.getDocumentDownloadUrl(submission.document_id);
      const opened = window.open(
        result.download_url,
        "_blank",
        "noopener,noreferrer",
      );
      if (!opened) window.location.assign(result.download_url);
    } catch (error) {
      setDocumentMessage(errorMessage(error));
    } finally {
      setDocumentOpening(false);
    }
  };

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.currentTarget === e.target) onClose();
      }}
    >
      <article
        className="report-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={reportTitleId}
      >
        <button
          ref={closeButtonRef}
          type="button"
          className="modal-close"
          onClick={onClose}
          aria-label="Close report"
        >
          <X />
        </button>
        <div className="report-header">
          <div>
            <span>PRELIMINARY SCRUTINY REPORT</span>
            <h2 id={reportTitleId}>{submission.title}</h2>
            <p>{submission.description ?? ""}</p>
          </div>
          <div className={`report-score ${status} ${automatedScoreReleased ? "" : "not-scored"}`}>
            <strong>{automatedScoreReleased ? officialAutomatedScore : "—"}</strong>
            <span>{automatedScoreReleased ? "/ 100" : "NOT SCORED"}</span>
            <StatusBadge status={status} />
          </div>
        </div>
        {evaluation ? (
          <>
            <div className="prototype-notice report-prototype-notice">
              <ShieldCheck size={16} />
              <span>
                This report combines deterministic eligibility screening with a
                brochure-aligned trained NLP scorer. The packaged model is
                bootstrap-trained, remains advisory, and requires authorised
                human review before any decision.
              </span>
            </div>
            {structured && !structured.documentGate.accepted && (
              <div className="document-gate-banner">
                <TriangleAlert size={21} />
                <div>
                  <strong>Automated scoring was not released</strong>
                  <span>
                    {structured.documentGate.reasons[0] ??
                      `Document gate status: ${structured.documentGate.status.replace(/_/g, " ")}.`}
                  </span>
                  <small>
                    Classified as {structured.documentGate.documentType.replace(/_/g, " ")} · declared role {structured.documentGate.declaredRole.replace(/_/g, " ")}
                  </small>
                </div>
              </div>
            )}
            {structured && (
              <div
                className={`hard-screen-banner ${
                  hardScreenPassed && !documentGateAccepted
                    ? "review"
                    : structured.hardScreening.result
                }`}
              >
                {hardScreenPassed && documentGateAccepted ? (
                  <CheckCircle2 size={21} />
                ) : (
                  <TriangleAlert size={21} />
                )}
                <div>
                  <strong>
                    {hardScreenPassed
                      ? documentGateAccepted
                        ? "Deterministic eligibility checks passed"
                        : "No deterministic rule failure detected"
                      : "Deterministic eligibility issue found"}
                  </strong>
                  {hardScreenPassed && !documentGateAccepted && (
                    <span>
                      The available extracted information did not trigger a
                      hard-screening rule. This does not establish document
                      acceptance, completeness, or scoring eligibility.
                    </span>
                  )}
                  {!hardScreenPassed && (
                    <span>
                      {structured.hardScreening.failedReasons[0] ??
                        "One or more deterministic eligibility checks require review."}
                    </span>
                  )}
                </div>
              </div>
            )}
            <details className="technical-details">
              <summary>Technical details</summary>
              {structured && (
                <div className="stream-report-strip">
                  <Sparkles size={18} />
                  <div>
                    <strong>{structured.researchStream.name}</strong>
                    <span>
                      Model profile: {structured.researchStream.modelProfile}
                    </span>
                  </div>
                </div>
              )}
              {structured?.documentAudit &&
                structured.documentAudit.wordCount > 0 && (
                  <div className="panel document-audit">
                    <div className="audit-heading">
                      <div>
                        <span>DOCUMENT EXAMINATION</span>
                        <h3>
                          {structured.documentAudit.fileName ??
                            "Manual proposal body"}
                        </h3>
                      </div>
                      <b
                        className={
                          structured.documentAudit.sufficientForScoring
                            ? "pass"
                            : "fail"
                        }
                      >
                        {structured.documentAudit.sufficientForScoring
                          ? "COMPLETE"
                          : "INSUFFICIENT"}
                      </b>
                    </div>
                    <div className="audit-metrics">
                      <div>
                        <strong>{structured.documentAudit.wordCount}</strong>
                        <span>words examined</span>
                      </div>
                      <div>
                        <strong>
                          {structured.documentAudit.pageCount ?? "—"}
                        </strong>
                        <span>pages extracted</span>
                      </div>
                      <div>
                        <strong>
                          {structured.documentAudit.sentenceCount}
                        </strong>
                        <span>substantive sentences</span>
                      </div>
                      <div>
                        <strong>
                          {Math.round(
                            structured.documentAudit.overallCoverage * 100,
                          )}
                          %
                        </strong>
                        <span>criterion coverage</span>
                      </div>
                      <div>
                        <strong>
                          {structured.documentAudit.ocrPages?.length ?? 0}
                        </strong>
                        <span>OCR pages</span>
                      </div>
                      <div>
                        <strong>
                          {structured.documentAudit.tablesDetected ?? 0}
                        </strong>
                        <span>tables detected</span>
                      </div>
                      <div>
                        <strong>
                          {structured.documentAudit.imagesDetected ?? 0}
                        </strong>
                        <span>images inventoried</span>
                      </div>
                    </div>
                  </div>
                )}
              {structured?.priorProjectCheck && (
                <div className="reliability-grid">
                  <div className="panel reliability-card">
                    <span>PRIOR-PROJECT CHECK</span>
                    <h3>
                      {Math.round(
                        structured.priorProjectCheck.highestSimilarity * 100,
                      )}
                      % highest overlap
                    </h3>
                    <p>
                      {structured.priorProjectCheck.checkedProjects} previous
                      proposal(s) checked.
                    </p>
                  </div>
                  <div className="panel reliability-card">
                    <span>CALIBRATION</span>
                    <h3>
                      {structured.calibration.applied
                        ? "Active"
                        : "No calibration data"}
                    </h3>
                    <p>{structured.calibration.note}</p>
                  </div>
                </div>
              )}
            </details>
            <div className="report-grid">
              <div className="panel report-chart">
                <h3>Category performance (advisory)</h3>
                <div
                  className="category-bars"
                  role="img"
                  aria-label="Advisory category scores"
                >
                  {categories.map((category) => {
                    const percentage = category.score !== null && category.max
                      ? Math.min(100, Math.max(0, (category.score / category.max) * 100))
                      : 0;
                    return (
                      <div className="category-bar-row" key={category.name}>
                        <span title={category.name}>{category.name}</span>
                        <div className="category-bar-track">
                          <i style={{ width: `${percentage}%` }} />
                        </div>
                        <strong>
                          {category.score === null ? "Not scored" : `${category.score}/${category.max}`}
                        </strong>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="panel report-summary">
                <span>ADVISORY ASSESSMENT</span>
                <h3>
                  {structured?.finalRecommendation ??
                    "Not recommended at this stage"}
                </h3>
                <p>
                  {evaluation.combined_reasoning ||
                    "No narrative assessment was provided."}
                </p>
              </div>
            </div>
            {structured && (
              <>
                <details className="technical-details score-details">
                  <summary>Eligibility details</summary>
                  <div className="panel screening-table">
                    <h3>Eligibility screening</h3>
                    {structured.hardScreening.rules.map((rule) => (
                      <div className="screening-row" key={rule.id}>
                        <span
                          className={`rule-result ${rule.passed ? "pass" : "fail"}`}
                        >
                          {rule.passed ? "PASS" : "FAIL"}
                        </span>
                        <div>
                          <strong>{rule.label}</strong>
                          <p>{rule.reason}</p>
                          {rule.correction && (
                            <small>Correction: {rule.correction}</small>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
                <details className="technical-details score-details">
                  <summary>Detailed scoring</summary>
                  <div className="panel detailed-score-table">
                    <h3>Evidence-grounded criterion scores (advisory)</h3>
                    <div className="score-table-head">
                      <span>Criterion</span>
                      <span>Evidence</span>
                      <span>Marks</span>
                    </div>
                    {structured.detailedScores.map((item) => (
                      <div className="score-table-row" key={item.key}>
                        <div>
                          <strong>{item.criterion}</strong>
                          <small>{item.category}</small>
                        </div>
                        <p>
                          {item.evidence[0]?.text ??
                            "No specific evidence detected."}
                        </p>
                        <b className={item.released ? "" : "not-scored-mark"}>
                          {item.awarded === null ? "Not scored" : `${item.awarded}/${item.maximum}`}
                        </b>
                      </div>
                    ))}
                  </div>
                </details>
                <div className="explainability-grid">
                  <ExplainabilityCard
                    title="Strengths"
                    items={structured.strengths}
                  />
                  <ExplainabilityCard
                    title="Weaknesses"
                    items={structured.weaknesses}
                  />
                  <ExplainabilityCard
                    title="Risk areas"
                    items={structured.riskAreas}
                  />
                </div>
                {structured.humanReview.required && (
                  <div className="human-review-banner">
                    <ShieldCheck size={21} />
                    <div>
                      <strong>
                        Human review recommended ({completedReviewCount}/
                        {requiredReviewers} complete)
                      </strong>
                      <span>{structured.humanReview.reasons.join(" ")}</span>
                    </div>
                  </div>
                )}
                <details
                  className="review-details"
                  open={structured.humanReview.required}
                >
                  <summary>
                    {isOwner ? "Review status" : "Complete review"}
                  </summary>
                  <div className="panel expert-review-form">
                    <div>
                      <span>EXPERT REVIEW</span>
                      <h3>Independent reviewer assessment</h3>
                    </div>
                    {isOwner ? (
                      <div className="alert info">
                        Proposal owners can inspect review progress but cannot
                        submit or assign expert reviews.
                      </div>
                    ) : canSubmitReview ? (
                      <div className="review-inputs">
                        <label>
                          Total expert score
                          <input type="number" value={expertScore} readOnly />
                        </label>
                        <label>
                          Recommendation
                          <select
                            value={reviewRecommendation}
                            onChange={(e) =>
                              setReviewRecommendation(
                                e.target.value as
                                  "approved" | "revision" | "rejected",
                              )
                            }
                          >
                            <option value="approved">Recommended</option>
                            <option value="revision">Revision needed</option>
                            <option value="rejected">Not recommended</option>
                          </select>
                        </label>
                        <div className="criterion-label-grid full">
                          {reviewCriteria.map((s) => (
                            <label key={s.key}>
                              <span>{s.label}</span>
                              <input
                                type="number"
                                min="0"
                                max={s.maximum}
                                step={
                                  Number.isInteger(s.maximum) ? "1" : "0.25"
                                }
                                value={criterionScores[s.key] ?? ""}
                                onChange={(e) =>
                                  setCriterionScores((c) => ({
                                    ...c,
                                    [s.key]: e.target.value,
                                  }))
                                }
                                placeholder={`0-${s.maximum}`}
                              />
                            </label>
                          ))}
                        </div>
                        <label className="full">
                          Reviewer notes
                          <textarea
                            rows={3}
                            value={reviewNotes}
                            onChange={(e) => setReviewNotes(e.target.value)}
                            placeholder="Record evidence, disagreements, and corrections."
                          />
                        </label>
                      </div>
                    ) : (
                      <div className="alert info">
                        No active reviewer assignment is available for this
                        account.
                      </div>
                    )}
                    {currentAssignment &&
                      !isOwner &&
                      currentAssignment.status !== "completed" &&
                      currentAssignment.conflict_declared !== true && (
                        <div className="review-assignment">
                          <label>
                            Conflict of interest
                            <input
                              value={conflictNotes}
                              onChange={(e) => setConflictNotes(e.target.value)}
                              placeholder="Organisation, collaborator, financial or personal conflict"
                            />
                          </label>
                          <button type="button"
                            onClick={() => void declareConflict()}
                            disabled={reviewSaving}
                          >
                            Declare conflict
                          </button>
                        </div>
                      )}
                    {canAssignReviewers &&
                      assignments
                        .filter(
                          (assignment) =>
                            assignment.conflict_declared === true &&
                            assignment.status === "conflict_declared",
                        )
                        .map((assignment) => (
                          <div className="alert info" key={assignment.id}>
                            <strong>Conflict awaiting resolution</strong>
                            <p>{assignment.conflict_notes}</p>
                            <button type="button"
                              onClick={() =>
                                void resolveConflict(assignment.id, "cleared")
                              }
                              disabled={reviewSaving}
                            >
                              Clear conflict
                            </button>
                            <button type="button"
                              onClick={() =>
                                void resolveConflict(assignment.id, "cancelled")
                              }
                              disabled={reviewSaving}
                            >
                              Cancel assignment
                            </button>
                          </div>
                        ))}
                    {reviewMessage && <p>{reviewMessage}</p>}
                    {canSubmitReview && (
                      <button type="button"
                        onClick={() => void saveReview()}
                        disabled={reviewSaving}
                      >
                        {reviewSaving ? (
                          <Loader2 className="spin" size={16} />
                        ) : (
                          <ShieldCheck size={16} />
                        )}{" "}
                        Submit expert review
                      </button>
                    )}
                    {canAssignReviewers && (
                      <div className="review-assignment">
                        <label>
                          Reviewer email
                          <input
                            type="email"
                            value={reviewerEmail}
                            onChange={(e) => setReviewerEmail(e.target.value)}
                            placeholder="reviewer@organisation.gov.in"
                          />
                        </label>
                        <label>
                          Review role
                          <select
                            value={reviewerRole}
                            onChange={(e) =>
                              setReviewerRole(
                                e.target.value as "technical" | "financial",
                              )
                            }
                          >
                            <option value="technical">
                              Technical reviewer
                            </option>
                            <option value="financial">
                              Financial reviewer
                            </option>
                          </select>
                        </label>
                        <button type="button"
                          onClick={() => void assignReviewer()}
                          disabled={reviewSaving}
                        >
                          Assign reviewer
                        </button>
                      </div>
                    )}
                  </div>
                </details>
              </>
            )}
            {(committeeDecision ||
              adjudications.length > 0 ||
              canAdjudicate ||
              canRecordCommitteeDecision) && (
              <details
                className="review-details"
                open={Boolean(committeeDecision)}
              >
                <summary>Adjudication and committee decision</summary>
                <div className="panel expert-review-form">
                  <div>
                    <span>INSTITUTIONAL GOVERNANCE</span>
                    <h3>Version-bound decision record</h3>
                  </div>
                  {adjudications.map((item) => (
                    <div className="alert info" key={item.id}>
                      <strong>Adjudication</strong> — {item.reason}
                      {item.resolved_score != null && (
                        <span> Resolved score: {item.resolved_score}/100.</span>
                      )}
                    </div>
                  ))}
                  {committeeDecision ? (
                    <div className="alert info">
                      <strong>
                        Committee decision:{" "}
                        {committeeDecision.decision.replace(/_/g, " ")}
                      </strong>
                      <p>{committeeDecision.decision_notes}</p>
                      <small>
                        Model score:{" "}
                        {committeeDecision.model_score_at_decision ?? "—"};
                        expert mean:{" "}
                        {committeeDecision.expert_score_at_decision ?? "—"}
                      </small>
                    </div>
                  ) : (
                    <>
                      {canAdjudicate && (
                        <div className="review-inputs">
                          <label className="full">
                            Adjudication reason
                            <textarea
                              rows={3}
                              value={adjudicationReason}
                              onChange={(e) =>
                                setAdjudicationReason(e.target.value)
                              }
                              placeholder="Explain reviewer disagreement, evidence considered, and resolution."
                            />
                          </label>
                          <label>
                            Resolved total score (optional)
                            <input
                              type="number"
                              min="0"
                              max="100"
                              value={resolvedScore}
                              onChange={(e) => setResolvedScore(e.target.value)}
                            />
                          </label>
                          <button type="button"
                            onClick={() => void submitAdjudication()}
                            disabled={governanceSaving}
                          >
                            Record adjudication
                          </button>
                        </div>
                      )}
                      {canRecordCommitteeDecision && (
                        <div className="review-inputs">
                          <label>
                            Committee decision
                            <select
                              value={decisionValue}
                              onChange={(e) =>
                                setDecisionValue(
                                  e.target.value as
                                    | "approved"
                                    | "rejected"
                                    | "revision_required",
                                )
                              }
                            >
                              <option value="approved">Approve</option>
                              <option value="revision_required">
                                Request revision
                              </option>
                              <option value="rejected">Reject</option>
                            </select>
                          </label>
                          <label className="full">
                            Decision reasons
                            <textarea
                              rows={3}
                              value={decisionNotes}
                              onChange={(e) => setDecisionNotes(e.target.value)}
                              placeholder="Record the committee basis, conditions, dissent, and next action."
                            />
                          </label>
                          <button type="button"
                            onClick={() => void submitCommitteeDecision()}
                            disabled={governanceSaving}
                          >
                            Record final decision
                          </button>
                        </div>
                      )}
                    </>
                  )}
                  {governanceMessage && <p>{governanceMessage}</p>}
                </div>
              </details>
            )}
            <div className="panel suggestions">
              <h3>Suggested improvements</h3>
              {suggestions.length ? (
                suggestions.map((s, i) => (
                  <div key={`${s}-${i}`}>
                    <b>{String(i + 1).padStart(2, "0")}</b>
                    <p>{s}</p>
                  </div>
                ))
              ) : (
                <p>No additional suggestions were generated.</p>
              )}
            </div>
          </>
        ) : (
          <EmptyMini text="This proposal has not been scrutinised yet." />
        )}
        <div className="report-links">
          {submission.document_id ? (
            <button
              type="button"
              className="text-button"
              onClick={() => void openProposalDocument()}
              disabled={documentOpening}
            >
              {documentOpening ? (
                <Loader2 className="spin" size={17} />
              ) : (
                <FileText size={17} />
              )}
              Open {submission.document_file_name ?? "proposal document"}
            </button>
          ) : submission.file_url ? (
            <a href={submission.file_url} target="_blank" rel="noreferrer">
              <FileText size={17} /> Open proposal document
            </a>
          ) : null}
          {submission.link_url && (
            <a href={submission.link_url} target="_blank" rel="noreferrer">
              {" "}
              Open proposal link
            </a>
          )}
          {documentMessage && (
            <span className="alert error">{documentMessage}</span>
          )}
        </div>
      </article>
    </div>
  );
}
