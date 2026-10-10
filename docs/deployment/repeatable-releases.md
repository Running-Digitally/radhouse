# Repeatable private releases

`scripts/release.py` separates portable source qualification from an installation's
private settings, approval and evidence. Source preparation runs offline. The
server-local apply path currently supports **static web source changes only**.
Application Python, native/Hermes, schema, dependency, vendored-library and deployment
configuration changes receive an actionable plan and a source packet, but apply
refuses them. They still require a separately qualified release lane.

No command SSHes to a host, creates credentials, installs dependencies, invokes a
model, restarts Hermes, restores a database or automatically selects older code.
The operator transports the packet and reviewed helper using an already authorized
private mechanism. Running an offline command never grants live deployment authority.
The older supplied-VM installer remains a different installation workflow; its
upgrade/rollback behavior is not inherited by this static lane.

## Public and private boundary

The public repository contains this helper, a synthetic `.env.example`, portable
tests and product source. Actual profiles, addresses, machine identity, service
identities, control pins, approvals, snapshots and receipts belong in a private
repository or ignored directories. `.env`, `.env.*`, `.releases/` and
`.release-private/` are ignored; `.env.example` is explicitly retained.

Create a mode-0600 placeholder profile without overwriting an existing one:

```sh
python3 scripts/release.py init-profile --output .env
mkdir -p .releases .release-private
chmod 0700 .releases .release-private
```

Do not source the file as shell code. The parser accepts literal `KEY=value` lines
and comments; it performs no variable substitution or command execution. Populate
all required fields privately. The origin must be HTTPS with no embedded credentials.
The service must have an unprivileged user and UID. Evidence and data roots must be
separate from the release root. Credentials remain in the existing protected API
configuration, referenced by filename rather than copied into the release profile.

On the target, the profile and authority must belong to the invoking root identity
and have mode 0600. The release root must already exist with root ownership and no
writable group/other ancestors; the evidence root must additionally have mode 0700.
Data and originals must remain mode 0600 files / mode 0700 directory owned by the
configured service UID. Paths with symlink ancestors are refused. The helper creates
no standing privileged access and executes only fixed API systemd operations.

The baseline unit must already run from the versioned baseline release directory
and contain exactly one `Environment=RADHOUSE_RELEASE_COMMIT=<baseline>` marker.
The existing interpreter/launcher must live outside the source release directory;
a baseline-local `.venv` is refused because this lane never builds one.
Only that directory and marker are rewritten; interpreter, configuration, TLS,
sandbox and all other unit settings stay as qualified. A unit which uses an unrelated
`current` symlink must be deliberately onboarded before this lane can apply.

`RADHOUSE_CONTROLS_FILE` references a private mode-0600 JSON array that freezes
installation configuration, TLS CA, existing interpreter/launcher, tunnel and
native-policy files. Every entry has this synthetic shape:

```json
[
  {
    "path": "/etc/example-app/tls/ca.crt",
    "sha256": "REPLACE_WITH_FULL_SHA256",
    "uid": 0,
    "mode": "0644"
  }
]
```

Pin the controls file itself with `RADHOUSE_CONTROLS_SHA256`; replacing the list
is a new profile/approval, even if the edited list matches new file contents.
The configured CA must be included. The API unit is pinned separately and must not
appear as a fixed control. Pin every standing execution dependency and private
configuration involved in the qualified baseline. A changed digest or mode stops
the release. SHA-256 digests are integrity pins, not credentials.

If the existing source release contains an already qualified `vendor/` tree, use
the optional `RADHOUSE_RETAINED_FILES_FILE` and matching digest. The private JSON
object maps every retained `vendor/...` file to its SHA-256. Apply verifies and copies
those exact files unchanged from the baseline; it installs no dependencies. Unknown
release files, symlinks and unpinned vendor changes stop the process.

Record the private SQLite schema digest during reviewed onboarding, using the same
canonical encoding as the helper: SHA-256 of sorted compact JSON plus newline with
keys `version` (`PRAGMA user_version`) and `objects` (rows from `SELECT
type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name`). This digest must stay
unchanged in the supported lane. Application-level data remain private and are never
printed. Root onboarding, service confinement and the original baseline's runtime
qualification must be established separately; this tool does not create them.

The loaded systemd unit must match the pinned API unit, and every active drop-in
must be included in private control pins. Service selection is checked before stop.
An execution-link control may add `symlink_target`: pin each exact literal link
hop and the final regular file using its digest, with root-owned protected
ancestors. Changed links and missing chain pins refuse deployment.

## Run the offline candidate workflow

For a committed static web change, `scripts/release_candidate.py` runs the reviewed
conservative gate plan and packages the resulting source. `--plan-only` identifies
required gates without checking dependencies, creating evidence or executing tests.
Both modes require clean exact `HEAD` descended from the specified baseline; the
running runner and helper must match their frozen committed bytes.

```sh
python3 scripts/release_candidate.py --baseline FULL_BASELINE_COMMIT --plan-only
python3 scripts/release_candidate.py --baseline FULL_BASELINE_COMMIT
```

