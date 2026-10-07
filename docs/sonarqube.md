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
Git with access to the repository's origin are required for the launcher.

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

This command performs **static analysis**. It does not execute the application
test suite, generate test coverage or audit dependency vulnerabilities.
Coverage displayed without an imported report is not evidence of test quality.
The qualified Community Build also warns that it does not detect critical
injection vulnerabilities such as SQL injection and XSS; this lane is a limited
security check and does not establish application security.
Continue to use the owned local fixture (`uv run python scripts/vs0.py verify`)
and web tests independently. Review security hotspots in SonarQube; an analysis
alone does not mark them safe. Findings on main require fixes through the normal
review/merge process, followed by another local scan.

See the official [Community Build feature comparison](https://docs.sonarsource.com/sonarqube-community-build/feature-comparison-table)
and [analysis overview](https://docs.sonarsource.com/sonarqube-community-build/analyzing-source-code/analysis-overview).
