import { useState } from "react";
import { useApi } from "../hooks/useApi";
import type { AuditEvent, Diagnostic, Page } from "../types/api";
import { Loaded, Status, fmtTime } from "../components/ui";
import { DiagnosticTable } from "./Vehicles";

export function Diagnostics() {
  const [severity, setSeverity] = useState("");
  const [vehicle, setVehicle] = useState("");
  const params = new URLSearchParams({ limit: "200", ...(severity && { severity }), ...(vehicle && { vehicle_id: vehicle }) });
  const q = useApi<Page<Diagnostic>>(`/api/v1/diagnostics?${params}`, 5000);
  return (
    <>
      <header className="page-head"><h1>Diagnostics</h1>
        <p className="lede">Trouble codes reported by vehicles (U3xxx: update failures and recoveries) and events raised by the cloud (C0xxx: connectivity, rejected telemetry).</p>
      </header>
      <div className="toolbar">
        <label>Severity
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">Any</option>{["INFO", "WARNING", "ERROR", "CRITICAL"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label>Vehicle ID<input value={vehicle} onChange={(e) => setVehicle(e.target.value.trim())} placeholder="exact ID" /></label>
      </div>
      <Loaded q={q} empty={(p) => p.items.length === 0 && "No diagnostic events match."}>
        {(p) => <><p className="muted">{p.total} events{p.total > p.items.length ? `, showing the latest ${p.items.length}` : ""}.</p><DiagnosticTable items={p.items} /></>}
      </Loaded>
    </>
  );
}

export function Audit() {
  const [action, setAction] = useState("");
  const params = new URLSearchParams({ limit: "200", ...(action && { action }) });
  const q = useApi<Page<AuditEvent>>(`/api/v1/audit-events?${params}`, 5000);
  return (
    <>
      <header className="page-head"><h1>Audit log</h1>
        <p className="lede">Every sensitive action, including refused ones, with who did it and from where.</p>
      </header>
      <div className="toolbar">
        <label>Action
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">All</option>
            {["auth", "vehicle", "firmware", "campaign", "device", "authz"].map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
      </div>
      <Loaded q={q} empty={(p) => p.items.length === 0 && "Nothing recorded for this filter."}>
        {(p) => (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Outcome</th><th>Details</th></tr></thead>
              <tbody>
                {p.items.map((e) => (
                  <tr key={e.id}>
                    <td>{fmtTime(e.ts)}</td><td>{e.actor}</td><td><code>{e.action}</code></td>
                    <td>{e.target_type ? `${e.target_type} ${e.target_id ?? ""}` : ""}</td><td><Status value={e.outcome} /></td>
                    <td className="details">{Object.entries(e.details).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loaded>
    </>
  );
}
