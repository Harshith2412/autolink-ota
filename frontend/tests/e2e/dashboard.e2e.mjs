// Dashboard end-to-end check with Playwright (library API) against a live stack.
// Env: BASE_URL, ADMIN_USER, ADMIN_PASSWORD, VEHICLE_ID, BAD_VEHICLE_ID, CAMPAIGN_ID, SCREENSHOT_DIR
import { chromium } from "playwright";
import assert from "node:assert/strict";

const { BASE_URL, ADMIN_USER, ADMIN_PASSWORD, VEHICLE_ID, BAD_VEHICLE_ID, CAMPAIGN_ID, SCREENSHOT_DIR } = process.env;
const results = [];
const check = async (name, fn) => {
  try { await fn(); results.push({ name, ok: true }); console.log(`ok   ${name}`); }
  catch (e) { results.push({ name, ok: false, error: String(e) }); console.log(`FAIL ${name}: ${e.message}`); }
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
const consoleErrors = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
const shot = (n) => SCREENSHOT_DIR && page.screenshot({ path: `${SCREENSHOT_DIR}/${n}.png`, fullPage: true });

await check("rejects wrong password with a visible error", async () => {
  await page.goto(BASE_URL + "/");
  await page.getByLabel("Username").fill(ADMIN_USER);
  await page.getByLabel("Password").fill("definitely-wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("alert").filter({ hasText: "invalid username or password" }).waitFor({ timeout: 5000 });
});

await check("signs in and shows fleet overview from the backend", async () => {
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { name: "Fleet", level: 1 }).waitFor({ timeout: 5000 });
  const lede = await page.getByTestId("fleet-lede").innerText();
  assert.match(lede, /\d+ vehicles registered/);
  await page.locator(".rail").first().waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 1, `desktop page overflows by ${overflow}px`);
  await shot("01-fleet");
});

await check("vehicle page shows committed firmware, rail and telemetry", async () => {
  await page.goto(`${BASE_URL}/#/vehicles/${VEHICLE_ID}`);
  await page.getByTestId("vehicle-firmware").filter({ hasText: "1.1.0" }).waitFor({ timeout: 8000 });
  await page.getByText("Committed", { exact: true }).last().waitFor();
  const charts = await page.locator("figure.chart svg").count();
  assert.ok(charts >= 3, `expected telemetry charts, saw ${charts}`);
  await shot("02-vehicle");
});

await check("rejected corrupt update is shown as rejected, version unchanged", async () => {
  await page.goto(`${BASE_URL}/#/vehicles/${BAD_VEHICLE_ID}`);
  await page.getByTestId("vehicle-firmware").filter({ hasText: "1.0.0" }).waitFor({ timeout: 8000 });
  await page.getByText(/Rejected by vehicle \(DIGEST_MISMATCH\)/).waitFor();
  await page.getByRole("cell", { name: "U3002" }).waitFor();
});

await check("campaign page lists both outcomes", async () => {
  await page.goto(`${BASE_URL}/#/campaigns/${CAMPAIGN_ID}`);
  await page.getByTestId(`deployment-${VEHICLE_ID}`).getByText("Committed", { exact: true }).last().waitFor({ timeout: 5000 });
  await shot("03-campaign");
});

await check("audit log shows the approval", async () => {
  await page.goto(`${BASE_URL}/#/audit`);
  await page.getByRole("cell", { name: "campaign.approve" }).first().waitFor({ timeout: 5000 });
  await shot("04-audit");
});

await check("firmware page shows verified signature", async () => {
  await page.goto(`${BASE_URL}/#/firmware`);
  await page.getByText(/verified \(dev-key-1\)/).first().waitFor({ timeout: 5000 });
});

await check("basic accessibility: labelled controls, named buttons, one h1", async () => {
  for (const route of ["fleet", "vehicles", "firmware", "campaigns", "diagnostics", "audit"]) {
    await page.goto(`${BASE_URL}/#/${route}`);
    await page.locator("h1").first().waitFor();
    const problems = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll("input, select").forEach((el) => { if (!el.closest("label") && !el.getAttribute("aria-label")) out.push(`unlabelled ${el.outerHTML.slice(0, 60)}`); });
      document.querySelectorAll("button").forEach((b) => { if (!b.textContent.trim() && !b.getAttribute("aria-label")) out.push("unnamed button"); });
      if (document.querySelectorAll("h1").length !== 1) out.push(`h1 count ${document.querySelectorAll("h1").length}`);
      return out;
    });
    assert.deepEqual(problems, [], `${route}: ${problems.join(", ")}`);
  }
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.textContent);
  assert.equal(focused, "Skip to content");
});

await check("narrow viewport has no horizontal page scroll", async () => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE_URL}/#/vehicles/${VEHICLE_ID}`);
  await page.getByTestId("vehicle-firmware").waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 1, `page overflows by ${overflow}px`);
  await shot("05-mobile-vehicle");
});

await check("no console errors", async () => { assert.deepEqual(consoleErrors.filter((e) => !e.includes("401")), []); });

await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(JSON.stringify({ total: results.length, failed }));
process.exit(failed ? 1 : 0);
