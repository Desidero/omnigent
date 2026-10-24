import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { isChunkLoadError } from "@/lib/chunkLoadRecovery";
import { copyText } from "@/lib/clipboard";

interface Props {
  children: ReactNode;
  name: string;
  resetKey?: string;
}

interface State {
  failed: boolean;
  resetKey?: string;
  error?: unknown;
  componentStack?: string;
}

/** Contains render failures without remounting healthy content on navigation. */
export class RenderErrorBoundary extends Component<Props, State> {
  override state: State = { failed: false, resetKey: this.props.resetKey };

  static getDerivedStateFromProps(props: Props, state: State) {
    return props.resetKey !== state.resetKey ? { failed: false, resetKey: props.resetKey } : null;
  }

  static getDerivedStateFromError(error: unknown) {
    // Let the app's chunk boundary keep its guarded reload recovery.
    if (isChunkLoadError(error)) throw error;
    return { failed: true, error, componentStack: undefined };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Rendering ${this.props.name} failed`, error, info.componentStack);
    this.setState({ componentStack: info.componentStack ?? undefined });
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    // What a bug report needs: the error, where React was rendering, and the page.
    const details = [
      describeError(this.state.error),
      this.state.componentStack ? `Component stack:${this.state.componentStack}` : "",
      `Path: ${location.pathname}`,
    ]
      .filter(Boolean)
      .join("\n\n");
    return (
      <div
        role="alert"
        className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-6 text-center"
      >
        <p className="text-sm text-muted-foreground">Unable to display {this.props.name}.</p>
        <div className="flex flex-wrap justify-center gap-2">
          <Button type="button" variant="outline" onClick={() => this.setState({ failed: false })}>
            Try again
          </Button>
          <Button type="button" variant="outline" onClick={() => location.reload()}>
            Reload
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => void copyText(details).catch(() => {})}
          >
            Copy details
          </Button>
        </div>
        <pre className="max-h-60 w-full max-w-3xl overflow-auto rounded-md bg-muted p-3 text-left font-mono text-xs whitespace-pre-wrap select-text">
          {details}
        </pre>
      </div>
    );
  }
}

function describeError(error: unknown): string {
  if (error instanceof Error) return error.stack ?? `${error.name}: ${error.message}`;
  try {
    return String(error);
  } catch {
    // Objects without a prototype have no toString; the fallback must not throw.
    return "Unknown error";
  }
}
