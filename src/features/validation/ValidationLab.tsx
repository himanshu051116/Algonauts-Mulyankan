import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Archive,
  Beaker,
  CheckCircle2,
  Database,
  Download,
  FlaskConical,
  Snowflake,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Users,
  XCircle,
} from "lucide-react";
import type { Submission } from "../../types";
import * as api from "../../lib/api";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function formatMetric(value: number | null | undefined, name: string): string {
  if (value == null) return "—";
  if (name.includes("rate") || name.includes("correlation")) {
    return value.toFixed(3);
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

export function ValidationLab({
  submissions,
}: {
  submissions: Submission[];
}) {
  const [studies, setStudies] = useState<api.ValidationStudyResponse[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [summary, setSummary] =
    useState<api.ValidationStudySummaryResponse | null>(null);
  const [cases, setCases] = useState<api.ValidationCaseResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");

  const [studyName, setStudyName] = useState("Coal R&D Shadow Pilot 2026");
  const [protocolVersion, setProtocolVersion] = useState(
    "expert-grounded-validation-v1",
  );
  const [rulebookVersion, setRulebookVersion] = useState(
    "expert-annotation-rulebook-v1",
  );
  const [minimumReviewers, setMinimumReviewers] = useState(2);
  const [proposalId, setProposalId] = useState("");
  const [partition, setPartition] = useState("shadow");
  const [reviewerEmail, setReviewerEmail] = useState("");
  const [reviewerRole, setReviewerRole] = useState<"technical" | "financial">(
    "technical",
  );
  const [caseForReviewer, setCaseForReviewer] = useState("");

  const selectedStudy = studies.find((study) => study.id === selectedId) ?? null;
  const allMetrics = useMemo(
    () =>
      (summary?.metrics ?? []).filter(
        (metric) => !metric.name.includes(":"),
      ),
    [summary],
  );

  const load = async (preferredId?: string) => {
    setLoading(true);
    setMessage("");
    try {
      const response = await api.listValidationStudies();
      setStudies(response.studies);
      const nextId =
        preferredId ?? selectedId ?? response.studies[0]?.id ?? "";
      const resolvedId = response.studies.some((study) => study.id === nextId)
        ? nextId
        : response.studies[0]?.id ?? "";
      setSelectedId(resolvedId);
      if (resolvedId) {
        const [studySummary, caseList] = await Promise.all([
          api.getValidationStudy(resolvedId),
          api.listValidationCases(resolvedId),
        ]);
        setSummary(studySummary);
        setCases(caseList.cases);
      } else {
        setSummary(null);
        setCases([]);
      }
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    void Promise.all([
      api.getValidationStudy(selectedId),
      api.listValidationCases(selectedId),
    ])
      .then(([studySummary, caseList]) => {
        setSummary(studySummary);
        setCases(caseList.cases);
      })
      .catch((error) => setMessage(errorMessage(error)));
  }, [selectedId]);

  const createStudy = async () => {
    if (!studyName.trim()) return;
    setWorking(true);
    setMessage("");
    try {
      const study = await api.createValidationStudy({
        name: studyName.trim(),
        description:
          "Blind expert comparison and shadow-mode validation. Outputs do not affect proposal decisions.",
        scheme_code: "MOC-ST",
        protocol_version: protocolVersion.trim(),
        annotation_rulebook_version: rulebookVersion.trim(),
        shadow_mode: true,
        minimum_reviews_per_case: minimumReviewers,
        recommendation_policy: {},
      });
      setMessage("Validation study created. Activate it before assigning reviewers.");
      await load(study.id);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setWorking(false);
    }
  };

  const updateStatus = async (status: string) => {
    if (!selectedStudy) return;
    setWorking(true);
    setMessage("");
    try {
      await api.updateValidationStudyStatus(selectedStudy.id, status);
      setMessage(`Study status changed to ${status}.`);
      await load(selectedStudy.id);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setWorking(false);
    }
  };

  const addCase = async () => {
    if (!selectedStudy || !proposalId) return;
    setWorking(true);
    setMessage("");
    try {
      await api.addValidationCase(selectedStudy.id, {
        proposal_id: proposalId,
        partition,
      });
      setMessage(
        "Proposal version added with leakage protection. Assign at least two blind reviewers.",
      );
      setProposalId("");
      await load(selectedStudy.id);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setWorking(false);
    }
  };

  const assignReviewer = async () => {
    if (!caseForReviewer || !reviewerEmail.trim()) return;
    setWorking(true);
    setMessage("");
    try {
      const response = await api.assignShadowReviewer(
        caseForReviewer,
        reviewerEmail.trim(),
        reviewerRole,
      );
      setMessage(response.message);
      setReviewerEmail("");
      await load(selectedStudy?.id);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setWorking(false);
    }
  };

  const excludeCase = async (caseId: string) => {
    const reason = window.prompt(
      "Protocol-defined exclusion reason (minimum 10 characters):",
    );
    if (!reason?.trim()) return;
    setWorking(true);
    setMessage("");
    try {
      await api.excludeValidationCase(caseId, reason.trim());
      setMessage("Validation case excluded with an auditable reason.");
      await load(selectedStudy?.id);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setWorking(false);
    }
  };

  const compute = async () => {
    if (!selectedStudy) return;
    setWorking(true);
    setMessage("");
    try {
      const response = await api.computeValidationMetrics(selectedStudy.id);
      setMessage(response.message);
      await load(selectedStudy.id);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setWorking(false);
    }
  };

  const exportDataset = async () => {
    if (!selectedStudy) return;
    setWorking(true);
    setMessage("");
    try {
      const blob = await api.downloadValidationDataset(selectedStudy.id, false);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `mulyankan-validation-${selectedStudy.id}.jsonl`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setMessage("Stable expert-labelled dataset manifest downloaded.");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setWorking(false);
    }
  };

  if (loading) {
    return (
      <div className="panel validation-loading">
        <Loader2 className="spin" /> Loading validation laboratory…
      </div>
    );
  }

  return (
    <div className="page-stack validation-lab">
      <section className="hero-panel validation-hero">
        <div>
          <span className="eyebrow">
            <FlaskConical size={15} /> Mulyankan 0.8
          </span>
          <h1>Expert-grounded validation and shadow pilot</h1>
          <p>
            Collect blind criterion-level expert labels, compare them with frozen
            model runs, and measure performance without influencing any proposal
            decision.
          </p>
        </div>
        <div className="validation-safety-card">
          <ShieldCheck />
          <strong>Shadow mode</strong>
          <span>Model outputs stay hidden from assigned experts.</span>
          <small>No pilot metric changes an official workflow outcome.</small>
        </div>
      </section>

      {message && <div className="alert info">{message}</div>}

      <section className="validation-grid">
        <div className="panel validation-create-panel">
          <div className="panel-heading">
            <div>
              <span>PROTOCOL</span>
              <h2>Create validation study</h2>
            </div>
            <Beaker size={20} />
          </div>
          <label>
            Study name
            <input
              value={studyName}
              onChange={(event) => setStudyName(event.target.value)}
            />
          </label>
          <div className="validation-form-grid">
            <label>
              Protocol version
              <input
                value={protocolVersion}
                onChange={(event) => setProtocolVersion(event.target.value)}
              />
            </label>
            <label>
              Annotation rulebook
              <input
                value={rulebookVersion}
                onChange={(event) => setRulebookVersion(event.target.value)}
              />
            </label>
            <label>
              Minimum blind reviewers
              <input
                type="number"
                min="2"
                max="10"
                value={minimumReviewers}
                onChange={(event) =>
                  setMinimumReviewers(Number(event.target.value))
                }
              />
            </label>
          </div>
          <button
            type="button"
            className="primary-button compact"
            onClick={() => void createStudy()}
            disabled={working}
          >
            {working ? <Loader2 className="spin" /> : <Plus />} Create study
          </button>
        </div>

        <div className="panel validation-study-panel">
          <div className="panel-heading">
            <div>
              <span>STUDIES</span>
              <h2>Controlled validation programme</h2>
            </div>
            <button type="button" onClick={() => void load(selectedId)}>
              <RefreshCw size={16} /> Refresh
            </button>
          </div>
          {studies.length ? (
            <select
              className="validation-study-select"
              value={selectedId}
              onChange={(event) => setSelectedId(event.target.value)}
            >
              {studies.map((study) => (
                <option key={study.id} value={study.id}>
                  {study.name} · {study.status}
                </option>
              ))}
            </select>
          ) : (
            <p>No validation studies have been created.</p>
          )}
          {selectedStudy && (
            <div className="validation-study-meta">
              <div>
                <strong>{selectedStudy.model_name}</strong>
                <span>Model {selectedStudy.model_version}</span>
              </div>
              <div>
                <strong>Rubric {selectedStudy.rubric_version}</strong>
                <span>{selectedStudy.scheme_code}</span>
              </div>
              <div>
                <strong>{selectedStudy.case_count}</strong>
                <span>cases</span>
              </div>
              <div>
                <strong>{selectedStudy.compared_case_count}</strong>
                <span>compared</span>
              </div>
            </div>
          )}
          {selectedStudy && (
            <div className="validation-actions">
              {selectedStudy.status === "draft" && (
                <button type="button" onClick={() => void updateStatus("active")}>
                  <Play size={16} /> Activate
                </button>
              )}
              {selectedStudy.status === "active" && (
                <button type="button" onClick={() => void updateStatus("frozen")}>
                  <Snowflake size={16} /> Freeze labels
                </button>
              )}
              {selectedStudy.status === "frozen" && (
                <button type="button" onClick={() => void updateStatus("completed")}>
                  <CheckCircle2 size={16} /> Complete
                </button>
              )}
              {selectedStudy.status !== "archived" && (
                <button type="button" onClick={() => void updateStatus("archived")}>
                  <Archive size={16} /> Archive
                </button>
              )}
              <button type="button" onClick={() => void compute()}>
                <Activity size={16} /> Compute observations
              </button>
              <button
                type="button"
                onClick={() => void exportDataset()}
                disabled={!['frozen', 'completed', 'archived'].includes(selectedStudy.status)}
              >
                <Download size={16} /> Export JSONL
              </button>
            </div>
          )}
        </div>
      </section>

      {selectedStudy && (
        <section className="validation-grid">
          <div className="panel">
            <div className="panel-heading">
              <div>
                <span>CASE INCLUSION</span>
                <h2>Add frozen model run</h2>
              </div>
              <Database size={20} />
            </div>
            <label>
              Proposal
              <select
                value={proposalId}
                onChange={(event) => setProposalId(event.target.value)}
              >
                <option value="">Select a proposal</option>
                {submissions.map((submission) => (
                  <option key={submission.id} value={submission.id}>
                    {submission.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Partition
              <select
                value={partition}
                onChange={(event) => setPartition(event.target.value)}
              >
                <option value="shadow">Shadow pilot</option>
                <option value="development">Development</option>
                <option value="internal_test">Internal test</option>
                <option value="external_test">External test</option>
              </select>
            </label>
            <button
              type="button"
              onClick={() => void addCase()}
              disabled={working || !proposalId || !["draft", "active"].includes(selectedStudy.status)}
            >
              <Plus size={16} /> Add case
            </button>
          </div>

          <div className="panel">
            <div className="panel-heading">
              <div>
                <span>BLIND REVIEW</span>
                <h2>Assign expert</h2>
              </div>
              <Users size={20} />
            </div>
            <label>
              Validation case
              <select
                value={caseForReviewer}
                onChange={(event) => setCaseForReviewer(event.target.value)}
              >
                <option value="">Select a case</option>
                {cases
                  .filter((item) => item.status !== "excluded")
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.proposal_title} · {item.completed_reviews}/
                      {item.minimum_reviews_required}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Reviewer email
              <input
                type="email"
                value={reviewerEmail}
                onChange={(event) => setReviewerEmail(event.target.value)}
                placeholder="expert@organisation.gov.in"
              />
            </label>
            <label>
              Reviewer role
              <select
                value={reviewerRole}
                onChange={(event) =>
                  setReviewerRole(event.target.value as "technical" | "financial")
                }
              >
                <option value="technical">Technical reviewer</option>
                <option value="financial">Financial reviewer</option>
              </select>
            </label>
            <button
              type="button"
              onClick={() => void assignReviewer()}
              disabled={working || selectedStudy.status !== "active"}
            >
              <Users size={16} /> Create blind assignment
            </button>
          </div>
        </section>
      )}

      {summary && (
        <section className="panel validation-readiness">
          <div className="panel-heading">
            <div>
              <span>READINESS</span>
              <h2>Validation evidence status</h2>
            </div>
            <ShieldCheck size={20} />
          </div>
          <div className="validation-stat-grid">
            <div><strong>{summary.readiness.total_cases}</strong><span>cases</span></div>
            <div><strong>{summary.readiness.compared_cases}</strong><span>compared</span></div>
            <div><strong>{summary.readiness.completed_reviews}</strong><span>expert reviews</span></div>
            <div><strong>No</strong><span>scientific validation claim</span></div>
          </div>
          {summary.readiness.warnings.length > 0 && (
            <ul className="validation-warning-list">
              {summary.readiness.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          {allMetrics.length > 0 && (
            <div className="validation-metric-grid">
              {allMetrics
                .filter((metric) =>
                  [
                    "cases_compared",
                    "model_release_rate",
                    "total_score_mae",
                    "total_score_rmse",
                    "spearman_rank_correlation",
                    "expert_pairwise_mae",
                  ].includes(metric.name),
                )
                .map((metric) => (
                  <div key={metric.name}>
                    <span>{metric.name.split("_").join(" ")}</span>
                    <strong>{formatMetric(metric.value, metric.name)}</strong>
                    <small>n={metric.sample_size}</small>
                  </div>
                ))}
            </div>
          )}
        </section>
      )}

      {selectedStudy && cases.length > 0 && (
        <section className="panel validation-case-table">
          <div className="panel-heading">
            <div>
              <span>CASES</span>
              <h2>Shadow comparison register</h2>
            </div>
          </div>
          <div className="validation-case-head">
            <span>Proposal</span><span>Partition</span><span>Reviews</span><span>Status / action</span>
          </div>
          {cases.map((item) => (
            <div className="validation-case-row" key={item.id}>
              <div><strong>{item.proposal_title}</strong><small>Version {item.proposal_version_number}</small></div>
              <span>{item.partition.split("_").join(" ")}</span>
              <span>{item.completed_reviews}/{item.minimum_reviews_required}</span>
              <div className="validation-case-action">
                <b>{item.status.split("_").join(" ")}</b>
                {item.status !== "excluded" &&
                  item.status !== "compared" &&
                  ["draft", "active"].includes(selectedStudy.status) && (
                    <button
                      type="button"
                      onClick={() => void excludeCase(item.id)}
                      disabled={working}
                      title="Exclude with an auditable protocol reason"
                    >
                      <XCircle size={14} /> Exclude
                    </button>
                  )}
              </div>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
