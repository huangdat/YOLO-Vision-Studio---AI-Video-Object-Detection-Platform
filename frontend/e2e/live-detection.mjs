// Status: written for the hybrid-tracking work; NOT yet run (blocked by low host memory, see
// docs/hybrid-tracking-gpu-architecture.md). Requires Playwright with Chromium installed separately:
//   npm i -D playwright && npx playwright install chromium
// Real-browser Live Detection check (Chromium with a fake camera fed from a sample street clip).
//   node live-e2e.mjs <baseUrl> <mode: off|client|server> <seconds> <outDir> <fakeVideo.mjpeg>
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

await page.goto(`${baseUrl}/live`, { waitUntil: "networkidle" });
await page.getByRole("button", { name: /Start Live Detection/ }).waitFor({ timeout: 30000 });
if (mode !== "off") {
  await page.getByRole("switch", { name: /Object tracking/ }).check();
  await page.getByRole("radio", { name: mode === "client" ? /Browser/ : /Server/ }).check();
}
await page.getByRole("button", { name: /Start Live Detection/ }).click();
await page.getByText("Detecting live").waitFor({ timeout: 60000 });
await page.waitForTimeout(Number(seconds) * 1000);

const metrics = await page.$$eval(".live-metrics > div", (items) =>
  Object.fromEntries(items.map((item) => [item.querySelector("dt")?.textContent?.trim(),
    item.querySelector("dd")?.textContent?.trim()])));
// The overlay is a canvas: check it has drawn pixels (boxes/labels), not just that it exists.
const overlayPixels = await page.evaluate(() => {
  const canvas = document.querySelector("canvas");
  if (!canvas || !canvas.width) return 0;
  const data = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
  let painted = 0;
  for (let i = 3; i < data.length; i += 4) if (data[i] > 0) painted++;
  return painted;
});
await page.screenshot({ path: `${outDir}/live-${mode}.png` });
await page.getByRole("button", { name: "Stop" }).click();
await page.getByText("Camera off").waitFor({ timeout: 15000 });
const notice = await page.locator('[role="alert"], [role="status"]').allTextContents();

const report = { mode, seconds: Number(seconds), metrics, overlayPixels, workers, consoleErrors, notice };
fs.writeFileSync(`${outDir}/live-${mode}.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
await browser.close();
