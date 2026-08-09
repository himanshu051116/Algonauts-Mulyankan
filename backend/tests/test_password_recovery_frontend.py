from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_password_recovery_request_and_update_flow_are_wired() -> None:
    auth_page = (ROOT / "src/features/auth/AuthPage.tsx").read_text(encoding="utf-8")
    reset_page = (ROOT / "src/features/auth/ResetPasswordPage.tsx").read_text(
        encoding="utf-8"
    )
    supabase = (ROOT / "src/lib/supabase.ts").read_text(encoding="utf-8")
    app = (ROOT / "src/App.tsx").read_text(encoding="utf-8")

    assert "resetPasswordForEmail" in auth_page
    assert "getPasswordRecoveryRedirectUrl()" in auth_page
    assert 'new URL("/auth/reset-password"' in supabase
    assert "supabase.auth.updateUser({ password })" in reset_page
    assert 'supabase.auth.signOut({ scope: "local" })' in reset_page
    assert 'pathname === "/auth/reset-password"' in app
    assert 'event === "PASSWORD_RECOVERY"' in app
    assert '"/auth/reset-password"' in app


def test_password_recovery_does_not_disclose_account_existence() -> None:
    auth_page = (ROOT / "src/features/auth/AuthPage.tsx").read_text(encoding="utf-8")
    assert "If an account exists for this email address" in auth_page


def test_release_example_uses_version_specific_compose_namespace() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "COMPOSE_PROJECT_NAME=mulyankan-080" in env_example
    assert "COMPOSE_PROJECT_NAME=mulyankan-061" not in env_example
