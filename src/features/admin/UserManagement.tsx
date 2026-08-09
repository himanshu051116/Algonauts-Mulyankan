import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  CircleUserRound,
  Loader2,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  UserCog,
  UserRoundCheck,
  UserRoundX,
  X,
} from "lucide-react";
import * as api from "../../lib/api";

const ROLE_OPTIONS = [
  { value: "applicant", label: "Applicant" },
  { value: "technical_reviewer", label: "Technical reviewer" },
  { value: "financial_reviewer", label: "Financial reviewer" },
  { value: "scrutiny_officer", label: "Scrutiny officer" },
  { value: "senior_adjudicator", label: "Senior adjudicator" },
  { value: "committee_secretariat", label: "Committee secretariat" },
  { value: "ml_engineer", label: "ML engineer" },
  { value: "auditor", label: "Auditor" },
  { value: "administrator", label: "Administrator" },
] as const;

type UserFilter = "all" | "pending" | "active" | "suspended";
type ActionKind = "approve" | "suspend" | "reactivate" | "role";

function displayName(user: api.UserResponse) {
  return user.full_name?.trim() || user.email.split("@")[0] || "Unnamed user";
}

function humaniseRole(role: string) {
  return role
    .split("_")
    .join(" ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function accountState(user: api.UserResponse): Exclude<UserFilter, "all"> {
  if (user.is_active) return "active";
  const approval = (user.approval_status ?? "").toLowerCase();
  if (approval.includes("suspend") || approval.includes("inactive")) {
    return "suspended";
  }
  return "pending";
}

function formatDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Unknown";
  return parsed.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return "The user-management request failed.";
}

function StateBadge({ user }: { user: api.UserResponse }) {
  const state = accountState(user);
  const label = state === "active" ? "Active" : state === "suspended" ? "Suspended" : "Pending approval";
  return <span className={`user-state-badge ${state}`}>{label}</span>;
}

