import * as React from "react";
import { createRoot } from "react-dom/client";
import { getJson, HttpError, postJson } from "../../web-request/api";
import { ReadPanel } from "../../web-request/ReadPanel";

function field(value: unknown, key: string): string {
  if (typeof value !== "object" || !value || !(key in value)) throw Error("필드 누락");
  const result = (value as Record<string, unknown>)[key];
  if (typeof result !== "string") throw Error("문자열 필드 필요");
  return result;
}
function App() {
  const [user, setUser] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(true);
  const [error, setError] = React.useState("");
  async function restore() {
    setBusy(true); setError("");
    try { setUser(await getJson("/api/me", v => field(v, "id"))); }
    catch (e) {
      setUser(null);
      if (!(e instanceof HttpError && e.status === 401)) setError("계정을 확인하지 못했습니다.");
    } finally { setBusy(false); }
  }
  React.useEffect(() => { void restore(); }, []);
  if (busy) return <p>확인 중…</p>;
  if (!user) return <form onSubmit={async e => {
    e.preventDefault();
    const values = Object.fromEntries(new FormData(e.currentTarget));
    setBusy(true); setError("");
    try { await postJson("/api/login", values); await restore(); }
    catch { setError("로그인 실패"); setBusy(false); }
  }}>
    <label>아이디<input name="id" data-testid="id" /></label>
    <label>비밀번호<input name="password" type="password" data-testid="password" /></label>
    <button data-testid="login">로그인</button><p role="alert">{error}</p>
  </form>;
  return <main><p data-testid="identity">{user}</p>
    <ReadPanel accountId={user} path="/api/item" label="내 항목 조회"
      decode={v => field(v, "item")} onUnauthorized={() => setUser(null)}>
      {item => item}
    </ReadPanel>
    <button data-testid="logout" onClick={async () => {
      setBusy(true); setError("");
      try { await postJson("/api/logout", {}); setUser(null); }
      catch { setError("로그아웃 실패"); } finally { setBusy(false); }
    }}>로그아웃</button><p role="alert">{error}</p>
  </main>;
}
createRoot(document.getElementById("root")!).render(<App />);
