-- AutoLink OTA initial schema. Portable SQL (SQLite verified; PostgreSQL-compatible types).
CREATE TABLE roles (
  name        TEXT PRIMARY KEY,
  description TEXT NOT NULL
);
INSERT INTO roles (name, description) VALUES
  ('admin',    'Full control incl. campaign approval and credential rotation'),
  ('engineer', 'Register vehicles, upload firmware, draft campaigns'),
  ('viewer',   'Read-only access');

CREATE TABLE users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL REFERENCES roles(name),
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL
);

CREATE TABLE vehicles (
  id                TEXT PRIMARY KEY,           -- vehicle identifier (VIN-like)
  display_name      TEXT NOT NULL,
  model             TEXT NOT NULL,
  device_token_hash TEXT NOT NULL,
  next_command_seq  INTEGER NOT NULL DEFAULT 1,
  last_command_seq  INTEGER NOT NULL DEFAULT 0, -- last seq reported consumed by ECU
  last_heartbeat_at TEXT,
  firmware_version  TEXT,
  update_state      TEXT,
  created_at        TEXT NOT NULL
);

CREATE TABLE ecus (
  id          TEXT PRIMARY KEY,
  vehicle_id  TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
  ecu_id      TEXT NOT NULL,
  hardware_id TEXT NOT NULL,
  active_slot TEXT,
  UNIQUE (vehicle_id, ecu_id)
);
CREATE INDEX ix_ecus_hardware ON ecus(hardware_id);

CREATE TABLE firmware_packages (
  id                  TEXT PRIMARY KEY,         -- firmware_id from the signed manifest
  version             TEXT NOT NULL,
  hardware_id         TEXT NOT NULL,
  sha256              TEXT NOT NULL,
  size                INTEGER NOT NULL,
  security_counter    INTEGER NOT NULL,
  min_current_version TEXT NOT NULL,
  key_id              TEXT NOT NULL,
  release_notes       TEXT NOT NULL,
  simulate_unhealthy  INTEGER NOT NULL,
  manifest_json       TEXT NOT NULL,
  blob_key            TEXT NOT NULL,
  signature_verified  INTEGER NOT NULL,
  uploaded_by         TEXT NOT NULL REFERENCES users(id),
  created_at          TEXT NOT NULL,
  UNIQUE (hardware_id, version)
);

CREATE TABLE update_campaigns (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  firmware_id TEXT NOT NULL REFERENCES firmware_packages(id),
  status      TEXT NOT NULL,                    -- PENDING_APPROVAL | APPROVED | CANCELLED
  created_by  TEXT NOT NULL REFERENCES users(id),
  approved_by TEXT REFERENCES users(id),
  created_at  TEXT NOT NULL,
  approved_at TEXT
);

CREATE TABLE deployments (
  id           TEXT PRIMARY KEY,
  campaign_id  TEXT NOT NULL REFERENCES update_campaigns(id),
  vehicle_id   TEXT NOT NULL REFERENCES vehicles(id),
  status       TEXT NOT NULL,                   -- see app/services/deployment_status.py
  command_seq  INTEGER,
  expires_at   INTEGER,
  last_state   TEXT,
  error_code   TEXT,
  created_at   TEXT NOT NULL,
  finished_at  TEXT,
  UNIQUE (campaign_id, vehicle_id),
  UNIQUE (vehicle_id, command_seq)
);
CREATE INDEX ix_deployments_vehicle_status ON deployments(vehicle_id, status);

CREATE TABLE deployment_events (
  id               TEXT PRIMARY KEY,
  deployment_id    TEXT REFERENCES deployments(id),
  vehicle_id       TEXT NOT NULL REFERENCES vehicles(id),
  event_seq        INTEGER NOT NULL,
  kind             TEXT NOT NULL,
  from_state       TEXT,
  to_state         TEXT,
  detail           TEXT,
  error_code       TEXT,
  firmware_version TEXT,
  device_ts        INTEGER NOT NULL,
  received_at      TEXT NOT NULL,
  UNIQUE (vehicle_id, event_seq)               -- idempotent ingestion
);
CREATE INDEX ix_events_deployment ON deployment_events(deployment_id);

CREATE TABLE telemetry_records (
  id               TEXT PRIMARY KEY,
  vehicle_id       TEXT NOT NULL REFERENCES vehicles(id),
  received_at      TEXT NOT NULL,
  speed_kph        REAL,
  battery_v        REAL,
  coolant_c        REAL,
  rssi_dbm         REAL,
  firmware_version TEXT,
  update_state     TEXT
);
CREATE INDEX ix_telemetry_vehicle_time ON telemetry_records(vehicle_id, received_at);

CREATE TABLE diagnostic_events (
  id            TEXT PRIMARY KEY,
  vehicle_id    TEXT NOT NULL REFERENCES vehicles(id),
  deployment_id TEXT REFERENCES deployments(id),
  event_seq     INTEGER,                        -- NULL for cloud-generated events
  source        TEXT NOT NULL DEFAULT 'DEVICE', -- DEVICE | CLOUD
  code          TEXT NOT NULL,
  severity      TEXT NOT NULL,
  description   TEXT NOT NULL,
  device_ts     INTEGER NOT NULL,
  received_at   TEXT NOT NULL,
  UNIQUE (vehicle_id, event_seq)
);
CREATE INDEX ix_diag_vehicle_time ON diagnostic_events(vehicle_id, received_at);

CREATE TABLE audit_events (
  id          TEXT PRIMARY KEY,
  ts          TEXT NOT NULL,
  actor       TEXT NOT NULL,                    -- username, vehicle:<id>, or anonymous
  action      TEXT NOT NULL,
  target_type TEXT,
  target_id   TEXT,
  outcome     TEXT NOT NULL,                    -- SUCCESS | DENIED | FAILED
  details     TEXT NOT NULL,                    -- JSON
  source_ip   TEXT
);
CREATE INDEX ix_audit_ts ON audit_events(ts);
