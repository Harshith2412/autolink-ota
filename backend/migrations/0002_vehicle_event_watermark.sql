-- Vehicle firmware/state is also derived from reliable (outbox-retried) STATE
-- events; the watermark keeps out-of-order events from regressing it.
ALTER TABLE vehicles ADD COLUMN last_event_seq INTEGER NOT NULL DEFAULT 0;
