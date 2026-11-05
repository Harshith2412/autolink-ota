// Unit tests for the lifecycle-rail mapping (node:test; run with `npm run test:unit`).
import { test } from "node:test";
import assert from "node:assert/strict";
import { railPosition } from "../../src/components/LifecycleRail";

const d = (status: string, last_state: string | null = null, error_code: string | null = null) =>
  ({ status, last_state, error_code }) as Parameters<typeof railPosition>[0];

test("committed fills the whole rail", () => assert.deepEqual(railPosition(d("SUCCEEDED", "COMMITTED")), { reached: 7, failedAt: null }));
test("not yet started shows nothing reached", () => {
  for (const s of ["AWAITING_APPROVAL", "PENDING", "CANCELLED", "EXPIRED"]) assert.deepEqual(railPosition(d(s)), { reached: -1, failedAt: null });
});
test("in-progress marks the current stop", () => assert.deepEqual(railPosition(d("IN_PROGRESS", "STAGING")), { reached: 3, failedAt: null }));
test("signature/digest rejection fails at Verify", () => assert.deepEqual(railPosition(d("REJECTED", "VERIFICATION_FAILED", "DIGEST_MISMATCH")), { reached: 1, failedAt: 2 }));
test("rollback fails at Health check, not at Verify", () => assert.deepEqual(railPosition(d("ROLLED_BACK", "ROLLED_BACK")), { reached: 5, failedAt: 6 }));
test("abandoned download fails at Download", () => assert.deepEqual(railPosition(d("FAILED", "IDLE", "ABANDONED")), { reached: 0, failedAt: 1 }));
test("command rejected by ECU fails at the first stop", () => assert.deepEqual(railPosition(d("REJECTED", null, "COMMAND_REJECTED")), { reached: -1, failedAt: 0 }));
test("recovery failure is drawn as a failure", () => assert.equal(railPosition(d("RECOVERY_FAILED", "RECOVERY_FAILED")).failedAt, 6));
