import { useState } from "react";
import { useApi } from "../hooks/useApi";
import { href, navigate } from "../hooks/useRoute";
import { api, can, type ApiError } from "../services/api";
import type { Campaign, Compatibility, Firmware, Page, User, Vehicle } from "../types/api";
import { LifecycleRail } from "../components/LifecycleRail";
import { Confirm, ErrorNote, Loaded, Status, fmtTime } from "../components/ui";

export function Campaigns({ user }: { user: User }) {
  const q = useApi<Page<Campaign>>("/api/v1/campaigns?limit=100", 4000);
  return (
    <>
      <header className="page-head"><h1>Campaigns</h1>
        <p className="lede">A campaign sends one firmware package to chosen vehicles. An engineer drafts it; a different administrator approves it before any vehicle is told to update.</p>
      </header>
      {can.write(user) && <NewCampaign />}
      <section aria-labelledby="all">
        <h2 id="all">All campaigns</h2>
        <Loaded q={q} empty={(p) => p.items.length === 0 && "No campaigns yet."}>
          {(p) => (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Campaign</th><th>Firmware</th><th>Status</th><th>Progress</th><th>Drafted by</th><th>Approved by</th><th>Created</th></tr></thead>
                <tbody>
                  {p.items.map((c) => (
                    <tr key={c.id}>
                      <td><a href={href("campaigns", c.id)}>{c.name}</a></td><td>{c.firmware_id} ({c.firmware_version})</td>
                      <td><Status value={c.status} /></td>
                      <td>{c.progress.finished} of {c.progress.total} finished{c.progress.by_status.SUCCEEDED ? `, ${c.progress.by_status.SUCCEEDED} committed` : ""}</td>
                      <td>{c.created_by_name}</td><td>{c.approved_by_name ?? "not yet"}</td><td>{fmtTime(c.created_at)}</td>
                    </tr>
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

function NewCampaign() {
  const fw = useApi<Page<Firmware>>("/api/v1/firmware?limit=200");
  const vs = useApi<Page<Vehicle>>("/api/v1/vehicles?limit=200");
  const [name, setName] = useState("");
  const [firmwareId, setFirmwareId] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [compat, setCompat] = useState<Compatibility | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const chosen = fw.data?.items.find((f) => f.id === firmwareId);
  const candidates = (vs.data?.items ?? []).filter((v) => !chosen || v.hardware_id === chosen.hardware_id);
  const toggle = (id: string) => { setCompat(null); setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]); };
  const check = async () => {
    setError(null);
    try { setCompat(await api.post<Compatibility>("/api/v1/campaigns/validate", { firmware_id: firmwareId, vehicle_ids: selected })); }
    catch (e) { setError(e as ApiError); }
  };
  const create = async () => {
    setError(null);
    try {
      const c = await api.post<Campaign>("/api/v1/campaigns", { name, firmware_id: firmwareId, vehicle_ids: selected });
      navigate("campaigns", c.id);
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "incompatible_targets") setCompat(err.details as Compatibility);
      setError(err);
    }
  };
  return (
    <section aria-labelledby="new">
      <h2 id="new">Draft a campaign</h2>
      <div className="form form--grid">
        <label>Name<input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="e.g. TCU 1.1.0 pilot" /></label>
        <label>Firmware
          <select value={firmwareId} onChange={(e) => { setFirmwareId(e.target.value); setSelected([]); setCompat(null); }}>
            <option value="">Choose a package</option>
            {fw.data?.items.map((f) => <option key={f.id} value={f.id}>{f.id} ({f.version}, {f.hardware_id})</option>)}
          </select>
        </label>
      </div>
      {firmwareId && (
        <fieldset className="pick">
          <legend>Target vehicles with hardware {chosen?.hardware_id}</legend>
          {candidates.length === 0 ? <p className="note">No registered vehicle uses this hardware.</p> : candidates.map((v) => {
            const c = compat?.vehicles.find((x) => x.vehicle_id === v.id);
            return (
              <label key={v.id} className="pick__item">
                <input type="checkbox" checked={selected.includes(v.id)} onChange={() => toggle(v.id)} />
                <span>{v.id}</span><span className="muted">runs {v.firmware_version ?? "unknown"}</span>
                {c && (c.compatible ? <span className="status status-succeeded">compatible</span> : <span className="status status-failed">{c.issues.join("; ")}</span>)}
              </label>
            );
          })}
        </fieldset>
      )}
      <div className="actions">
        <button className="btn" disabled={!firmwareId || !selected.length} onClick={check}>Check compatibility</button>
        <button className="btn btn--primary" disabled={!name.trim() || !firmwareId || !selected.length || compat?.all_compatible === false} onClick={create}>Draft campaign</button>
      </div>
      <ErrorNote error={error} />
    </section>
  );
}

export function CampaignDetail({ id, user }: { id: string; user: User }) {
  const q = useApi<Campaign>(`/api/v1/campaigns/${encodeURIComponent(id)}`, 2000);
  const [confirm, setConfirm] = useState<"approve" | "cancel" | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const act = async (what: "approve" | "cancel") => {
    setConfirm(null); setError(null);
    try { await api.post(`/api/v1/campaigns/${encodeURIComponent(id)}/${what}`); q.reload(); }
    catch (e) { setError(e as ApiError); }
  };
  return (
    <Loaded q={q}>
      {(c) => (
        <>
          <header className="page-head">
            <p className="crumb"><a href={href("campaigns")}>Campaigns</a></p>
            <h1>{c.name}</h1>
            <p className="lede">{c.firmware_id} version {c.firmware_version} to {c.progress.total} vehicle{c.progress.total === 1 ? "" : "s"}. Drafted by {c.created_by_name}{c.approved_by_name ? `, approved by ${c.approved_by_name}` : ""}. <Status value={c.status} /></p>
          </header>
          {can.admin(user) && c.status !== "CANCELLED" && (
            <div className="actions">
              {c.status === "PENDING_APPROVAL" && <button className="btn btn--primary" onClick={() => setConfirm("approve")}>Approve and send</button>}
              <button className="btn btn--danger" onClick={() => setConfirm("cancel")}>Cancel campaign</button>
            </div>
          )}
          <ErrorNote error={error} />
          <section aria-labelledby="deps">
            <h2 id="deps">Vehicles</h2>
            <ul className="deployments">
              {c.deployments?.map((d) => (
                <li key={d.id} data-testid={`deployment-${d.vehicle_id}`}>
                  <div className="deployments__who"><a href={href("vehicles", d.vehicle_id)}>{d.vehicle_id}</a>
                    {d.finished_at && <span className="muted"> finished {fmtTime(d.finished_at)}</span>}</div>
                  <LifecycleRail deployment={d} />
                </li>
              ))}
            </ul>
          </section>
          <Confirm open={confirm === "approve"} title="Approve this campaign?" confirmLabel="Approve and send"
            body={<p>Each target vehicle will receive a signed install command for {c.firmware_version} on its next heartbeat.</p>}
            onConfirm={() => act("approve")} onCancel={() => setConfirm(null)} />
          <Confirm open={confirm === "cancel"} title="Cancel this campaign?" confirmLabel="Cancel campaign" danger
            body={<p>Vehicles that have not yet received the command will not be updated. Vehicles already updating will finish or roll back on their own.</p>}
            onConfirm={() => act("cancel")} onCancel={() => setConfirm(null)} />
        </>
      )}
    </Loaded>
  );
}
