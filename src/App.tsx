import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { AlertTriangle, Loader2, RotateCcw, ShieldAlert, ShieldCheck } from "lucide-react";
import { supabase, supabaseConfigurationError } from "./lib/supabase";
import { BrandMark } from "./components/shared/BrandMark";
import { Auth } from "./features/auth/AuthPage";
import {
  InvalidPasswordRecoveryLink,
  ResetPasswordPage,
} from "./features/auth/ResetPasswordPage";
import { WorkspaceShell } from "./components/layout/WorkspaceShell";
import { Overview } from "./features/dashboard/Overview";
import { SubmissionStudio } from "./features/proposals/SubmissionStudio";
import { SubmissionHistory } from "./features/proposals/SubmissionHistory";
import { UserManagement } from "./features/admin/UserManagement";
import { ValidationLab } from "./features/validation/ValidationLab";
import { ShadowReviewDesk } from "./features/validation/ShadowReviewDesk";
import type {
  View,
  Submission,
  Evaluation,
  EvaluationReview,
  Status,
} from "./types";
import * as api from "./lib/api";
import { adaptEvaluation } from "./lib/evaluation-adapter";

const normalizeStatus = (status: string): Status => {
  if (status === "evaluated") return "completed";
  if (status === "revision_required") return "revision";
  if (["submitted", "queued", "draft"].includes(status)) return "pending";
  return [
    "approved",
    "revision",
    "rejected",
    "pending",
    "evaluating",
    "human_review",
    "adjudication",
    "committee_review",
    "withdrawn",
    "error",
    "completed",
  ].includes(status)
    ? (status as Status)
    : "pending";
};

function proposalToSubmission(p: api.ProposalResponse): Submission {
  return {
    id: p.id,
    owner_id: p.owner_id,
    title: p.title,
    description: p.executive_summary ?? null,
    document_id: p.document_id ?? null,
    document_file_name: p.document_file_name ?? null,
    status: p.status,
    scheme_id: p.scheme_id,
    current_version: p.current_version,
    submission_type: "server",
    created_at: p.created_at,
    updated_at: p.updated_at,
  };
}

function backendEvaluationToEvaluation(
  proposalId: string,
  evaluation: api.EvaluationResponse,
): Evaluation {
  const structured = adaptEvaluation(evaluation);
  return {
    id: evaluation.model_run_id ?? `${proposalId}-evaluation`,
    submission_id: proposalId,
    total_score: structured.totalScore,
    stream_total_score: structured.totalScore,
    stream_id: "coal-energy",
    combined_reasoning: structured.finalRecommendation,
    future_suggestions: structured.improvementSuggestions.join("\n"),
    evaluated_by: structured.engine,
    gpt_evaluation: structured,
  };
}

function apiReviewToReview(
  proposalId: string,
  review: api.ExpertReviewResponse,
): EvaluationReview {
  return {
    id: review.id,
    submission_id: proposalId,
    evaluation_id: review.assignment_id,
    reviewer_id: review.reviewer_id,
    proposal_version_number: review.proposal_version_number,
    expert_score: review.total_score ?? 0,
    recommendation:
      review.recommendation === "approved" ||
      review.recommendation === "rejected"
        ? review.recommendation
        : "revision",
    notes: review.notes ?? null,
    criterion_scores: Object.fromEntries(
      review.criterion_scores.map((criterion) => [
        criterion.criterion_key ?? criterion.criterion_id,
        criterion.score,
      ]),
    ),
    created_at: review.submitted_at ?? new Date(0).toISOString(),
  };
}

function ConfigurationError() {
  return (
    <main className="system-state-page">
      <section className="system-state-card" role="alert">
        <BrandMark />
        <div className="system-state-icon danger">
          <AlertTriangle size={26} />
        </div>
        <span className="step-label">CONFIGURATION REQUIRED</span>
        <h1>Mulyankan sign-in is not ready.</h1>
        <p>
          The secure sign-in service is not configured for this deployment.
          Contact the system administrator before using the workspace.
        </p>
        <button
          type="button"
          className="primary-button"
          onClick={() => window.location.reload()}
        >
          <RotateCcw size={18} /> Recheck configuration
        </button>
      </section>
    </main>
  );
}

function Splash() {
  return (
    <main className="splash">
      <BrandMark />
      <Loader2 className="spin" size={22} />
    </main>
  );
}

