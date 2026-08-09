import { useEffect, useRef, useState } from "react";
import {
  ClipboardCheck,
  EyeOff,
  FlaskConical,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  RefreshCw,
  ShieldCheck,
  UsersRound,
  X,
} from "lucide-react";
import type { Session } from "@supabase/supabase-js";
import type { View } from "../../types";
import { BrandMark } from "../shared/BrandMark";
import { supabase } from "../../lib/supabase";

function NavButton({
  active,
  onClick,
  icon,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count?: number;
}) {
  return (
    <button
      type="button"
      className={`nav-button ${active ? "active" : ""}`}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
    >
      {icon}
      <span>{label}</span>
      {count != null && <b aria-label={`${count} proposals`}>{count}</b>}
    </button>
  );
}

function humaniseRole(role: string) {
  return role
    .split("_").join(" ")
    .replace(/\b\w/g, (character: string) => character.toUpperCase());
}

export function WorkspaceShell({
  session,
  userRole,
  view,
  submissionCount,
  refreshing,
  lastUpdated,
  onRefresh,
  onNavigate,
  children,
}: {
  session: Session;
  userRole: string;
  view: View;
  submissionCount: number;
  refreshing: boolean;
  lastUpdated: Date | null;
  onRefresh: () => void;
  onNavigate: (view: View) => void;
  children: React.ReactNode;
}) {
  const [mobileNav, setMobileNav] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const navigate = (next: View) => {
    onNavigate(next);
    setMobileNav(false);
  };

  useEffect(() => {
    if (!mobileNav) return;
    const previousOverflow = document.body.style.overflow;
    const menuButton = menuButtonRef.current;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNav(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
      menuButton?.focus();
    };
  }, [mobileNav]);

  const viewTitle =
    view === "overview"
      ? "Overview"
      : view === "submit"
        ? "New proposal scrutiny"
        : view === "history"
          ? "Submission history"
          : view === "validation"
            ? "Expert validation laboratory"
            : view === "shadow-review"
              ? "Blind shadow review"
              : "User management";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace-main">
        Skip to main content
      </a>
      <aside
        className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}
        aria-label="Primary navigation"
      >
        <div className="sidebar-top">
          <BrandMark compact />
          <button
            ref={closeButtonRef}
            type="button"
            className="mobile-close"
            onClick={() => setMobileNav(false)}
            aria-label="Close navigation"
          >
            <X size={20} />
          </button>
        </div>
        <nav>
          <span className="nav-label">WORKSPACE</span>
          <NavButton
            active={view === "overview"}
            onClick={() => navigate("overview")}
            icon={<LayoutDashboard size={19} />}
            label="Overview"
          />
          <NavButton
            active={view === "submit"}
            onClick={() => navigate("submit")}
            icon={<ClipboardCheck size={19} />}
            label="New preliminary scrutiny"
          />
          <NavButton
            active={view === "history"}
            onClick={() => navigate("history")}
            icon={<History size={19} />}
            label="Submission history"
            count={submissionCount}
          />
          {["technical_reviewer", "financial_reviewer"].includes(userRole) && (
            <NavButton
              active={view === "shadow-review"}
              onClick={() => navigate("shadow-review")}
              icon={<EyeOff size={19} />}
              label="Shadow review desk"
            />
          )}
          {[
            "administrator",
            "ml_engineer",
            "scrutiny_officer",
            "auditor",
            "senior_adjudicator",
            "committee_secretariat",
          ].includes(userRole) && (
            <NavButton
              active={view === "validation"}
              onClick={() => navigate("validation")}
              icon={<FlaskConical size={19} />}
              label="Validation laboratory"
            />
          )}
          {["administrator", "auditor"].includes(userRole) && (
            <>
              <span className="nav-label admin-nav-label">ADMINISTRATION</span>
              <NavButton
                active={view === "users"}
                onClick={() => navigate("users")}
                icon={<UsersRound size={19} />}
                label="User management"
              />
            </>
          )}
        </nav>
        <div className="sidebar-insight">
          <ShieldCheck size={18} />
          <strong>Advisory prototype</strong>
          <p>
            Brochure-aligned trained NLP and deterministic screening support human
            review. It does not make an automatic funding decision.
          </p>
        </div>
        <div className="sidebar-user">
          <div className="avatar" aria-hidden="true">
            {session.user.email?.slice(0, 2).toUpperCase() || "MU"}
          </div>
          <div>
            <strong>{session.user.email?.split("@")[0] || "Mulyankan user"}</strong>
            <span>{humaniseRole(userRole)}</span>
          </div>
          <button
            type="button"
            onClick={() => void supabase.auth.signOut()}
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut size={18} />
          </button>
        </div>
      </aside>
      {mobileNav && (
        <button
          type="button"
          className="nav-scrim"
          onClick={() => setMobileNav(false)}
          aria-label="Close navigation"
        />
      )}
      <main className="workspace" id="workspace-main" tabIndex={-1}>
        <header className="topbar">
          <button
            ref={menuButtonRef}
            type="button"
            className="menu-button"
            onClick={() => setMobileNav(true)}
            aria-label="Open navigation"
            aria-expanded={mobileNav}
          >
            <Menu size={22} />
          </button>
          <div className="topbar-title">
            <span>
              {view === "overview"
                ? "Dashboard"
                : view === "submit"
                  ? "Scrutiny"
                  : view === "history"
                    ? "Records"
                    : view === "validation"
                      ? "Model validation"
                      : view === "shadow-review"
                        ? "Expert annotation"
                        : "Administration"}
            </span>
            <strong>{viewTitle}</strong>
          </div>
          <div className="topbar-actions">
            {view !== "users" && (
              <button
                type="button"
                className="refresh-button"
                onClick={onRefresh}
                disabled={refreshing}
                aria-label="Refresh workspace data"
                title={lastUpdated ? `Last updated ${lastUpdated.toLocaleTimeString()}` : "Refresh workspace"}
              >
                <RefreshCw className={refreshing ? "spin" : ""} size={17} />
                <span>{refreshing ? "Refreshing" : "Refresh"}</span>
              </button>
            )}
            {!["submit", "users", "validation", "shadow-review"].includes(view) && (
              <button
                type="button"
                className="top-action"
                onClick={() => navigate("submit")}
              >
                <ClipboardCheck size={17} /> Scrutinise proposal
              </button>
            )}
          </div>
        </header>
        <div className="workspace-content">{children}</div>
      </main>
    </div>
  );
}
