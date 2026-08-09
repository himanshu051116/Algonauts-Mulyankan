import { useEffect, useMemo, useState } from "react";
import { EyeOff, Loader2, ShieldCheck, TriangleAlert } from "lucide-react";
import type { ReviewerAssignmentResponse } from "../../api/reviews";
import * as api from "../../lib/api";

interface CriterionAnnotation {
  score: string;
  rationale: string;
  pages: string;
  confidence: string;
  evidenceCoverage: string;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function pageReferences(raw: string): number[] | null {
  const tokens = raw
    .split(/[,;\s]+/)
    .map((token) => token.trim())
    .filter(Boolean);
  if (!tokens.length) return null;
  const pages = tokens.map(Number);
  if (pages.some((page) => !Number.isInteger(page) || page < 1)) return null;
  return [...new Set(pages)];
}

export function ShadowReviewDesk({
  assignments,
  onReviewSaved,
}: {
  assignments: ReviewerAssignmentResponse[];
  onReviewSaved: () => Promise<void>;
}) {
  const shadowAssignments = useMemo(
    () =>
      assignments.filter(
        (assignment) =>
          assignment.is_shadow_validation &&
          !["completed", "cancelled"].includes(assignment.status),
      ),
    [assignments],
  );
  const [selectedId, setSelectedId] = useState(shadowAssignments[0]?.id ?? "");
  const [form, setForm] = useState<api.ValidationReviewFormResponse | null>(null);
  const [annotations, setAnnotations] = useState<Record<string, CriterionAnnotation>>({});
  const [recommendation, setRecommendation] = useState<
    "approved" | "revision" | "rejected"
  >("revision");
  const [notes, setNotes] = useState("");
  const [conflictNotes, setConflictNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!selectedId && shadowAssignments[0]) setSelectedId(shadowAssignments[0].id);
  }, [selectedId, shadowAssignments]);

  useEffect(() => {
    if (!selectedId) {
      setForm(null);
      return;
    }
    setLoading(true);
    setMessage("");
    void api
      .getValidationReviewForm(selectedId)
      .then((response) => {
        setForm(response);
        setAnnotations(
          Object.fromEntries(
            response.criteria.map((criterion) => [
              criterion.criterion_id,
              {
                score: "",
                rationale: "",
                pages: "",
                confidence: "",
                evidenceCoverage: "",
              },
            ]),
          ),
        );
      })
      .catch((error) => setMessage(errorMessage(error)))
      .finally(() => setLoading(false));
  }, [selectedId]);

  const updateAnnotation = (
    criterionId: string,
    field: keyof CriterionAnnotation,
    value: string,
  ) => {
    setAnnotations((current) => ({
      ...current,
      [criterionId]: {
        ...(current[criterionId] ?? {
          score: "",
          rationale: "",
          pages: "",
          confidence: "",
          evidenceCoverage: "",
        }),
        [field]: value,
      },
    }));
  };

  const total = form
    ? form.criteria.reduce((sum, criterion) => {
        const value = Number(annotations[criterion.criterion_id]?.score);
        return sum + (Number.isFinite(value) ? value : 0);
      }, 0)
    : 0;

  const submit = async () => {
    if (!form) return;
    for (const criterion of form.criteria) {
      const annotation = annotations[criterion.criterion_id];
      const score = Number(annotation?.score);
      if (
        !annotation ||
        annotation.score === "" ||
        !Number.isFinite(score) ||
        score < 0 ||
        score > criterion.maximum
      ) {
        setMessage(
          `Enter a score from 0 to ${criterion.maximum} for ${criterion.criterion}.`,
        );
        return;
      }
      if (annotation.rationale.trim().length < 10) {
        setMessage(`Add a concise evidence rationale for ${criterion.criterion}.`);
        return;
      }
      if (!pageReferences(annotation.pages)) {
        setMessage(`Add one or more valid page numbers for ${criterion.criterion}.`);
        return;
      }
      for (const [label, value] of [
        ["confidence", annotation.confidence],
        ["evidence coverage", annotation.evidenceCoverage],
      ] as const) {
        if (value !== "") {
          const numeric = Number(value);
          if (!Number.isFinite(numeric) || numeric < 0 || numeric > 1) {
            setMessage(`Enter ${label} from 0 to 1 for ${criterion.criterion}.`);
            return;
          }
        }
      }
    }

    setLoading(true);
    setMessage("");
    try {
      const response = await api.submitReview(form.assignment_id, {
        total_score: Math.round(total * 100) / 100,
        recommendation,
        notes: notes.trim() || null,
        criterion_scores: form.criteria.map((criterion) => {
          const annotation = annotations[criterion.criterion_id];
          return {
            criterion_id: criterion.criterion_id,
            score: Number(annotation.score),
            confidence:
              annotation.confidence === "" ? null : Number(annotation.confidence),
            evidence_coverage:
              annotation.evidenceCoverage === ""
                ? null
                : Number(annotation.evidenceCoverage),
            rationale: annotation.rationale.trim(),
            page_references: pageReferences(annotation.pages) ?? [],
          };
        }),
      });
      setMessage(response.message);
      await onReviewSaved();
      setSelectedId("");
      setForm(null);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  const declareConflict = async () => {
    if (!selectedId || conflictNotes.trim().length < 3) {
      setMessage("Describe the conflict before submitting it.");
      return;
    }
    setLoading(true);
    try {
      await api.declareReviewConflict(selectedId, conflictNotes.trim());
      setMessage("Conflict declared. The assignment is locked for coordinator review.");
      await onReviewSaved();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-stack shadow-review-desk">
      <section className="hero-panel shadow-review-hero">
        <div>
          <span className="eyebrow">
            <EyeOff size={15} /> Blind expert annotation
          </span>
          <h1>Shadow review desk</h1>
          <p>
            Score the frozen rubric independently. Automated scores and other expert
            labels remain hidden until your immutable review is submitted.
          </p>
        </div>
        <div className="validation-safety-card">
          <ShieldCheck />
          <strong>Decision isolation</strong>
          <span>Your review is used for model validation only.</span>
          <small>It does not change the proposal outcome.</small>
        </div>
      </section>

      {message && <div className="alert info">{message}</div>}

      {!shadowAssignments.length ? (
        <section className="panel shadow-empty">
          <ShieldCheck size={28} />
          <h2>No pending blind assignments</h2>
          <p>New expert-validation cases will appear here when assigned.</p>
        </section>
      ) : (
        <section className="panel shadow-review-form">
          <label>
            Assignment
            <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
              {shadowAssignments.map((assignment) => (
                <option key={assignment.id} value={assignment.id}>
                  Proposal version {assignment.proposal_version_number} · {assignment.role}
                </option>
              ))}
            </select>
          </label>

          {loading && (
            <p>
              <Loader2 className="spin" /> Loading frozen rubric…
            </p>
          )}
          {form && (
            <>
              <div className="shadow-form-heading">
                <div>
                  <span>{form.study_name ?? "Validation study"}</span>
                  <h2>{form.proposal_title}</h2>
                  <p>
                    Rubric {form.rubric_version} · Protocol {form.protocol_version} ·
                    Rulebook {form.annotation_rulebook_version}
                  </p>
                </div>
                {form.model_output_hidden && (
                  <div className="blind-badge">
                    <EyeOff /> Model output hidden
                  </div>
                )}
              </div>
              <div className="alert info">
                <TriangleAlert size={17} /> Score only documented evidence. Every criterion
                requires a rationale and source-page reference.
              </div>
              <div className="shadow-criterion-grid">
                {form.criteria.map((criterion) => {
                  const annotation = annotations[criterion.criterion_id];
                  return (
                    <fieldset key={criterion.criterion_id}>
                      <legend>{criterion.criterion}</legend>
                      <small>
                        {criterion.category} · maximum {criterion.maximum}
                      </small>
                      <div className="shadow-score-row">
                        <label>
                          Score
                          <input
                            type="number"
                            min="0"
                            max={criterion.maximum}
                            step="0.25"
                            value={annotation?.score ?? ""}
                            onChange={(event) =>
                              updateAnnotation(
                                criterion.criterion_id,
                                "score",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label>
                          Confidence (0–1)
                          <input
                            type="number"
                            min="0"
                            max="1"
                            step="0.05"
                            value={annotation?.confidence ?? ""}
                            onChange={(event) =>
                              updateAnnotation(
                                criterion.criterion_id,
                                "confidence",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                        <label>
                          Evidence coverage (0–1)
                          <input
                            type="number"
                            min="0"
                            max="1"
                            step="0.05"
                            value={annotation?.evidenceCoverage ?? ""}
                            onChange={(event) =>
                              updateAnnotation(
                                criterion.criterion_id,
                                "evidenceCoverage",
                                event.target.value,
                              )
                            }
                          />
                        </label>
                      </div>
                      <label>
                        Criterion rationale
                        <textarea
                          rows={3}
                          value={annotation?.rationale ?? ""}
                          onChange={(event) =>
                            updateAnnotation(
                              criterion.criterion_id,
                              "rationale",
                              event.target.value,
                            )
                          }
                          placeholder="Explain the score using only documented evidence."
                        />
                      </label>
                      <label>
                        Source pages
                        <input
                          value={annotation?.pages ?? ""}
                          onChange={(event) =>
                            updateAnnotation(
                              criterion.criterion_id,
                              "pages",
                              event.target.value,
                            )
                          }
                          placeholder="Example: 4, 7, 12"
                        />
                      </label>
                    </fieldset>
                  );
                })}
              </div>
              <div className="shadow-review-footer">
                <label>
                  Total score
                  <input value={Math.round(total * 100) / 100} readOnly />
                </label>
                <label>
                  Recommendation
                  <select
                    value={recommendation}
                    onChange={(event) =>
                      setRecommendation(
                        event.target.value as "approved" | "revision" | "rejected",
                      )
                    }
                  >
                    <option value="approved">Recommended</option>
                    <option value="revision">Revision required</option>
                    <option value="rejected">Not recommended</option>
                  </select>
                </label>
                <label className="full">
                  Overall expert note
                  <textarea
                    rows={4}
                    value={notes}
                    onChange={(event) => setNotes(event.target.value)}
                    placeholder="Record overall uncertainty and important cross-criterion observations."
                  />
                </label>
              </div>
              <div className="shadow-actions">
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => void submit()}
                  disabled={loading}
                >
                  <ShieldCheck size={17} /> Submit immutable blind review
                </button>
                <label>
                  Conflict declaration
                  <input
                    value={conflictNotes}
                    onChange={(event) => setConflictNotes(event.target.value)}
                    placeholder="Organisation, collaborator, financial or personal conflict"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void declareConflict()}
                  disabled={loading}
                >
                  Declare conflict
                </button>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
