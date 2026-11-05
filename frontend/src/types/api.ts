// Types mirror the backend JSON responses (backend/app/api/*.py).
export type Role = "admin" | "engineer" | "viewer";
export type Connectivity = "ONLINE" | "OFFLINE" | "NEVER_CONNECTED";
export type DeploymentStatus =
  | "AWAITING_APPROVAL" | "PENDING" | "IN_PROGRESS" | "SUCCEEDED" | "REJECTED"
  | "ROLLED_BACK" | "FAILED" | "RECOVERY_FAILED" | "EXPIRED" | "CANCELLED";

export interface User { id: string; username: string; role: Role }
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }

export interface Deployment {
  id: string; campaign_id: string; campaign_name: string; vehicle_id: string; firmware_id: string;
  target_version: string; status: DeploymentStatus; command_seq: number | null; last_state: string | null;
  error_code: string | null; created_at: string; finished_at: string | null; events?: DeploymentEvent[];
}
export interface DeploymentEvent {
  id: string; event_seq: number; kind: "STATE" | "DTC" | "COMMAND_REJECTED"; from_state: string | null;
  to_state: string | null; detail: string | null; error_code: string | null; firmware_version: string | null;
  device_ts: number; received_at: string;
}
export interface Vehicle {
  id: string; display_name: string; model: string; last_heartbeat_at: string | null; firmware_version: string | null;
  update_state: string | null; ecu_id: string; hardware_id: string; active_slot: string | null;
  connectivity: Connectivity; created_at: string; deployments?: Deployment[]; device_token?: string;
}
export interface Firmware {
  id: string; version: string; hardware_id: string; sha256: string; size: number; security_counter: number;
  min_current_version: string; key_id: string; release_notes: string; simulate_unhealthy: boolean;
  signature_verified: boolean; created_at: string; manifest?: Record<string, unknown>;
}
export interface Campaign {
  id: string; name: string; firmware_id: string; firmware_version: string; hardware_id: string;
  status: "PENDING_APPROVAL" | "APPROVED" | "CANCELLED"; created_by: string; created_by_name: string;
  approved_by_name: string | null; created_at: string; approved_at: string | null;
  progress: { total: number; finished: number; by_status: Record<string, number> }; deployments?: Deployment[];
}
export interface Compatibility {
  firmware_id: string; target_version: string; all_compatible: boolean;
  vehicles: { vehicle_id: string; compatible: boolean; issues: string[] }[];
}
export interface Diagnostic {
  id: string; vehicle_id: string; deployment_id: string | null; event_seq: number | null; source: "DEVICE" | "CLOUD";
  code: string; severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL"; description: string; received_at: string;
}
export interface TelemetryPoint {
  received_at: string; speed_kph: number | null; battery_v: number | null; coolant_c: number | null; rssi_dbm: number | null;
}
export interface AuditEvent {
  id: string; ts: string; actor: string; action: string; target_type: string | null; target_id: string | null;
  outcome: "SUCCESS" | "DENIED" | "FAILED"; details: Record<string, unknown>; source_ip: string | null;
}
export interface FleetSummary {
  vehicles_total: number; connectivity: Record<Connectivity, number>;
  firmware_distribution: { version: string; count: number }[]; deployments_by_status: Record<string, number>;
  active_deployments: number; failed_deployments: number; recent_alerts: Diagnostic[]; recent_deployments: Deployment[];
}
