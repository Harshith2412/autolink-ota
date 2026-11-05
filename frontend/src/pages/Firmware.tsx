import { useRef, useState, type FormEvent } from "react";
import { useApi } from "../hooks/useApi";
import { api, can, type ApiError } from "../services/api";
import type { Firmware as Fw, Page, User } from "../types/api";
import { Loaded, fmtBytes, fmtTime, short } from "../components/ui";

export function Firmware({ user }: { user: User }) {
  const q = useApi<Page<Fw>>("/api/v1/firmware?limit=200");
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <header className="page-head"><h1>Firmware</h1>
        <p className="lede">Packages are accepted only when their Ed25519 signature verifies against the trust store and the image matches the signed SHA-256.</p>
      </header>
      {can.write(user) && <Upload onDone={q.reload} />}
      <section aria-labelledby="rel">
        <h2 id="rel">Release history</h2>
        <Loaded q={q} empty={(p) => p.items.length === 0 && "No firmware uploaded yet. Sign a package with firmware/tools/autolink_fw.py and upload it here."}>
          {(p) => (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Firmware</th><th>Version</th><th>Hardware</th><th>Signature</th><th>Security counter</th><th>Size</th><th>Uploaded</th><th /></tr></thead>
                <tbody>
                  {p.items.map((f) => (
                    <FwRow key={f.id} f={f} open={open === f.id} toggle={() => setOpen(open === f.id ? null : f.id)} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Loaded>
      </section>
    </>
  );
}

function FwRow({ f, open, toggle }: { f: Fw; open: boolean; toggle: () => void }) {
  return (
    <>
      <tr>
        <td>{f.id}</td><td>{f.version}{f.simulate_unhealthy && <span className="tag">fails self-test</span>}</td><td>{f.hardware_id}</td>
        <td>{f.signature_verified ? <span className="status status-succeeded">verified ({f.key_id})</span> : <span className="status status-failed">unverified</span>}</td>
        <td>{f.security_counter}</td><td>{fmtBytes(f.size)}</td><td>{fmtTime(f.created_at)}</td>
        <td><button className="btn btn--quiet" onClick={toggle} aria-expanded={open}>{open ? "Hide details" : "Details"}</button></td>
      </tr>
      {open && (
        <tr className="detail-row"><td colSpan={8}>
          <dl className="facts">
            <div><dt>SHA-256</dt><dd><code title={f.sha256}>{short(f.sha256, 24)}</code></dd></div>
            <div><dt>Requires installed</dt><dd>{f.min_current_version} or newer</dd></div>
            <div><dt>Release notes</dt><dd>{f.release_notes || "none"}</dd></div>
          </dl>
        </td></tr>
      )}
    </>
  );
}

function Upload({ onDone }: { onDone: () => void }) {
  const manifest = useRef<HTMLInputElement>(null);
  const image = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<Fw | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const m = manifest.current?.files?.[0], i = image.current?.files?.[0];
    if (!m || !i) return;
    const fd = new FormData();
    fd.append("manifest", m);
    fd.append("image", i);
    setBusy(true); setError(null); setDone(null);
    try {
      setDone(await api.post<Fw>("/api/v1/firmware", fd));
      onDone();
      (e.target as HTMLFormElement).reset();
    } catch (err) { setError(err as ApiError); } finally { setBusy(false); }
  };
  const reason = (error?.details as { reason?: string } | undefined)?.reason;
  return (
    <section aria-labelledby="up">
      <h2 id="up">Upload a signed package</h2>
      <form className="form form--grid" onSubmit={submit}>
        <label>Manifest (.json)<input ref={manifest} type="file" accept="application/json,.json" required /></label>
        <label>Image<input ref={image} type="file" required /></label>
        <div className="actions"><button className="btn btn--primary" disabled={busy}>{busy ? "Verifying…" : "Upload package"}</button></div>
      </form>
      {error && <p className="note note--error" role="alert">Rejected{reason ? ` (${reason})` : ""}: {error.message}</p>}
      {done && <p className="note note--ok" role="status">Uploaded {done.id} {done.version}. Signature verified with {done.key_id}.</p>}
    </section>
  );
}
