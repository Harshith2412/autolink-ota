import { useApi } from "../hooks/useApi";
import { href } from "../hooks/useRoute";
import type { FleetSummary } from "../types/api";
import { LifecycleRail } from "../components/LifecycleRail";
import { Loaded, Status, fmtTime } from "../components/ui";

export function Fleet() {
  const q = useApi<FleetSummary>("/api/v1/fleet/summary", 3000);
  return (
    <Loaded q={q}>
      {(s) => {
        const maxCount = Math.max(1, ...s.firmware_distribution.map((f) => f.count));
        return (
          <>
            <header className="page-head">
              <h1>Fleet</h1>
              <p className="lede" data-testid="fleet-lede">
                {s.vehicles_total} vehicles registered, {s.connectivity.ONLINE} online now.
                {s.active_deployments > 0 && ` ${s.active_deployments} updates in flight.`}
                {s.failed_deployments > 0 && ` ${s.failed_deployments} did not commit.`}
              </p>
            </header>
            <dl className="figures">
              <div><dt>Online</dt><dd>{s.connectivity.ONLINE}</dd></div>
              <div><dt>Offline</dt><dd>{s.connectivity.OFFLINE}</dd></div>
              <div><dt>Never connected</dt><dd>{s.connectivity.NEVER_CONNECTED}</dd></div>
              <div><dt>Updates in flight</dt><dd>{s.active_deployments}</dd></div>
              <div className={s.failed_deployments ? "is-alert" : ""}><dt>Did not commit</dt><dd>{s.failed_deployments}</dd></div>
            </dl>
            <div className="split">
              <section aria-labelledby="dist">
                <h2 id="dist">Installed firmware</h2>
                {s.firmware_distribution.length === 0 ? <p className="note">No vehicle has reported a version yet.</p> : (
                  <ul className="bars">
                    {s.firmware_distribution.map((f) => (
                      <li key={f.version}>
                        <span className="bars__label">{f.version}</span>
                        <span className="bars__bar" style={{ width: `${(f.count / maxCount) * 100}%` }} />
                        <span className="bars__n">{f.count}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section aria-labelledby="alerts">
                <h2 id="alerts">Recent alerts</h2>
                {s.recent_alerts.length === 0 ? <p className="note">No warnings or errors reported.</p> : (
                  <ul className="list">
                    {s.recent_alerts.map((a) => (
                      <li key={a.id}><Status value={a.severity} /> <a href={href("vehicles", a.vehicle_id)}>{a.vehicle_id}</a>{" "}
                        <code>{a.code}</code> {a.description}<span className="muted"> {fmtTime(a.received_at)}</span></li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
            <section aria-labelledby="recent">
              <h2 id="recent">Latest deployments</h2>
              {s.recent_deployments.length === 0 ? <p className="note">No deployments yet. <a href={href("campaigns")}>Plan a campaign</a> to send firmware to vehicles.</p> : (
                <ul className="deployments">
                  {s.recent_deployments.map((d) => (
                    <li key={d.id}>
                      <div className="deployments__who"><a href={href("vehicles", d.vehicle_id)}>{d.vehicle_id}</a>
                        <span className="muted"> to {d.target_version}, {d.campaign_name}</span></div>
                      <LifecycleRail deployment={d} compact />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        );
      }}
    </Loaded>
  );
}
