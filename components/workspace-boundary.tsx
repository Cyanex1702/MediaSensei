"use client";
import { Component, type ReactNode } from "react";

export default class WorkspaceBoundary extends Component<{children: ReactNode}, {error: string | null}> {
  state: {error: string | null} = {error: null};
  static getDerivedStateFromError(error: unknown) {
    return {error: error instanceof Error ? error.message : String(error)};
  }
  render() {
    if (this.state.error) return <main className="mx-auto my-12 max-w-xl rounded-xl border bg-card p-8 space-y-4" role="alert">
      <h1 className="text-xl font-semibold">The workspace view could not load</h1>
      <p>Your imported files and saved work remain in the local workspace. Reload to reconnect. Check Jobs before submitting an operation again.</p>
      <button className="rounded-md bg-primary px-4 py-2 text-primary-foreground" onClick={() => window.location.reload()}>Reload workspace</button>
      <details><summary>Error details</summary><pre className="whitespace-pre-wrap break-words text-sm">{this.state.error}</pre></details>
    </main>;
    return this.props.children;
  }
}
