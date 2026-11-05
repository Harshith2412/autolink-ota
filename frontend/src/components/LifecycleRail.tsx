import type { Deployment } from "../types/api";

// Every deployment drawn on the same track, so outcomes are comparable at a glance.
const STOPS = ["Available", "Download", "Verify", "Stage", "Ready", "Activate", "Health check", "Committed"];
const STATE_INDEX: Record<string, number> = {
  UPDATE_AVAILABLE: 0, DOWNLOADING: 1, DOWNLOAD_FAILED: 1, VERIFYING: 2, VERIFICATION_FAILED: 2, STAGING: 3,
  STAGING_FAILED: 3, READY_TO_ACTIVATE: 4, ACTIVATING: 5, HEALTH_CHECK: 6, ACTIVATION_FAILED: 6,
  RECOVERY_IN_PROGRESS: 6, ROLLED_BACK: 6, RECOVERY_FAILED: 6, COMMITTED: 7,
};
const OUTCOME: Record<string, string> = {
  AWAITING_APPROVAL: "Waiting for approval", PENDING: "Sent to vehicle", IN_PROGRESS: "In progress",
  SUCCEEDED: "Committed", REJECTED: "Rejected by vehicle", ROLLED_BACK: "Rolled back to last known-good",
  FAILED: "Failed", RECOVERY_FAILED: "Recovery failed, service needed", EXPIRED: "Command expired",
  CANCELLED: "Cancelled",
};

export function railPosition(d: Pick<Deployment, "status" | "last_state" | "error_code">): { reached: number; failedAt: number | null } {
  if (d.status === "SUCCEEDED") return { reached: 7, failedAt: null };
  if (["AWAITING_APPROVAL", "PENDING", "CANCELLED", "EXPIRED"].includes(d.status)) return { reached: -1, failedAt: null };
  if (d.error_code === "COMMAND_REJECTED") return { reached: -1, failedAt: 0 };
  const idx = d.last_state && d.last_state in STATE_INDEX ? STATE_INDEX[d.last_state] : d.status === "FAILED" ? 1 : 0;
  const failed = ["REJECTED", "ROLLED_BACK", "FAILED", "RECOVERY_FAILED"].includes(d.status);
  return failed ? { reached: idx - 1, failedAt: idx } : { reached: idx, failedAt: null };
}

export function LifecycleRail({ deployment, compact = false }: { deployment: Deployment; compact?: boolean }) {
  const { reached, failedAt } = railPosition(deployment);
  const outcome = OUTCOME[deployment.status] ?? deployment.status;
  const label = `${outcome}${deployment.error_code ? ` (${deployment.error_code})` : ""}`;
  return (
    <div className={`rail ${compact ? "rail--compact" : ""}`} role="img" aria-label={`Update ${deployment.target_version}: ${label}`}>
      <ol className="rail__track">
        {STOPS.map((stop, i) => {
          const cls = i === failedAt ? "is-failed" : i <= reached ? "is-done" : "";
          return (
            <li key={stop} className={`rail__stop ${cls}`}>
              <span className="rail__dot" aria-hidden="true" />
              {!compact && <span className="rail__label">{stop}</span>}
            </li>
          );
        })}
      </ol>
      <p className={`rail__outcome status-${deployment.status.toLowerCase()}`}>{label}</p>
    </div>
  );
}
