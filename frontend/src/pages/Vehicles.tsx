import { useState, type FormEvent } from "react";
import { useApi } from "../hooks/useApi";
import { href } from "../hooks/useRoute";
import { api, can, type ApiError } from "../services/api";
import type { Diagnostic, Page, TelemetryPoint, User, Vehicle } from "../types/api";
import { LifecycleRail } from "../components/LifecycleRail";
import { LineChart } from "../components/LineChart";
import { ErrorNote, Loaded, Status, fmtTime } from "../components/ui";

export function Vehicles({ user }: { user: User }) {
  const [search, setSearch] = useState("");
  const [conn, setConn] = useState("");
  const params = new URLSearchParams({ limit: "200", ...(search && { q: search }), ...(conn && { connectivity: conn }) });
  const q = useApi<Page<Vehicle>>(`/api/v1/vehicles?${params}`, 5000);
  return (
    <>
      <header className="page-head"><h1>Vehicles</h1></header>
      <div className="toolbar" role="search">
        <label>Search<input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Vehicle ID, name or model" /></label>
        <label>Connectivity
          <select value={conn} onChange={(e) => setConn(e.target.value)}>
            <option value="">Any</option><option value="ONLINE">Online</option><option value="OFFLINE">Offline</option>
            <option value="NEVER_CONNECTED">Never connected</option>
          </select>
        </label>
      </div>
      <Loaded q={q} empty={(p) => p.items.length === 0 && (search || conn ? "No vehicles match these filters." : "No vehicles yet. Register one below to issue its device credential.")}>
        {(p) => (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Vehicle</th><th>Model</th><th>Hardware</th><th>Firmware</th><th>ECU state</th><th>Connectivity</th><th>Last heartbeat</th></tr></thead>
              <tbody>
                {p.items.map((v) => (
                  <tr key={v.id}>
                    <td><a href={href("vehicles", v.id)}>{v.id}</a><div className="muted">{v.display_name}</div></td>
                    <td>{v.model}</td><td>{v.hardware_id}</td><td>{v.firmware_version ?? "unknown"}</td>
                    <td>{v.update_state ?? "unknown"}</td><td><Status value={v.connectivity} /></td><td>{fmtTime(v.last_heartbeat_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loaded>
      {can.write(user) && <RegisterVehicle onDone={q.reload} />}
    </>
  );
}

function RegisterVehicle({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({ vehicle_id: "", display_name: "", model: "", ecu_id: "ECU-TCU-01", hardware_id: "ALK-TCU-R1" });
  const [error, setError] = useState<ApiError | null>(null);
  const [issued, setIssued] = useState<Vehicle | null>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      setIssued(await api.post<Vehicle>("/api/v1/vehicles", form));
      onDone();
    } catch (err) { setError(err as ApiError); }
  };
  return (
    <section aria-labelledby="reg">
      <h2 id="reg">Register a vehicle</h2>
      <form className="form form--grid" onSubmit={submit}>
        <label>Vehicle ID<input required pattern="[A-Za-z0-9][A-Za-z0-9._\-]{0,63}" value={form.vehicle_id} onChange={set("vehicle_id")} /></label>
        <label>Name<input required maxLength={100} value={form.display_name} onChange={set("display_name")} /></label>
        <label>Model<input required maxLength={100} value={form.model} onChange={set("model")} /></label>
        <label>ECU ID<input required value={form.ecu_id} onChange={set("ecu_id")} /></label>
        <label>Hardware ID<input required value={form.hardware_id} onChange={set("hardware_id")} /></label>
        <div className="actions"><button className="btn btn--primary">Register vehicle</button></div>
      </form>
      <ErrorNote error={error} />
      {issued?.device_token && (
        <div className="note note--key" role="status">
          <p>Registered {issued.id}. Copy its device token now; it is shown only once and stored only as a hash.</p>
          <code className="token" data-testid="device-token">{issued.device_token}</code>
        </div>
      )}
    </section>
  );
}

export function VehicleDetail({ id }: { id: string }) {
  const v = useApi<Vehicle>(`/api/v1/vehicles/${encodeURIComponent(id)}`, 3000);
  const t = useApi<{ items: TelemetryPoint[] }>(`/api/v1/vehicles/${encodeURIComponent(id)}/telemetry?limit=60`, 3000);
  const d = useApi<Page<Diagnostic>>(`/api/v1/vehicles/${encodeURIComponent(id)}/diagnostics?limit=50`, 5000);
  return (
    <Loaded q={v}>
      {(veh) => (
        <>
          <header className="page-head">
            <p className="crumb"><a href={href("vehicles")}>Vehicles</a></p>
            <h1>{veh.id}</h1>
            <p className="lede">{veh.display_name}, {veh.model}. Running <strong data-testid="vehicle-firmware">{veh.firmware_version ?? "unknown"}</strong> from slot {veh.active_slot ?? "?"}.</p>
          </header>
          <dl className="facts">
            <div><dt>Connectivity</dt><dd><Status value={veh.connectivity} /></dd></div>
            <div><dt>Last heartbeat</dt><dd>{fmtTime(veh.last_heartbeat_at)}</dd></div>
            <div><dt>ECU</dt><dd>{veh.ecu_id}</dd></div>
            <div><dt>Hardware</dt><dd>{veh.hardware_id}</dd></div>
            <div><dt>Update state</dt><dd>{veh.update_state ?? "unknown"}</dd></div>
          </dl>
          <section aria-labelledby="hist">
            <h2 id="hist">Update history</h2>
            {!veh.deployments?.length ? <p className="note">This vehicle has not been targeted by a campaign.</p> : (
              <ul className="deployments">
                {veh.deployments.map((dep) => (
                  <li key={dep.id}>
                    <div className="deployments__who"><a href={href("campaigns", dep.campaign_id)}>{dep.campaign_name}</a>
                      <span className="muted"> to {dep.target_version}, {fmtTime(dep.created_at)}</span></div>
                    <LifecycleRail deployment={dep} />
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-labelledby="tel">
            <h2 id="tel">Telemetry</h2>
            <Loaded q={t} empty={(x) => x.items.length === 0 && "No telemetry received yet."}>
              {(x) => {
                const times = x.items.map((p) => p.received_at);
                return (
                  <div className="charts">
                    <LineChart title="Speed" unit="km/h" values={x.items.map((p) => p.speed_kph)} times={times} />
                    <LineChart title="Battery" unit="V" values={x.items.map((p) => p.battery_v)} times={times} />
                    <LineChart title="Coolant" unit="°C" values={x.items.map((p) => p.coolant_c)} times={times} />
                    <LineChart title="Signal" unit="dBm" values={x.items.map((p) => p.rssi_dbm)} times={times} />
                  </div>
                );
              }}
            </Loaded>
          </section>
          <section aria-labelledby="diag">
            <h2 id="diag">Diagnostics</h2>
            <Loaded q={d} empty={(x) => x.items.length === 0 && "No diagnostic events for this vehicle."}>
              {(x) => <DiagnosticTable items={x.items} showVehicle={false} />}
            </Loaded>
          </section>
        </>
      )}
    </Loaded>
  );
}

export function DiagnosticTable({ items, showVehicle = true }: { items: Diagnostic[]; showVehicle?: boolean }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Received</th>{showVehicle && <th>Vehicle</th>}<th>Severity</th><th>Code</th><th>Description</th><th>Source</th></tr></thead>
        <tbody>
          {items.map((x) => (
            <tr key={x.id}>
              <td>{fmtTime(x.received_at)}</td>
              {showVehicle && <td><a href={href("vehicles", x.vehicle_id)}>{x.vehicle_id}</a></td>}
              <td><Status value={x.severity} /></td><td><code>{x.code}</code></td><td>{x.description}</td>
              <td>{x.source === "CLOUD" ? "Cloud" : "Vehicle"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