function PendingApproval() {
  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="auth-story-inner">
          <BrandMark />
          <div className="eyebrow">
            <ShieldAlert size={15} /> Account pending
          </div>
          <h1>Approval required</h1>
          <p>
            Your account has been created but requires administrator approval
            before you can access the platform.
          </p>
          <p>Please contact your system administrator.</p>
        </div>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <ShieldCheck size={40} />
          <h2>Account status</h2>
          <p className="alert info">
            Your registration is pending approval. You will be notified once an
            administrator activates your account.
          </p>
          <button
            className="text-button"
            onClick={() => void supabase.auth.signOut()}
          >
            Sign out
          </button>
        </div>
      </section>
    </main>
  );
}

function AccountStatusUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="auth-story-inner">
          <BrandMark />
          <div className="eyebrow">
            <ShieldAlert size={15} /> Account status unavailable
          </div>
          <h1>Unable to verify access</h1>
          <p>
            Mulyankan could not confirm your account status. The workspace
            remains locked until verification succeeds.
          </p>
        </div>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <ShieldAlert size={40} />
          <h2>Connection or account error</h2>
          <p className="alert error">
            Check your connection or contact the system administrator, then retry.
          </p>
          <button className="primary-button" onClick={onRetry}>
            Retry verification
          </button>
          <button
            className="text-button"
            onClick={() => void supabase.auth.signOut()}
          >
            Sign out
          </button>
        </div>
      </section>
    </main>
  );
}

