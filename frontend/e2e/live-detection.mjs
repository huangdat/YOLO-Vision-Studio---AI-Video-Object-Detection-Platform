// Real-browser Live Detection check: Chromium with a fake camera fed from a video file (MJPEG or Y4M),
// against a running stack (frontend -> Spring Boot -> live worker). Requires Playwright with Chromium,
// installed separately (not a project dependency):
//   npm i -D playwright && npx playwright install chromium
// Usage:
//   node live-detection.mjs <baseUrl> <mode: off|client|server> <seconds> <outDir> <fakeVideo>
// It starts a session, records the metrics tiles and whether the overlay canvas has drawn pixels,
// resizes the window (the overlay must follow), stops, starts again (restart), and stops again.
// Exit code 1 when a check fails. Results go to <outDir>/live-<mode>.json and screenshots.
import { chromium } from "playwright";
import fs from "node:fs";

const [baseUrl, mode, seconds, outDir, video] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch({
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    `--use-file-for-fake-video-capture=${video}`,
  ],
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ["camera"] });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
page.on("pageerror", (error) => consoleErrors.push(String(error)));
const workers = [];
page.on("worker", (worker) => workers.push(worker.url()));

const metrics = () => page.$$eval(".live-metrics > div", (items) =>
  Object.fromEntries(items.map((item) => [item.querySelector("dt")?.textContent?.trim(),
    item.querySelector("dd")?.textContent?.trim()])));

// The overlay is a canvas: count drawn pixels (boxes/labels) and check its backing store matches its
// CSS size at the device pixel ratio.
const overlay = () => page.evaluate(() => {
  const canvas = document.querySelector("canvas");
  if (!canvas || !canvas.width) return { painted: 0 };
  const data = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
  let painted = 0;
  for (let i = 3; i < data.length; i += 4) if (data[i] > 0) painted++;
  const ratio = window.devicePixelRatio || 1;
  return { painted, width: canvas.width, height: canvas.height,
    sized: canvas.width === Math.round(canvas.clientWidth * ratio)
      && canvas.height === Math.round(canvas.clientHeight * ratio) };
});

async function startSession() {
  await page.getByRole("button", { name: /Start Live Detection/ }).click();
  try {
    await page.getByText("Detecting live").waitFor({ timeout: 60000 });
  } catch (error) {
    await page.screenshot({ path: `${outDir}/live-${mode}-start-failed.png` });
    const alerts = await page.locator('[role="alert"], [role="status"]').allTextContents();
    console.error(JSON.stringify({ startFailed: true, alerts, consoleErrors }));
    throw error;
  }
}

async function stopSession() {
  await page.getByRole("button", { name: "Stop" }).click();
  await page.getByText("Camera off").waitFor({ timeout: 15000 });
}

await page.goto(`${baseUrl}/live`, { waitUntil: "networkidle" });
await page.getByRole("button", { name: /Start Live Detection/ }).waitFor({ timeout: 30000 });
if (mode !== "off") {
  await page.getByRole("switch", { name: /Object tracking/ }).check();
  await page.getByRole("radio", { name: mode === "client" ? /Browser/ : /Server/ }).check();
}
await startSession();
await page.waitForTimeout(Number(seconds) * 1000);
const first = { metrics: await metrics(), overlay: await overlay() };
await page.locator("canvas").locator("..").screenshot({ path: `${outDir}/live-${mode}.png` });

await page.setViewportSize({ width: 900, height: 900 });
await page.waitForTimeout(1500);
const resized = { overlay: await overlay() };
await page.locator("canvas").locator("..").screenshot({ path: `${outDir}/live-${mode}-resized.png` });
await stopSession();
const afterStop = { overlay: await overlay() };

await startSession();
await page.waitForTimeout(5000);
const restarted = { metrics: await metrics(), overlay: await overlay() };
await stopSession();
const notice = await page.locator('[role="alert"]').allTextContents();

const number = (value) => Number.parseFloat(String(value ?? "").replace(/[^0-9.]/g, "")) || 0;
const checks = {
  framesProcessed: number(first.metrics.Frames) > 0,
  overlayDrawn: first.overlay.painted > 0,
  overlayFollowsResize: resized.overlay.painted > 0 && resized.overlay.sized === true,
  overlayClearedOnStop: afterStop.overlay.painted === 0,
  restartProcessesFrames: number(restarted.metrics.Frames) > 0 && restarted.overlay.painted > 0,
  noConsoleErrors: consoleErrors.length === 0,
  ...(mode === "client" ? {
    trackerWorkerStarted: workers.some((url) => url.includes("tracker")),
    browserTrackingTimed: number(first.metrics["Tracking (browser)"]) > 0,
    activeTracks: number(first.metrics["Active tracks"]) > 0,
  } : {}),
  ...(mode === "server" ? { activeTracks: number(first.metrics["Active tracks"]) > 0 } : {}),
};
const report = { mode, seconds: Number(seconds), first, resized, afterStop, restarted, workers, consoleErrors,
  notice, checks, passed: Object.values(checks).every(Boolean) };
fs.writeFileSync(`${outDir}/live-${mode}.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify({ mode, checks, passed: report.passed, metrics: first.metrics }));
await browser.close();
process.exit(report.passed ? 0 : 1);
