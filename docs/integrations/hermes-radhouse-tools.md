# Native Hermes documents and the shared browser

This is installation and integration source, not evidence of a deployed capability.
The web application grants only saved conversation originals to two native tools and
shows the browser belonging to that same trusted Hermes session. Uploaded files do
not become host paths, generic filesystem permissions, or executable instructions.

## Source composition

`runtime/hermes/source-lock.json` pins Hermes commit
`2237be355906fbe6065ce1815711eee52b2d646e` and the exact composed API inputs after
the eight existing Runs overlays. `overlay.py` refuses different bytes; it preserves
exact allowed tools, provider budgets, durable idempotency and runtime-contract
controls. It also pins the original browser module, session adapter and installer.
Original bounded native functions in `fixtures/` make admission, worker cleanup and
thread propagation tests reproducible without installing another Hermes runtime.
The upstream MIT notice is retained in `fixtures/HERMES-LICENSE.txt`; its digest
matches the original qualified upstream lock.

To prepare an independent tree for review, run:

```sh
python3 -B -I runtime/hermes/overlay.py --source /path/to/qualified-hermes-source --output /path/to/new-rendered-tree
```

This creates source and SHA256 receipts only. An installation must separately verify
the complete upstream/overlay composition, installed owner and permissions, existing
Hermes dependencies, bot profile and rollback source. Install the generated
`radhouse_hermes_bridge.py` next to the pinned Hermes source. The directory plugin's
`plugin.yaml` and `__init__.py` belong in the existing native plugin root. Its toolset
is `radhouse_documents`; the bot profile must include that toolset and the native
browser subset. No MCP server or extra service is required.

The pinned dedicated gateway startup calls `GatewayStartupMixin.start()` →
`_start_recover_previous_run()` → `_start_register_plugins_relay_hooks()` →
`discover_plugins()` before connecting the API adapter. Standalone plugins register
synchronously under that one trusted `HERMES_HOME` profile. Failed registration
leaves the capability false. Constructing an API adapter directly, or using other
profiles, does not establish this ordering; installation must probe the actual bot
profile before the first frontend capability request. Verify the actual gateway's
private `UMask=0077`; the same-session native profile must be owned by the bot and
inaccessible to other users, as checked by the qualification helper.

The public product Python package requires Python3.14. The standalone runtime source
uses Python3.12-compatible standard libraries and the existing Hermes `aiohttp`.
It does not import the web application's package.

## Document handoff

POST `/v1/runs` accepts the private `document_scope_token` only with durable keyed
admission, a session and both exact tools `document_search` and `document_read`.
The opaque bearer is exactly43 URL-safe characters and is included in the existing
whole-request idempotency fingerprint. It is excluded from model instructions,
schemas, agent kwargs, launch repr, run status, events and browser child environment.
Initial durable status contains the trusted `session_id`, exact `allowed_tools` and
`dispatch_key` before background execution. A lost acknowledgement can therefore be
corroborated on the first callback; changing the bearer for the same key conflicts.

The worker binds `DocumentRunContext(run_id,session_id,dispatch_key,scope_token)` in
one ContextVar, resets it on success or exception, and relies on the pinned native
tool-thread propagation. There is no process-environment identity fallback. Tool
execution checks native `task_id`/`session_id` against the trusted context.

```text
document_search(file_id, query, cursor?)
document_read(file_id?, locator?, cursor?)
```

Omitting `file_id` from `document_read` requests a bounded catalog page; its cursor
can continue discovery. A locator without a file is rejected. Arguments cannot
override the trusted context. The bridge calls fixed `/internal/documents/search`
or `/internal/documents/read` with the opaque bearer and flat JSON containing the
trusted context plus model arguments. The web callback validates the durable active
turn and exact native status before and after reading, atomically binds the grant to
one run, and resolves saved file IDs under the owner/conversation scope.

Results are either `{kind:"catalog",files,next_cursor,complete}` or
`{kind:"passages",file_id,sha256,passages,next_cursor,complete,error}`. Original bytes
remain intact. Reads and literal search have bounded parser work and outputs; no
upload size/count ceiling is introduced. PDF page, Word paragraph/table, worksheet
cell and slide locators remain stable. Parser coverage and failures are explicit;
OCR, images, speaker notes and computed workbook recalculation are not implied.

Catalog `sha256` is the expected upload digest, labeled
`sha256_basis:"upload_receipt"`; discovery does not read every original or assert
that its current bytes have been verified. Passage operations hash the retained
regular file inside the existing bounded parser child and parse that same opened
descriptor. A digest mismatch or in-place mutation before parsing finishes denies
the result with `document_source_changed` (409), releasing no passages or cursor.
Full-file verification consumes the operation's existing CPU/wall budget; exhausting
that budget reports `document_operation_exhausted`, without imposing an upload limit.

Native plugin configuration provides `callback_base_url`, `callback_ca_file` and
`callback_tls_server_name`. TCP uses the existing loopback SSH forward. TLS uses the
independently pinned existing web identity `192.168.50.65`, whose certificate SAN
does not include loopback. Certificate chain and hostname checks remain enabled;
redirects and inherited HTTP proxies are rejected. The bearer supplies callback
authority; there is no additional standing callback key.

## Same-session browser

The exact browser surface is:

```text
browser_navigate, browser_snapshot, browser_click, browser_type,
browser_scroll, browser_back, browser_press
```

Click/type target only snapshot refs (`@e1` or `e1`), not selectors or native flags.
The reviewed native patch supports a literal `--` argument boundary; the runtime
puts every executable/config/session/global option before it. Typed text such as
`--config` remains ordinary field text and cannot change native launch settings.

