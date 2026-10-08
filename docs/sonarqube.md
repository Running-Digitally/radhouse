# Local SonarQube analysis after merge

Radhouse uses SonarQube Community Build to check merged code for security,
reliability, maintainability and duplication issues. Run the scanner on the
local development laptop after committing and merging changes into GitHub's
`main` branch. This integration uses no GitHub Actions runner or PR analysis.

The rationale, scope and review triggers are recorded in
[ADR-0001](decisions/0001-local-post-merge-sonarqube-analysis.md).

Community Build supports analysis of one main branch. The launcher clones only
`origin/main` into a temporary directory, verifies the merged commit before
submitting, and records that SHA in SonarQube and a local receipt. Running it
from a feature branch or a dirty development checkout still analyzes only the
merged remote source. A merge during preparation stops the command; rerun it.
The temporary clone is removed afterward. Full Git history is retained during
analysis for source blame and new-code attribution.

## One-time local setup

Install the official [SonarScanner CLI](https://docs.sonarsource.com/sonarqube-community-build/analyzing-source-code/scanners/sonarscanner).
Use the macOS AArch64 package on Apple Silicon. The first qualification used
CLI `8.1.0.6389`, including its bundled Java runtime. Python 3.11 or newer and
Git with access to the repository's origin are required for the launcher. The
coverage lane also needs uv, Node.js/npm, the intended local Docker daemon and
a Playwright Chromium installation. It uses the reviewed lockfiles and the
existing owned PostgreSQL fixture; remote Docker/PostgreSQL overrides are refused.

Create a project named **Radhouse**, key `Running-Digitally_radhouse`, with main
branch `main`. Keep the instance's existing quality gate, language profiles
and new-code definition. Create a **project analysis token** for this project;
it does not need global analysis or server administration access.

Provide the token through `SONAR_TOKEN`, or store it in macOS Keychain as a
generic password with service `radhouse-sonarqube` and account `local-analysis`.
Set an expiry and renew it when needed. Keep credentials out of source files,
Git, shell command arguments and scan receipts.

Set `SONAR_HOST_URL` to the HTTPS address of your SonarQube instance. Add the
scanner's `bin` directory to `PATH`, or supply `--scanner /path/to/sonar-scanner`.

## After each merge

An explicit owner scan request uses the established destination/payload approval
in [the Codex capability record](codex-capabilities.md). Project-scoped reviewer
context preserves that scope without changing global approvals or networking.

From the repository on the local laptop:

```sh
python3 scripts/sonarqube.py --dry-run
python3 scripts/sonarqube.py
```

The dry run reads the current remote main SHA without publishing. The normal
command waits for server processing and the quality gate. A nonzero exit means
a prerequisite, analysis, server-processing or quality-gate failure; inspect
the scanner log and project dashboard rather than treating upload as a pass.
Receipts, redacted logs and the server task locator remain under `.sonarqube/`.
There is no automatic scheduler or Git hook; run the command after a merge.

The scan covers first-party Python, TypeScript, JavaScript, CSS, HTML and
supported configuration files under `src`, `scripts`, `web`, `site` and `deploy`.
Test source is classified separately. Generated builds, dependency trees and
vendored third-party site code are excluded. Exclusions do not suppress
first-party security findings.

The normal command first installs locked development dependencies in the fresh
merged clone, builds web sources with source maps, and runs
`uv run --frozen python scripts/vs0.py verify --coverage`. That run executes the
Python suite, real browser walkthroughs and web/Node tests against synthetic
data and its exclusively owned local PostgreSQL fixture. Python subprocess
coverage is combined where the process can write a report. The document
parser keeps its production no-file-write limit; direct parser contract tests
provide its measured coverage alongside existing isolated subprocess tests. Chromium and Node execution are converted to LCOV for
the tested first-party JavaScript and original TypeScript.

Only reports from the matching commit, a successful test run with no skips and
completed fixture cleanup are imported. Report paths and SHA256 digests must
match that run. Source changes, failed tests, missing/tampered reports or a main
merge during preparation stop analysis. The token is supplied only to the
scanner, not dependency installation or tests. Receipts retain the verification
manifest and supplied reports alongside the redacted scanner log.
`test_coverage_submitted` requires the upload task locator;
`test_coverage_imported` is a positive confirmation only after a successful
scanner result with that locator. A failed submitted analysis retains submission
evidence with import unconfirmed, including a processing or quality-gate failure.

For a deliberate diagnostic without tests, use `--static-only`; its receipt
explicitly records that coverage was not imported. Missing coverage data does
not measure test quality. To qualify a feature branch locally without publishing
it to SonarQube, run `uv run python scripts/vs0.py verify --coverage` in the
branch and inspect that run's `.vs0/<run-id>/coverage/` reports. The Community
Build main project is updated only after the owner merges the reviewed changes.

This lane retains the existing gate, profiles and new-code definition. It does
not suppress first-party issues, exclude uncovered first-party code, audit all
dependencies or mark security hotspots safe. The qualified Community Build
warns that it does not detect critical injection vulnerabilities such as SQL
injection and XSS. Keep appropriate independent security review and dependency
auditing. Findings on main require fixes through the normal review/merge process,
followed by another local scan.

See the official [Community Build feature comparison](https://docs.sonarsource.com/sonarqube-community-build/feature-comparison-table)
and [analysis overview](https://docs.sonarsource.com/sonarqube-community-build/analyzing-source-code/analysis-overview).