function AuthCallback({ passwordRecovery = false }: { passwordRecovery?: boolean }) {
  return (
    <main className="splash auth-callback">
      <BrandMark />
      <div className="callback-status">
        <Loader2 className="spin" size={24} />
        <div>
          <strong>{passwordRecovery ? "Validating recovery link" : "Confirming your account"}</strong>
          <span>
            {passwordRecovery
              ? "The password form will open after the secure link is verified."
              : "You will be taken to the Mulyankan workspace."}
          </span>
        </div>
      </div>
    </main>
  );
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

function Workspace({ session }: { session: Session }) {
  const [userStatus, setUserStatus] = useState<
    api.UserMeResponse | null | "loading"
  >("loading");
  const [view, setView] = useState<View>("overview");
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [reviews, setReviews] = useState<EvaluationReview[]>([]);
  const [assignments, setAssignments] = useState<
    api.ReviewerAssignmentResponse[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [notice, setNotice] = useState("");
  const refreshInFlight = useRef(false);

  const loadUserStatus = useCallback(() => {
    setUserStatus("loading");
    api
      .getCurrentUser()
      .then(setUserStatus)
      .catch(() => setUserStatus(null));
  }, []);

  useEffect(() => {
    loadUserStatus();
  }, [loadUserStatus]);

  useEffect(() => {
    if (userStatus === "loading" || userStatus === null) return;
    const validationRoles = new Set([
      "administrator",
      "ml_engineer",
      "scrutiny_officer",
      "auditor",
      "senior_adjudicator",
      "committee_secretariat",
    ]);
    if (view === "users" && !["administrator", "auditor"].includes(userStatus.role)) {
      setView("overview");
    }
    if (view === "validation" && !validationRoles.has(userStatus.role)) {
      setView("overview");
    }
    if (
      view === "shadow-review" &&
      !["technical_reviewer", "financial_reviewer"].includes(userStatus.role)
    ) {
      setView("overview");
    }
  }, [userStatus, view]);

  const refresh = useCallback(async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    setRefreshing(true);
    setNotice("");
    try {
      const [proposalList, assignmentList] = await Promise.all([
        api.listProposals(),
        api.listReviewAssignments().catch(() => ({ assignments: [] })),
      ]);
      const nextSubmissions = proposalList.proposals.map(proposalToSubmission);
      const [evaluationResults, reviewResults] = await Promise.all([
        Promise.all(
          nextSubmissions.map(async (submission) => {
            try {
              return backendEvaluationToEvaluation(
                submission.id,
                await api.getEvaluation(submission.id),
              );
            } catch {
              return null;
            }
          }),
        ),
        Promise.all(
          nextSubmissions.map(async (submission) => {
            try {
              const response = await api.listProposalReviews(submission.id);
              return response.reviews.map((review) =>
                apiReviewToReview(submission.id, review),
              );
            } catch {
              return [];
            }
          }),
        ),
      ]);
      setSubmissions(nextSubmissions);
      setEvaluations(
        evaluationResults.filter(
          (evaluation): evaluation is Evaluation => evaluation !== null,
        ),
      );
      setReviews(reviewResults.flat());
      setAssignments(assignmentList.assignments);
      setLastUpdated(new Date());
    } catch (e) {
      setNotice(errorMessage(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
      refreshInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    if (
      userStatus === "loading" ||
      userStatus === null ||
      !userStatus.is_active
    ) {
      return;
    }
    void refresh();
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    const t = window.setInterval(refreshWhenVisible, 30000);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [refresh, userStatus]);

  const evaluationMap = useMemo(
    () => new Map(evaluations.map((e) => [e.submission_id, e])),
    [evaluations],
  );
  const reviewMap = useMemo(() => {
    const map = new Map<string, EvaluationReview[]>();
    for (const r of reviews)
      map.set(r.submission_id, [...(map.get(r.submission_id) ?? []), r]);
    return map;
  }, [reviews]);
  const effectiveStatus = useCallback((s: Submission): Status => {
    if (s.status === "evaluating") return "evaluating";
    return normalizeStatus(s.status);
  }, []);

  if (userStatus === "loading") return <Splash />;
  if (userStatus === null)
    return <AccountStatusUnavailable onRetry={loadUserStatus} />;
  if (!userStatus.is_active) return <PendingApproval />;

  return (
    <WorkspaceShell
      session={session}
      view={view}
      userRole={userStatus.role}
      submissionCount={submissions.length}
      refreshing={refreshing}
      lastUpdated={lastUpdated}
      onRefresh={() => void refresh()}
      onNavigate={setView}
    >
      {notice && (
        <div className="alert error workspace-alert" role="alert">
          <span>{notice}</span>
          <button type="button" onClick={() => void refresh()}>Retry</button>
        </div>
      )}
      {view === "overview" && (
        <Overview
          submissions={submissions}
          evaluations={evaluations}
          loading={loading}
          statusOf={effectiveStatus}
          onSubmit={() => setView("submit")}
          onHistory={() => setView("history")}
        />
      )}
      {view === "submit" && (
        <SubmissionStudio
          onComplete={async () => {
            await refresh();
            setView("history");
          }}
        />
      )}
      {view === "history" && (
        <SubmissionHistory
          userId={session.user.id}
          userRole={userStatus?.role ?? "applicant"}
          submissions={submissions}
          evaluationMap={evaluationMap}
          reviewMap={reviewMap}
          assignments={assignments}
          loading={loading}
          statusOf={effectiveStatus}
          onReviewSaved={refresh}
        />
      )}
      {view === "validation" && (
        <ValidationLab submissions={submissions} />
      )}
      {view === "shadow-review" && (
        <ShadowReviewDesk
          assignments={assignments}
          onReviewSaved={refresh}
        />
      )}
      {view === "users" && ["administrator", "auditor"].includes(userStatus.role) && (
        <UserManagement
          currentUserId={session.user.id}
          userRole={userStatus.role}
        />
      )}
    </WorkspaceShell>
  );
}

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const pathname = window.location.pathname;
  const isAuthCallback = pathname === "/auth/callback";
  const isPasswordRecovery = pathname === "/auth/reset-password";

  useEffect(() => {
    if (supabaseConfigurationError) {
      setCheckingSession(false);
      return;
    }

    let active = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setCheckingSession(false);
      if (data.session && window.location.pathname === "/auth/callback") {
        window.history.replaceState({}, document.title, "/");
      }
    });

    const { data } = supabase.auth.onAuthStateChange((event, nextSession) => {
      if (!active) return;
      setSession(nextSession);
      setCheckingSession(false);
      if (
        event === "PASSWORD_RECOVERY" &&
        window.location.pathname !== "/auth/reset-password"
      ) {
        window.history.replaceState({}, document.title, "/auth/reset-password");
      } else if (
        nextSession &&
        window.location.pathname === "/auth/callback"
      ) {
        window.history.replaceState({}, document.title, "/");
      }
    });

    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, []);

  if (supabaseConfigurationError) return <ConfigurationError />;
  if (checkingSession) {
    return isAuthCallback || isPasswordRecovery ? (
      <AuthCallback passwordRecovery={isPasswordRecovery} />
    ) : (
      <Splash />
    );
  }
  if (isPasswordRecovery) {
    return session ? <ResetPasswordPage /> : <InvalidPasswordRecoveryLink />;
  }
  return session ? (
    <Workspace session={session} />
  ) : (
    <Auth callbackFailed={isAuthCallback} />
  );
}

export default App;