`browser_exec`, shell/file tools, console/eval, raw CDP, personal profiles and browser
uploads are excluded. Scoped calls use a verified native binary and Chromium with
an explicit root-owned `{}` config, a new private native session and scrubbed child
environment. They bypass extension routing, inherited CDP and personal profile
selection, automatic npm installs and Hermes's automatic sandbox-disabling branch.
An unrelated preexisting native record is refused. HTTP(S) navigation can reach LAN
destinations allowed by the VM firewall; reachable services do not become authority
to mutate them.

`GET /v1/runs/{run_id}/browser` returns trusted IDs and
`state:starting|live|idle|unavailable`, nullable `generation` and safe `url`.
`GET /v1/runs/{run_id}/browser-frame` returns:

```json
{"run_id":"...","session_id":"...","generation":"...","frame_id":"...",
 "received_at":0.0,"captured_at":null,"jpeg":"base64"}
```

JPEG output is at most512KiB decoded. One read-only loopback WebSocket listener per
native session/generation retains a bounded actual frame while connected and
screencasting, including stationary pages. It clears on disconnect or generation
change. The viewer never creates a browser or sends input. Run/session/tools/dispatch
and generation are checked before and after each response. URLs omit query/fragment.
`received_at` is trusted relay observation time. `captured_at` is explicitly unknown:
the relay does not establish an independently verified native capture epoch.

The browser feature stays false until a root-owned release manifest contains verified
binary hashes and actual sandbox, same-session frame and origin-isolation canaries.
Published agent-browser0.26.0 has a cross-origin loopback command issue. Published
0.38.2 fixes `/api/command` but still exposes session creation and accepts overly
broad WebSocket Origins. Neither stock release qualifies for activation. A qualified
native release must deny visited-page control through command/session HTTP endpoints
and wrong-origin WebSockets while retaining the read-only relay. No blanket LAN
restriction substitutes for that endpoint boundary.

The additive `browser_network_policy` capability is a sanitized informational
snapshot `{schema,verified,source,verified_at,enforcement:"vm_firewall",allowed,denied}`.
Unknown defaults are explicitly unverified. Verified snapshots require a named source
and timezone-aware date. Lists contain at most16 short summaries, never raw firewall
configuration. Text is printable ASCII; dates more than five minutes in the future
are rejected. The same configured snapshot is appended to trusted system context;
it is neither a model argument nor permission/reachability assertion.

## Weekly lifecycle contract

The source helper `bootstrap.py` is prepared for the existing VM270 role. Fixed verbs
are `maintenance-stage`, `maintenance-qualify`, `maintenance-promote`,
`maintenance-verify` and `maintenance-rollback`, with fixed root policy
`/etc/radhouse/builder-maintenance.json` and bounded sanitized JSON stdin/stdout.
Root copies the exact reviewed native binary identified by its upstream version/npm
integrity, exact upstream source archive digest, view-only patch digest and built binary SHA256. Driver
updates require a separately reviewed pin. Weekly work stages full Chromium support files from an exact official
CfT revision, and freezes archive/executable hashes. Bot qualification runs native
tool equivalents, actual shared-stream frames, stationary viewing, hostile Origin
denials and narrow owned-renderer sandbox evidence. It identifies Chrome only among
the exact native daemon's bounded descendants, reads that owned private profile's
`DevToolsActivePort`, and verifies browser-Origin CDP WebSocket requests are denied
without sending CDP commands. The proof requires `chrome_control_guard_verified`,
`origin_guard_verified`, `view_only_input_ignored`, `same_session_frame_progression`
and `sandbox_enabled`. Root promotion requires all proof
fields and atomically changes `/opt/radhouse-browser/current`. Verification reruns the
real bot canary after native package changes or reboot; old receipt metadata alone
cannot release maintenance. Rollback switches to a retained qualified release.

The root verifier owns the bot canary through its native exit and browser cleanup.
An observation deadline, termination request or failed process-wait diagnostic
does not kill the qualifier. It waits for cleanup and reports an uncertain result,
so the maintenance hold remains in place until reconciliation and a fresh pass.

`runtime_files_sha256` is an exact installed source map. `runtime_sha256` is SHA256 of
its sorted compact JSON (`sort_keys=True,separators=(",",":")`). The helper checks
every mapped installed file. The private root policy also pins helper/orchestrator
sources, target machine, existing Hermes prefix/Python, role and initial artifact
source policy. No hashes or installed qualification are guessed by this repository.
The native policy is `agent_browser_channel:"reviewed"` and
`native_driver:{version,binary_path,binary_sha256,source_sha256,patch_sha256,npm_integrity}`.
No npm, Rust compiler or moving driver install is required on the VM.

The root-owned persistent hold `/var/lib/radhouse-maintenance/hold.json` gates new
native admission before its first await and survives restart/reboot. Malformed,
unknown or policy-drifted holds fail closed. Existing authenticated loopback routes
`GET /v1/maintenance/status`, `POST /v1/maintenance/fence` and
`POST /v1/maintenance/release` report aggregate activity only. Fence/release require
matching cycle and hold digest; the runtime never deletes the hold. Active/unknown
work defers package changes. The root orchestrator releases its own hold only after
the qualified verified restart or acknowledged no-change deferral. Daily OS security
updaters remain in place; no second maintenance service or root broker is introduced.

Local source tests and disposable Linux compatibility evidence do not establish a
VM270 installed browser, firewall rules, certificate-forward route or live model
tool execution. Those remain explicit deployment verification evidence.