Every static candidate runs the same conservative plan:

- Portable synthetic chat/API tests covering chat continuity, attachments, saved
  profile, Library, browser, terminal, About You and inference; release/helper,
  privacy and candidate-runner tests are included.
- Syntax checks for every tracked first-party static JavaScript file, plus the
  chat-client and formatting Node unit tests.
- Existing synthetic browser journeys for the interface, navigation, saved profile,
  appearance/readability, Library, owner terminal, inference controls, About You
  and browser session control. These exercise fixtures and loopback servers;
  they never contact deployed Hermes, a provider or an installation target.
- The existing public-source privacy gate, with an optional ignored private policy.
  This checks current candidate source and honors that policy; it does not reopen
  the owner's accepted historical metadata disposition or rewrite history.

The runner preflights existing dependencies and never downloads or installs them.
It requires Python 3.14 with project/test imports (including `pypdf` for attachment
proofs), Node.js 20.19 or newer, the repository-pinned Playwright version and an
existing Chromium binary/cache. Supply explicit existing locations when they live
outside the checkout:

```sh
python3 scripts/release_candidate.py --baseline FULL_BASELINE_COMMIT \
  --python /absolute/existing/python \
  --node /absolute/existing/node \
  --playwright-module /absolute/existing/playwright/index.mjs \
  --chromium /absolute/existing/chromium \
  --private-policy .release-private/public-source-policy.json
```

`--browsers-path` can select an existing Playwright cache instead of an explicit
Chromium binary. `--profile .env` optionally validates private release settings
and their baseline offline; its values are never inherited by test processes.
Production configuration, provider keys, proxies, fixture/database grants, Node
options and pytest/plugin options are excluded from the child's environment.
Required pytest skips, empty test results, Node skips/todos/cancellations, missing
journeys, nonzero exits and timeouts prevent qualification.

By default, the output is `.release-private/candidate-<full-candidate-commit>/`.
`--output` may choose an exclusive ignored or external directory; an existing run
is never overwritten. The private directory is mode 0700 and its evidence/logs
are mode 0600. An explicit private privacy policy is frozen into a mode-0600 snapshot before
execution and its hash is checked before/after gates; the original file is never
reread by the privacy child. Policy and private-identifier digests are retained
only in private qualification evidence.
It contains `qualification.json`, timed per-gate logs/results,
`packet/source.tar`, `packet/manifest.json`, and `candidate.json` with consolidated
qualification/manifest/archive/runner/helper pins. Console output contains bounded
gate progress, duration and the final source/pin summary, without local tool paths
or installation details. This is executed local evidence, not a CI-authenticated
attestation.

The runner rechecks exact clean source and tool custody before and after gates and
before returning a ready result. A source change or failed mandatory gate records
failure and never returns a ready candidate. Unsupported backend, native, schema,
dependency and deployment changes are routed to separate qualification before
executing this static plan. No authority template is approved, no privilege is
granted and no apply command runs. Use the emitted packet and pins in the existing
private owner-authority workflow below.

## Freeze and qualify a source revision

Use a clean checkout at a full 40-character commit descended from the reviewed
baseline. Dirty tracked files and untracked files refuse source preparation; ignored
private profiles and evidence are permitted.

```sh
python3 scripts/release.py plan --source . \
  --revision FULL_CANDIDATE_COMMIT --baseline FULL_BASELINE_COMMIT
```

The result identifies the lane and whether apply supports it. Native and dependency
changes remain visible in that result even though they are not in the deployable
`src/radhouse/` payload. The source tar contains only tracked regular files below
that explicit prefix. Its sorted member order, modes, owners and timestamps are
deterministic. Symlinks, submodules, traversal and oversized members are refused.

Run the repository privacy gate with an ignored private policy before publishing:

```sh
python3 scripts/public_privacy.py --source . \
  --private-policy .release-private/public-source-policy.json
```

The private JSON policy contains a `deny_literals` list of installation identifiers.
The gate checks publishable working source and supported asset metadata (including
PNG text and compressed Blender content), prints only sanitized paths/categories,
and exits nonzero on a finding. Add its passing result to qualification as
`public-source-privacy`. The gate does not rewrite Git history or certify that no
unknown sensitive identifier exists. Keep the policy and its diagnostics private.

Run the remaining repository checks appropriate to the actual change, including its
browser behavior, then retain a qualification receipt privately:

```json
{
  "source_revision": "FULL_CANDIDATE_COMMIT",
  "state": "qualified",
  "lane": "static-web",
  "checks": [
    {"name": "appearance-browser", "passed": true},
    {"name": "chat-client-tests", "passed": true}
  ]
}
```

These are examples, not an assertion that tests passed. The helper requires the
exact qualification receipt digest, candidate revision and passing check names. It
copies only bounded generic check names, not logs, descriptions or private paths.
Qualification must come from actual executed checks; this tool does not manufacture
or authenticate a CI attestation.