export function UserManagement({
  currentUserId,
  userRole,
}: {
  currentUserId: string;
  userRole: string;
}) {
  const canManage = userRole === "administrator";
  const [users, setUsers] = useState<api.UserResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<UserFilter>("pending");
  const [busy, setBusy] = useState<Record<string, ActionKind | undefined>>({});
  const [roleEditor, setRoleEditor] = useState<string | null>(null);
  const [roleDraft, setRoleDraft] = useState<Record<string, string>>({});
  const [reasonDraft, setReasonDraft] = useState<Record<string, string>>({});

  const loadUsers = useCallback(async (background = false) => {
    if (background) setRefreshing(true);
    else setLoading(true);
    setError("");
    try {
      const response = await api.listUsers(0, 200);
      setUsers(response.users);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const counts = useMemo(() => {
    const next = { all: users.length, pending: 0, active: 0, suspended: 0 };
    for (const user of users) next[accountState(user)] += 1;
    return next;
  }, [users]);

  const filteredUsers = useMemo(() => {
    const term = query.trim().toLowerCase();
    return users
      .filter((user) => filter === "all" || accountState(user) === filter)
      .filter((user) => {
        if (!term) return true;
        return [
          user.email,
          user.full_name ?? "",
          user.organisation ?? "",
          user.role,
          user.approval_status ?? "",
        ].some((value) => value.toLowerCase().includes(term));
      })
      .sort((a, b) => {
        const priority = { pending: 0, suspended: 1, active: 2 } as const;
        const stateDifference = priority[accountState(a)] - priority[accountState(b)];
        if (stateDifference !== 0) return stateDifference;
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      });
  }, [filter, query, users]);

  const beginAction = (userId: string, action: ActionKind) => {
    setBusy((current) => ({ ...current, [userId]: action }));
    setError("");
    setSuccess("");
  };

  const endAction = (userId: string) => {
    setBusy((current) => ({ ...current, [userId]: undefined }));
  };

  const runUserAction = async (
    user: api.UserResponse,
    action: Exclude<ActionKind, "role">,
  ) => {
    if (!canManage || busy[user.id]) return;
    const confirmation =
      action === "approve"
        ? `Approve ${user.email} and allow access to Mulyankan?`
        : action === "suspend"
          ? `Suspend ${user.email}? They will be unable to access the workspace.`
          : `Reactivate ${user.email}?`;
    if (!window.confirm(confirmation)) return;

    beginAction(user.id, action);
    try {
      if (action === "approve") await api.approveUser(user.id);
      if (action === "suspend") await api.suspendUser(user.id);
      if (action === "reactivate") await api.reactivateUser(user.id);
      setSuccess(
        action === "approve"
          ? `${user.email} was approved.`
          : action === "suspend"
            ? `${user.email} was suspended.`
            : `${user.email} was reactivated.`,
      );
      await loadUsers(true);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      endAction(user.id);
    }
  };

  const saveRole = async (user: api.UserResponse) => {
    if (!canManage || busy[user.id]) return;
    const nextRole = roleDraft[user.id] ?? user.role;
    const reason = (reasonDraft[user.id] ?? "").trim();
    if (nextRole === user.role) {
      setError("Choose a different role before saving.");
      return;
    }
    if (reason.length < 10) {
      setError("Enter a role-change reason of at least 10 characters.");
      return;
    }
    if (!window.confirm(`Change ${user.email} from ${humaniseRole(user.role)} to ${humaniseRole(nextRole)}?`)) {
      return;
    }

    beginAction(user.id, "role");
    try {
      await api.assignRole(user.id, nextRole, reason);
      setSuccess(`${user.email} was assigned the ${humaniseRole(nextRole)} role.`);
      setRoleEditor(null);
      setReasonDraft((current) => ({ ...current, [user.id]: "" }));
      await loadUsers(true);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      endAction(user.id);
    }
  };

  if (loading) {
    return (
      <section className="admin-users-page">
        <div className="loading-panel">
          <Loader2 className="spin" size={24} />
          <p>Loading registered users…</p>
        </div>
      </section>
    );
  }

  return (
    <section className="admin-users-page">
      <div className="admin-page-heading">
        <div>
          <span className="step-label">ADMINISTRATION</span>
          <h1>User management</h1>
          <p>
            Review registrations, approve access, manage account status, and assign operational roles.
          </p>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => void loadUsers(true)}
          disabled={refreshing}
        >
          <RefreshCw className={refreshing ? "spin" : ""} size={17} />
          {refreshing ? "Refreshing" : "Refresh users"}
        </button>
      </div>

      {!canManage && (
        <div className="admin-readonly-note">
          <ShieldAlert size={18} />
          <div>
            <strong>Read-only access</strong>
            <span>Auditors can inspect accounts but only administrators can change them.</span>
          </div>
        </div>
      )}

      {error && (
        <div className="alert error admin-feedback" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => setError("")} aria-label="Dismiss error">
            <X size={16} />
          </button>
        </div>
      )}
      {success && (
        <div className="alert success admin-feedback" role="status">
          <span>{success}</span>
          <button type="button" onClick={() => setSuccess("")} aria-label="Dismiss success">
            <X size={16} />
          </button>
        </div>
      )}

      <div className="admin-stat-grid">
        <button type="button" className={filter === "pending" ? "active" : ""} onClick={() => setFilter("pending")}>
          <UserRoundCheck size={19} />
          <span>Pending</span>
          <strong>{counts.pending}</strong>
        </button>
        <button type="button" className={filter === "active" ? "active" : ""} onClick={() => setFilter("active")}>
          <UserCheck size={19} />
          <span>Active</span>
          <strong>{counts.active}</strong>
        </button>
        <button type="button" className={filter === "suspended" ? "active" : ""} onClick={() => setFilter("suspended")}>
          <UserRoundX size={19} />
          <span>Suspended</span>
          <strong>{counts.suspended}</strong>
        </button>
        <button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>
          <CircleUserRound size={19} />
          <span>All users</span>
          <strong>{counts.all}</strong>
        </button>
      </div>

      <div className="admin-users-panel panel">
        <div className="admin-user-tools">
          <label className="admin-user-search">
            <Search size={17} />
            <span className="sr-only">Search users</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by name, email, organisation, or role"
            />
            {query && (
              <button type="button" onClick={() => setQuery("")} aria-label="Clear user search">
                <X size={15} />
              </button>
            )}
          </label>
          <label className="admin-filter-select">
            <span className="sr-only">Filter users</span>
            <select value={filter} onChange={(event) => setFilter(event.target.value as UserFilter)}>
              <option value="pending">Pending approval</option>
              <option value="active">Active</option>
              <option value="suspended">Suspended</option>
              <option value="all">All users</option>
            </select>
            <ChevronDown size={15} />
          </label>
          <span className="admin-result-count">{filteredUsers.length} shown</span>
        </div>

        {filteredUsers.length === 0 ? (
          <div className="admin-empty-state">
            <ShieldCheck size={28} />
            <h2>No matching users</h2>
            <p>Change the status filter or search term.</p>
          </div>
        ) : (
          <div className="admin-user-list">
            {filteredUsers.map((user) => {
              const state = accountState(user);
              const action = busy[user.id];
              const isSelf = user.id === currentUserId;
              const editorOpen = roleEditor === user.id;
              return (
                <article className="admin-user-card" key={user.id}>
                  <div className="admin-user-avatar" aria-hidden="true">
                    {displayName(user).slice(0, 2).toUpperCase()}
                  </div>
                  <div className="admin-user-identity">
                    <div className="admin-user-title-line">
                      <h2>{displayName(user)}</h2>
                      {isSelf && <span className="self-badge">You</span>}
                    </div>
                    <a href={`mailto:${user.email}`}>{user.email}</a>
                    <div className="admin-user-meta">
                      <span>{user.organisation || "Organisation not provided"}</span>
                      <span>Registered {formatDate(user.created_at)}</span>
                    </div>
                  </div>
                  <div className="admin-user-role">
                    <span>Role</span>
                    <strong>{humaniseRole(user.role)}</strong>
                  </div>
                  <div className="admin-user-status">
                    <StateBadge user={user} />
                    <span className={user.is_verified ? "verified" : "unverified"}>
                      {user.is_verified ? <CheckCircle2 size={13} /> : <ShieldAlert size={13} />}
                      {user.is_verified ? "Email verified" : "Email unverified"}
                    </span>
                  </div>
                  {canManage && (
                    <div className="admin-user-actions">
                      {state === "pending" && (
                        <button
                          type="button"
                          className="admin-action approve"
                          disabled={Boolean(action)}
                          onClick={() => void runUserAction(user, "approve")}
                        >
                          {action === "approve" ? <Loader2 className="spin" size={16} /> : <UserCheck size={16} />}
                          Approve
                        </button>
                      )}
                      {state === "active" && !isSelf && (
                        <button
                          type="button"
                          className="admin-action danger"
                          disabled={Boolean(action)}
                          onClick={() => void runUserAction(user, "suspend")}
                        >
                          {action === "suspend" ? <Loader2 className="spin" size={16} /> : <UserRoundX size={16} />}
                          Suspend
                        </button>
                      )}
                      {state === "suspended" && (
                        <button
                          type="button"
                          className="admin-action reactivate"
                          disabled={Boolean(action)}
                          onClick={() => void runUserAction(user, "reactivate")}
                        >
                          {action === "reactivate" ? <Loader2 className="spin" size={16} /> : <UserRoundCheck size={16} />}
                          Reactivate
                        </button>
                      )}
                      <button
                        type="button"
                        className="admin-action neutral"
                        disabled={Boolean(action) || isSelf}
                        title={isSelf ? "Your own role cannot be changed here." : "Change role"}
                        onClick={() => {
                          setRoleEditor(editorOpen ? null : user.id);
                          setRoleDraft((current) => ({ ...current, [user.id]: current[user.id] ?? user.role }));
                          setError("");
                        }}
                      >
                        <UserCog size={16} />
                        Role
                      </button>
                    </div>
                  )}

                  {canManage && editorOpen && !isSelf && (
                    <div className="admin-role-editor">
                      <div className="role-editor-heading">
                        <div>
                          <span>ROLE ASSIGNMENT</span>
                          <strong>Change access responsibilities</strong>
                        </div>
                        <button type="button" onClick={() => setRoleEditor(null)} aria-label="Close role editor">
                          <X size={16} />
                        </button>
                      </div>
                      <label>
                        New role
                        <select
                          value={roleDraft[user.id] ?? user.role}
                          onChange={(event) => setRoleDraft((current) => ({ ...current, [user.id]: event.target.value }))}
                        >
                          {ROLE_OPTIONS.map((role) => (
                            <option value={role.value} key={role.value}>{role.label}</option>
                          ))}
                        </select>
                      </label>
                      <label className="role-reason-field">
                        Reason for change
                        <textarea
                          value={reasonDraft[user.id] ?? ""}
                          onChange={(event) => setReasonDraft((current) => ({ ...current, [user.id]: event.target.value }))}
                          placeholder="Explain why this access role is required. This reason is written to the audit trail."
                          rows={3}
                        />
                        <small>{(reasonDraft[user.id] ?? "").trim().length}/10 minimum characters</small>
                      </label>
                      <button
                        type="button"
                        className="primary-button compact"
                        disabled={Boolean(action)}
                        onClick={() => void saveRole(user)}
                      >
                        {action === "role" ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
                        Save role
                      </button>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
