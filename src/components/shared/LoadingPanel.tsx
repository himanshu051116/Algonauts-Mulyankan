import { Loader2 } from "lucide-react";

export function LoadingPanel() {
  return (
    <div className="loading-panel" role="status" aria-live="polite">
      <Loader2 className="spin" aria-hidden="true" />
      <p>Loading your workspace…</p>
    </div>
  );
}
