import { supabase } from "../lib/supabase";

function resolveBackendUrl(): string {
  const configured = import.meta.env.VITE_API_URL;
  if (configured && configured.trim()) {
    return configured.trim().replace(/\/+$/, "");
  }
  if (import.meta.env.DEV) {
    return "http://localhost:8000";
  }
  return "";
}

const BACKEND_URL = resolveBackendUrl();
const API_PREFIX = `${BACKEND_URL}/api/v1`;

async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = await getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> ?? {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_PREFIX}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail ?? `HTTP ${res.status}`;
    throw new Error(`Request failed: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return res.json() as Promise<T>;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}


export async function apiDownload(path: string): Promise<Blob> {
  const token = await getAccessToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_PREFIX}${path}`, { headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail ?? `HTTP ${res.status}`;
    throw new Error(
      `Request failed: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`,
    );
  }
  return res.blob();
}
