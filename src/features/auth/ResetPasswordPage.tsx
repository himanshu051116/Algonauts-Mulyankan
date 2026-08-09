import { FormEvent, useId, useState } from "react";
import { Eye, EyeOff, KeyRound, Loader2, ShieldCheck } from "lucide-react";
import { BrandMark } from "../../components/shared/BrandMark";
import { supabase } from "../../lib/supabase";

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  if (
    error &&
    typeof error === "object" &&
    "message" in error &&
    typeof error.message === "string"
  )
    return error.message;
  return "Unable to update the password.";
}

export function ResetPasswordPage() {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const passwordId = useId();
  const confirmationId = useId();
  const statusId = useId();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (password !== confirmation) {
      setError("The passwords do not match.");
      return;
    }
    if (password.length < 6) {
      setError("Use a password with at least 6 characters.");
      return;
    }

    setLoading(true);
    try {
      const { error: updateError } = await supabase.auth.updateUser({ password });
      if (updateError) throw updateError;

      // Return to a fresh sign-in state after the credential change. Replacing
      // the history entry prevents the recovery URL from being revisited.
      window.history.replaceState({}, document.title, "/");
      await supabase.auth.signOut({ scope: "local" });
      window.location.replace("/");
    } catch (updateError) {
      setError(errorMessage(updateError));
      setLoading(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-story" aria-label="Password recovery">
        <div className="auth-story-inner">
          <BrandMark />
          <div className="eyebrow">
            <ShieldCheck size={15} /> Secure account recovery
          </div>
          <h1>Choose a new password.</h1>
          <p>
            This page is available only after Supabase validates the recovery
            link. The link cannot be used to access the Mulyankan workspace
            without completing authentication.
          </p>
          <div className="auth-quote">
            <KeyRound size={24} />
            <p>
              After the password is updated, the recovery session is signed out
              and you must sign in again with the new password.
            </p>
          </div>
        </div>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <div className="mobile-brand">
            <BrandMark />
          </div>
          <span className="step-label">PASSWORD RESET</span>
          <h2>Set a new password</h2>
          <p>Enter the new password twice to confirm it.</p>
          <form onSubmit={submit}>
            <div className="form-field">
              <label htmlFor={passwordId}>New password</label>
              <span className="password-field">
                <input
                  id={passwordId}
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  minLength={6}
                  autoComplete="new-password"
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
            <label htmlFor={confirmationId}>
              Confirm new password
              <input
                id={confirmationId}
                type={showPassword ? "text" : "password"}
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                minLength={6}
                autoComplete="new-password"
                required
                aria-describedby={statusId}
              />
            </label>
            <div id={statusId} className="auth-status" aria-live="polite">
              {error && <div className="alert error">{error}</div>}
            </div>
            <button className="primary-button" disabled={loading} type="submit">
              {loading ? <Loader2 className="spin" size={18} /> : <KeyRound size={18} />}
              Update password
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}

export function InvalidPasswordRecoveryLink() {
  const returnToSignIn = () => {
    window.history.replaceState({}, document.title, "/");
    window.location.replace("/");
  };

  return (
    <main className="system-state-page">
      <section className="system-state-card" role="alert">
        <BrandMark />
        <div className="system-state-icon danger">
          <KeyRound size={26} />
        </div>
        <span className="step-label">RECOVERY LINK UNAVAILABLE</span>
        <h1>The password-reset link is invalid or has expired.</h1>
        <p>
          Return to sign in and request a new reset link. For security, each
          recovery link is time-limited and should be used only once.
        </p>
        <button type="button" className="primary-button" onClick={returnToSignIn}>
          Return to sign in
        </button>
      </section>
    </main>
  );
}
