import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { BrandMark } from "./BrandMark";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Mulyankan frontend error", error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <main className="system-state-page">
        <section className="system-state-card" role="alert">
          <BrandMark />
          <div className="system-state-icon danger">
            <AlertTriangle size={26} />
          </div>
          <span className="step-label">APPLICATION ERROR</span>
          <h1>The workspace could not be displayed.</h1>
          <p>
            The workspace could not finish loading. Reload the application. If
            the problem continues, contact the system administrator.
          </p>
          <button
            type="button"
            className="primary-button"
            onClick={() => window.location.reload()}
          >
            <RotateCcw size={18} /> Reload workspace
          </button>
        </section>
      </main>
    );
  }
}
