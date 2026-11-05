import { useState, type FormEvent } from "react";
import { api, type ApiError } from "../services/api";
import type { User } from "../types/api";
import { ErrorNote } from "../components/ui";

export function Login({ onLogin }: { onLogin: (token: string, user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.login(username, password);
      onLogin(r.access_token, r.user);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="login">
      <div className="login__panel">
        <h1 className="wordmark">AutoLink OTA</h1>
        <p className="login__lede">Fleet software updates, from signed package to committed firmware.</p>
        <form onSubmit={submit} className="form">
          <label>Username<input name="username" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} /></label>
          <label>Password<input name="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <ErrorNote error={error} />
          <button className="btn btn--primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      </div>
    </main>
  );
}
