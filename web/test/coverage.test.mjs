import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, readdir, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { build } from "esbuild";
import { coverageReport, sourcePath } from "../../scripts/coverage-report.mjs";

test("LCOV preserves measured execution and uncovered code, rejects changed browser source", async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), "radhouse-coverage-")));
  try {
    const directory = join(root, "coverage");
    const file = join(root, "src/radhouse/chat/static/chat.js");
    const source = "function used() { return 1; }\nfunction unused() { return 2; }\nused();\n";
    await mkdir(join(root, "src/radhouse/chat/static"), { recursive: true });
    await mkdir(join(directory, "browser"), { recursive: true });
    await mkdir(join(directory, "node"));
    await writeFile(file, source);
    const child = spawnSync(process.execPath, [file], {
      env: { ...process.env, NODE_V8_COVERAGE: join(directory, "node") }, encoding: "utf8"
    });
    assert.equal(child.status, 0, child.stderr);
    const files = await readdir(join(directory, "node"));
    const data = JSON.parse(await readFile(join(directory, "node", files[0]), "utf8"));
    const measured = data.result.find(entry => (entry.url === pathToFileURL(file).href || entry.url === file));
    assert.ok(measured);
    await writeFile(join(directory, "browser/entry.json"), JSON.stringify({ result: [{ ...measured, url: "/chat.js", source }] }));
    await coverageReport(directory, root);
    const lcov = await readFile(join(directory, "lcov.info"), "utf8");
    assert.match(lcov, /SF:src\/radhouse\/chat\/static\/chat.js/);
    assert.match(lcov, /DA:2,0/);
    assert.match(lcov, /DA:3,[1-9]/);
    await writeFile(file, source + "// altered source\n");
    await assert.rejects(coverageReport(directory, root), /source differs/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("coverage ignores dependency and unrelated script URLs", () => {
  assert.equal(sourcePath("file:///tmp/vendor/node_modules/library.js"), null);
  assert.equal(sourcePath("/unrelated.js"), null);
  assert.ok(sourcePath("/app/dist/main.js").endsWith("/web/dist/main.js"));
});

test("bundle source maps retain uncovered TypeScript branches", async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), "radhouse-ts-coverage-")));
  try {
    const directory = join(root, "coverage");
    const input = join(root, "web/src/main.ts");
    const output = join(root, "web/dist/main.js");
    await mkdir(join(root, "web/src"), { recursive: true });
    await mkdir(join(directory, "browser"), { recursive: true });
    await mkdir(join(directory, "node"));
    await writeFile(input, "const flag = process.argv.includes('missing');\nif (flag) {\n  console.log('uncovered');\n} else {\n  console.log('covered');\n}\n");
    await build({ entryPoints: [input], outfile: output, bundle: true, sourcemap: true, platform: "node" });
    const child = spawnSync(process.execPath, [output], {
      env: { ...process.env, NODE_V8_COVERAGE: join(directory, "node") }, encoding: "utf8"
    });
    assert.equal(child.status, 0, child.stderr);
    await writeFile(join(directory, "browser/empty.json"), JSON.stringify({ result: [] }));
    await coverageReport(directory, root);
    const lcov = await readFile(join(directory, "lcov.info"), "utf8");
    assert.match(lcov, /SF:web\/src\/main.ts/);
    assert.match(lcov, /DA:3,0/);
    assert.match(lcov, /DA:5,[1-9]/);
  } finally { await rm(root, { recursive: true, force: true }); }
});
