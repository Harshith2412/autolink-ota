import { useEffect, useRef, type ReactNode } from "react";
import type { ApiError } from "../services/api";
import type { Query } from "../hooks/useApi";

export function Status({ value }: { value: string }) {
  return <span className={`status status-${value.toLowerCase()}`}>{value.replace(/_/g, " ").toLowerCase()}</span>;
}

export function ErrorNote({ error }: { error: ApiError | Error | null }) {
  if (!error) return null;
  return <p className="note note--error" role="alert">{error.message}</p>;
}

// Loading / error / empty handling in one place so every page treats them alike.
export function Loaded<T>({ q, empty, children }: { q: Query<T>; empty?: (d: T) => ReactNode | false; children: (d: T) => ReactNode }) {
  if (q.loading && q.data === undefined) return <p className="note" aria-live="polite">Loading…</p>;
  if (q.error && q.data === undefined) return <ErrorNote error={q.error} />;
  if (q.data === undefined) return null;
  const e = empty?.(q.data);
  if (e) return <div className="note note--empty">{e}</div>;
  return <>{children(q.data)}</>;
}

export function Confirm({ open, title, body, confirmLabel, danger, onConfirm, onCancel }: {
  open: boolean; title: string; body: ReactNode; confirmLabel: string; danger?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal?.();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="dialog" onCancel={(e) => { e.preventDefault(); onCancel(); }} aria-labelledby="dlg-title">
      <h2 id="dlg-title">{title}</h2>
      <div className="dialog__body">{body}</div>
      <div className="actions">
        <button type="button" className="btn" onClick={onCancel}>Keep as is</button>
        <button type="button" className={`btn ${danger ? "btn--danger" : "btn--primary"}`} onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </dialog>
  );
}

export const fmtTime = (iso: string | null) => iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" }) : "never";
export const fmtBytes = (n: number) => n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KiB` : `${(n / 1048576).toFixed(2)} MiB`;
export const short = (s: string, n = 12) => (s.length > n ? s.slice(0, n) + "…" : s);
