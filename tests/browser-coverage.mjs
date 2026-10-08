import { mkdir, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { join } from "node:path";

const pages = new Set();

// Opt in only inside the owned test run. Coverage spans reloads and sign-outs.
export async function cover(page) {
  if (!process.env.RADHOUSE_COVERAGE_DIR) return;
  await page.coverage.startJSCoverage({ resetOnNavigation: false });
  pages.add(page);
}

export async function closePage(page) {
  try { await savePage(page); }
  finally { await page.close(); }
}

async function savePage(page) {
  if (!pages.has(page)) return;
  const directory = process.env.RADHOUSE_COVERAGE_DIR;
  if (page.isClosed()) throw new Error("Browser closed before collecting coverage");
  await mkdir(directory, { recursive: true });
  const entries = await page.coverage.stopJSCoverage();
  const result = entries.filter(entry => entry.url && new URL(entry.url).pathname.endsWith(".js"));
  for (const entry of result) {
    entry.url = new URL(entry.url).pathname;
  }
  await writeFile(join(directory, `${randomUUID()}.json`), JSON.stringify({ result }));
  pages.delete(page);
}

async function saveCoverage() {
  const directory = process.env.RADHOUSE_COVERAGE_DIR;
  if (!directory) return;
  for (const page of pages) await savePage(page);
}

export async function closeBrowser(browser) {
  try { await saveCoverage(); }
  finally { await browser.close(); }
}
