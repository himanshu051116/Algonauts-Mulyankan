import { FormEvent, useId, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  getAuthRedirectUrl,
  getPasswordRecoveryRedirectUrl,
  supabase,
} from "../../lib/supabase";
import { BrandMark } from "../../components/shared/BrandMark";

type AuthMode = "signin" | "signup" | "forgot";

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

export function Auth({ callbackFailed = false }: { callbackFailed?: boolean }) {
  const [mode, setMode] = useState<AuthMode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(
    callbackFailed ? "The confirmation link is invalid or has expired." : "",
  );
  const emailId = useId();
  const passwordId = useId();
  const statusId = useId();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const normalizedEmail = email.trim();
      if (mode === "signin") {
        const { error: authError } = await supabase.auth.signInWithPassword({
          email: normalizedEmail,
          password,
        });
        if (authError) throw authError;
      } else if (mode === "signup") {
        const { error: authError } = await supabase.auth.signUp({
          email: normalizedEmail,
          password,
          options: { emailRedirectTo: getAuthRedirectUrl() },
        });
        if (authError) throw authError;
        setMessage(
          "Account created. Check your email for the confirmation link, then wait for administrator approval.",
        );
      } else {
        const { error: authError } = await supabase.auth.resetPasswordForEmail(
          normalizedEmail,
          { redirectTo: getPasswordRecoveryRedirectUrl() },
        );
        if (authError) throw authError;
        // Keep the response neutral so the page does not disclose whether an
        // address is registered.
        setMessage(
          "If an account exists for this email address, a password-reset link has been sent. Check your inbox and spam folder.",
        );
      }
    } catch (authError) {
      setError(errorMessage(authError));
    } finally {
      setLoading(false);
    }
  };

  const changeMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setError("");
    setMessage("");
    setPassword("");
    setShowPassword(false);
  };

  const title =
    mode === "signin"
      ? "Sign in to Mulyankan"
      : mode === "signup"
        ? "Register for Mulyankan"
        : "Reset your password";
  const description =
    mode === "signin"
      ? "Access proposals, advisory scores, and assigned review tasks."
      : mode === "signup"
        ? "New accounts require email verification and administrator approval."
        : "Enter your registered email address. We will send a secure link for choosing a new password.";

  return (
    <main className="auth-page">
      <section className="auth-story" aria-label="About Mulyankan">
        <div className="auth-story-inner">
          <BrandMark />
          <div className="eyebrow">
            <Sparkles size={15} /> Preliminary scrutiny platform
          </div>
          <h1>Standardised proposal review for coal R&amp;D.</h1>
          <p>
            Structured eligibility checks, evidence-based criteria preview,
            and a traceable human-review workflow in one secure workspace.
          </p>
          <div className="proof-grid" aria-label="Evaluation framework summary">
            <div>
              <strong>23</strong>
              <span>evaluation criteria</span>
            </div>
            <div>
              <strong>6</strong>
              <span>score categories</span>
            </div>
            <div>
              <strong>100</strong>
              <span>point framework</span>
            </div>
          </div>
          <div className="auth-quote">
            <ShieldCheck size={24} />
            <p>
              Preliminary screening is advisory. Authorised experts remain
              responsible for review, adjudication, and final decisions.
            </p>
          </div>
        </div>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <div className="mobile-brand">
            <BrandMark />
          </div>
          <span className="step-label">
            {mode === "signin"
              ? "WELCOME BACK"
              : mode === "signup"
                ? "CREATE ACCOUNT"
                : "ACCOUNT RECOVERY"}
          </span>
          <h2>{title}</h2>
          <p>{description}</p>
          <form onSubmit={submit}>
            <label htmlFor={emailId}>
              Email address
              <input
                id={emailId}
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="name@organisation.gov.in"
                autoComplete="email"
                inputMode="email"
                spellCheck={false}
                required
                aria-describedby={statusId}
              />
            </label>
            {mode !== "forgot" && (
              <div className="form-field">
                <span className="field-label-row">
                  <label htmlFor={passwordId}>Password</label>
                  {mode === "signin" && (
                    <button
                      type="button"
                      className="inline-text-button"
                      onClick={() => changeMode("forgot")}
                    >
                      Forgot password?
                    </button>
                  )}
                </span>
                <span className="password-field">
                  <input
                    id={passwordId}
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="Minimum 6 characters"
                    minLength={6}
                    autoComplete={mode === "signin" ? "current-password" : "new-password"}
                    required
                    aria-describedby={statusId}
                  />
                  <button
                    type="button"
                    className="password-toggle"
                    onClick={() => setShowPassword((visible) => !visible)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    title={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </span>
              </div>
            )}
            <div id={statusId} className="auth-status" aria-live="polite">
              {error && <div className="alert error">{error}</div>}
              {message && <div className="alert success">{message}</div>}
            </div>
            <button className="primary-button" disabled={loading} type="submit">
              {loading ? (
                <Loader2 className="spin" size={18} />
              ) : mode === "forgot" ? (
                <KeyRound size={18} />
              ) : (
                <ArrowRight size={18} />
              )}
              {mode === "signin"
                ? "Sign in securely"
                : mode === "signup"
                  ? "Create account"
                  : "Send reset link"}
            </button>
          </form>
          {mode === "forgot" ? (
            <button
              className="text-button"
              type="button"
              onClick={() => changeMode("signin")}
            >
              <ArrowLeft size={16} /> Back to sign in
            </button>
          ) : (
            <button
              className="text-button"
              type="button"
              onClick={() => changeMode(mode === "signin" ? "signup" : "signin")}
            >
              {mode === "signin"
                ? "New to Mulyankan? Create an account"
                : "Already registered? Sign in"}
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
