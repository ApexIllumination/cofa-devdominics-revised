import * as React from "react";
import { getJson, HttpError } from "./api";

type Props<T> = {
  path: string; accountId: string; label: string; decode: (value: unknown) => T;
  onUnauthorized: () => void; children: (value: T) => React.ReactNode;
};
type State<T> = { kind: "idle" | "loading" | "error" } | { kind: "done"; value: T };

export function ReadPanel<T>(props: Props<T>) {
  // A different user or URL must never inherit the previous response.
  return <Panel key={JSON.stringify([props.accountId, props.path])} {...props} />;
}

function Panel<T>({ path, label, decode, onUnauthorized, children }: Props<T>) {
  const [state, set] = React.useState<State<T>>({ kind: "idle" });
  const active = React.useRef<AbortController | null>(null);
  React.useEffect(() => () => { active.current?.abort(); }, []);
  async function read() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    set({ kind: "loading" });
    try {
      const value = await getJson(path, decode, controller.signal);
      if (!controller.signal.aborted) set({ kind: "done", value });
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof HttpError && error.status === 401) {
        set({ kind: "idle" }); onUnauthorized();
      } else {
        set({ kind: "error" });
      }
    } finally { active.current = null; }
  }
  return <section>
    <button type="button" data-testid="read" disabled={state.kind === "loading"} onClick={read}>
      {state.kind === "loading" ? "조회 중…" : state.kind === "error" ? "다시 시도" : label}
    </button>
    <div role="status">{state.kind === "error" && "조회하지 못했습니다. 다시 시도해 주세요."}</div>
    {state.kind === "done" && <div data-testid="result">{children(state.value)}</div>}
  </section>;
}
