import { apiFetch } from "./client";

export interface UserResponse {
  id: string; email: string; role: string; full_name?: string | null;
  organisation?: string | null; is_active: boolean; is_verified: boolean;
  approval_status?: string | null; created_at: string;
}

export interface UserListResponse {
  total: number; skip: number; limit: number; users: UserResponse[];
}

export interface UserMeResponse {
  id: string; email: string; role: string; is_active: boolean;
  is_verified: boolean; approval_status?: string | null;
  full_name?: string | null; organisation?: string | null;
}

export async function getCurrentUser(): Promise<UserMeResponse> {
  return apiFetch<UserMeResponse>("/admin/users/me");
}

export async function listUsers(skip = 0, limit = 50): Promise<UserListResponse> {
  return apiFetch<UserListResponse>(`/admin/users?skip=${skip}&limit=${limit}`);
}

export async function approveUser(userId: string): Promise<{ user_id: string; status: string }> {
  return apiFetch<{ user_id: string; status: string }>(`/admin/users/${userId}/approve`, { method: "POST" });
}

export async function assignRole(userId: string, role: string, reason: string): Promise<{ user_id: string; role: string; status: string }> {
  return apiFetch<{ user_id: string; role: string; status: string }>(`/admin/users/${userId}/roles`, {
    method: "POST", body: JSON.stringify({ role, reason }),
  });
}

export async function suspendUser(userId: string): Promise<{ user_id: string; status: string }> {
  return apiFetch<{ user_id: string; status: string }>(`/admin/users/${userId}/suspend`, { method: "POST" });
}

export async function reactivateUser(userId: string): Promise<{ user_id: string; status: string }> {
  return apiFetch<{ user_id: string; status: string }>(`/admin/users/${userId}/reactivate`, { method: "POST" });
}
