import { createClient } from "@supabase/supabase-js";

const configuredUrl = import.meta.env.VITE_SUPABASE_URL?.trim();
const configuredKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim();

export const supabaseConfigurationError =
  !configuredUrl || !configuredKey
    ? "VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY must be configured."
    : "";

// Keep module imports safe so a missing deployment variable produces a useful
// configuration screen instead of a blank page caused by an import-time throw.
const url = configuredUrl || "http://127.0.0.1:54321";
const key = configuredKey || "missing-publishable-key";

export const supabase = createClient(url, key, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

function getPublicAppUrl(): string {
  const configuredAppUrl = import.meta.env.VITE_PUBLIC_APP_URL?.trim();
  return configuredAppUrl || window.location.origin;
}

export function getAuthRedirectUrl(): string {
  return new URL("/auth/callback", getPublicAppUrl()).toString();
}

export function getPasswordRecoveryRedirectUrl(): string {
  return new URL("/auth/reset-password", getPublicAppUrl()).toString();
}