```sh
python3 scripts/release.py prepare --source . \
  --revision FULL_CANDIDATE_COMMIT --baseline FULL_BASELINE_COMMIT \
  --qualification .release-private/qualification.json \
  --qualification-sha256 QUALIFICATION_SHA256 \
  --output .releases/candidate

python3 scripts/release.py check --packet .releases/candidate \
  --manifest-sha256 MANIFEST_SHA256 --profile .env
```

`prepare` emits a checksummed `source.tar` and manifest; it prints the manifest pin
without private settings. `check` verifies exact helper, manifest, archive and member
custody and validates the profile offline. Unsupported lanes can still be frozen
for review; their manifest says `apply_supported: false`.

Preparation rejects common private addresses, private hostnames, personal home
paths and recognizable credential patterns without echoing the value. An optional
`--private-identifiers-file` (mode 0600, one privately known identifier per line)
adds installation-specific rejection. This is a bounded artifact guard, not a
complete secret scan or Git-history privacy audit. Review source and history before
publishing; keeping a file ignored does not remove earlier committed copies.

## Review authority and apply on the target

Create a private template after reviewing the qualified packet and profile:

```sh
python3 scripts/release.py authority-template --packet .releases/candidate \
  --manifest-sha256 MANIFEST_SHA256 --profile .env \
  --output .release-private/authority.json
```

An explicit owner decision must set `state` to `explicit-owner-go`, provide a private
`decision_locator`, and record timezone-aware `approved_at` and `expires_at`. The
window can be at most 90 minutes. `max_attempts` is bounded to 1–3 and defaults to 2.
The approval binds exact source/baseline, manifest, helper and complete private
profile; any edit requires a newly reviewed pin. A JSON state is a custody record,
not a replacement for the owner's actual approval. No template command approves
itself.

Transport the exact packet, reviewed helper, profile, referenced private files and
authority through the installation's authorized process. The attended server-local
command shape is:

```sh
sudo python3 scripts/release.py apply --packet PRIVATE_PACKET_DIRECTORY \
  --manifest-sha256 MANIFEST_SHA256 --profile PRIVATE_PROFILE_FILE \
  --authority PRIVATE_AUTHORITY_FILE --authority-sha256 AUTHORITY_SHA256
```

Apply verifies Linux/root identity and pinned machine identity, service unit,
private controls and exact baseline source. It refuses active or uncertain owner
work and unfinished uploads before stopping anything. Prepared turns which have
never been dispatched are retained. It stages immutable candidate source, stops
only the API and verifies the stopped service/cgroup, rechecks owner state, creates
a consistent private SQLite snapshot, and verifies row/original-file inventories.
It then selects the candidate unit, starts the API, checks trusted HTTPS health,
unauthenticated denials and exact served asset bytes, and proves retained SQLite
rows and originals. It dispatches no owner work and makes no generation request.

The changed static files must be among the currently served asset routes. A newly
introduced asset route requires backend qualification and therefore belongs in a
separate lane. Verification includes all supported static routes, not just the
changed files. Source/member/response limits are 16 MiB each; archive, database and
original-file reads are bounded to 128 MiB. Larger installations need a deliberately
qualified streaming inventory implementation before using this lane.

Private receipts, snapshots, baseline unit and the journal live under the configured
evidence root keyed by manifest digest. Console results expose bounded state,
revision, fixed refusal reason and receipt digest. They contain no installation
settings, secret values, SQL rows, original filenames or raw child-process output.
`status` is explicitly read-only and makes no HTTPS call:

```sh
sudo python3 scripts/release.py status --packet PRIVATE_PACKET_DIRECTORY \
  --manifest-sha256 MANIFEST_SHA256 --profile PRIVATE_PROFILE_FILE
```

## Diagnose and recover forward

A service/startup/HTTPS failure or busy-owner refusal produces a private failed
receipt and preserves the current selection, snapshots and data. After diagnosing
and resolving the failure within the exact approved scope, rerun `apply` with an
explicit generic label such as `--retry-reason resolved-api-startup`. Attempts are
bounded by the still-live authority. Apply does not silently loop, restore SQLite
or auto rollback. A retry must retain the original owner-state proof; it cannot
rebaseline away loss of rows or originals.

Unknown drift, integrity errors, schema changes and unexpected failures fence the
journal and require explicit reconciliation. If the API has already stopped or the
new unit was selected, the failed receipt names that phase; it stays there for
attended diagnosis. A new source revision or profile requires new qualification and
authority. Incomplete deployment retries retain exact original-state comparisons.
After successful completion, `verify` (or a repeated `apply`) checks the immutable
code/unit/private controls, served assets and retained
snapshot digest while preserving the historical release retention proof. Legitimate
subsequent owner messages, attachments and in-flight uploads do not falsely invalidate
that completed proof. Private receipts identify `retention_scope` as
`current-release-retention` during deployment or `historical-release-proof` for
completed rechecks, and retain `snapshot_sha256`. Rechecking never fabricates a
missing snapshot or retention proof.

Post-release operational records belong in the private deployment repository. Use
the receipt digest and frozen source revision to link them to the public source;
do not copy private receipts, screenshots, hostnames or topology into public PRs.
