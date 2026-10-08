import { readdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(join(root, "web/package.json"));
const v8ToIstanbul = require("v8-to-istanbul");
const { createCoverageMap } = require("istanbul-lib-coverage");
const { createContext } = require("istanbul-lib-report");
const reports = require("istanbul-reports");
const staticNames = new Set(["chat.js", "format.js", "browser-view.js", "admin.js"]);

function within(path, base) {
  const name = relative(base, path);
  return name !== ".." && !name.startsWith(`..${sep}`) && !name.startsWith(sep);
}

export function sourcePath(url, sourceRoot = root) {
  if (["/app/main.js", "/app/dist/main.js"].includes(url)) return join(sourceRoot, "web/dist/main.js");
  const name = url.slice(1);
  if (staticNames.has(name)) return join(sourceRoot, "src/radhouse/chat/static", name);
  if (url.startsWith("file:") || isAbsolute(url)) {
    const path = url.startsWith("file:") ? fileURLToPath(url) : url;
    return within(path, join(sourceRoot, "src/radhouse/chat/static")) || within(path, join(sourceRoot, "web/dist"))
      ? path : null;
  }
  return null;
}

function firstParty(path, sourceRoot) {
  return within(path, join(sourceRoot, "web/src")) || within(path, join(sourceRoot, "src/radhouse/chat/static"));
}

async function addEntry(map, entry, sourceRoot) {
  const path = sourcePath(entry.url, sourceRoot);
  if (!path) return;
  const source = await readFile(path, "utf8");
  if (entry.source !== undefined && entry.source !== source) throw new Error(`Coverage source differs: ${relative(sourceRoot, path)}`);
  const converter = v8ToIstanbul(path, 0, { source });
  try {
    await converter.load();
    converter.applyCoverage(entry.functions);
    for (const [mappedPath, coverage] of Object.entries(converter.toIstanbul())) {
      if (firstParty(mappedPath, sourceRoot)) map.merge({ [mappedPath]: coverage });
    }
  } finally { converter.destroy(); }
}

export async function coverageReport(directory, sourceRoot = root) {
  const map = createCoverageMap({});
  for (const name of ["browser", "node"]) {
    const folder = join(directory, name);
    const files = await readdir(folder);
    if (!files.some(file => file.endsWith(".json"))) throw new Error(`Missing ${name} coverage`);
    for (const file of files.filter(file => file.endsWith(".json")).sort()) {
      const data = JSON.parse(await readFile(join(folder, file), "utf8"));
      for (const entry of data.result) await addEntry(map, entry, sourceRoot);
    }
  }
  if (!map.files().length) throw new Error("No first-party JavaScript coverage collected");
  const context = createContext({ dir: directory, coverageMap: map });
  reports.create("lcovonly").execute(context);
  const lcov = await readFile(join(directory, "lcov.info"), "utf8");
  const normalized = lcov.replace(/^SF:(.+)$/gm, (_, path) => {
    const absolute = resolve(path);
    if (!firstParty(absolute, sourceRoot)) throw new Error("Coverage contains a foreign source path");
    return `SF:${relative(sourceRoot, absolute).split(sep).join("/")}`;
  });
  await writeFile(join(directory, "lcov.info"), normalized);
  await writeFile(join(directory, "javascript-summary.json"), JSON.stringify(map.getCoverageSummary().toJSON(), null, 2) + "\n");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await coverageReport(resolve(process.argv[2]));
}
