# ADR-0001: Run SonarQube analysis locally after merge

Status: accepted maintainer decision; repository integration is proposed in PR #69.

Date: 2026-10-07

## Context

Radhouse needs a repeatable static-analysis baseline for security, reliability
and maintainability findings. The selected SonarQube Community Build supports
analysis of one main branch. Maintainers chose to run this analysis from the
local development laptop after changes are committed and merged into `main`.

Development checkouts can contain unrelated edits or be on feature branches.
Submitting such a checkout to the main project would misrepresent which source
was analyzed. The repository also has a GitHub-hosted default for automated CI;
the scope of this separate maintainer-run analysis needs to be explicit.

## Decision

Use a manually invoked local SonarScanner command for Radhouse's post-merge
static analysis. The launcher clones remote `origin/main` with its Git history
into a temporary directory, checks that the source is clean and that the remote
main commit stayed consistent during preparation, and records the scanned SHA.
Its input is the merged remote source even when invoked from a dirty checkout
or feature branch.

The scanner submits to the project's single main-branch analysis and waits for
server processing and the quality gate. Analysis or gate failures produce a
nonzero exit. Keep the task locator, redacted scanner log and source receipt in
ignored local evidence. Remove the temporary source checkout afterward.

Use a project-scoped analysis token through the environment or the local
credential store. Keep it out of Git and command-line arguments. Continue using
the existing language profiles, quality gate and new-code policy.

This decision applies to this repository's maintainer-run SonarQube command.
The [automated CI hosting policy](../ci-and-runner-setup.md) continues to govern
ordinary CI and product onboarding. This command installs no hosted runner,
automatic scheduler or Git hook.

## Alternatives considered

- GitHub-hosted analysis could automate execution, but the selected workflow
  uses the existing local development computer and project credential.
- Scanning the current checkout is simpler, but risks attributing unmerged or
  dirty source to the project's main branch.
- Branch or pull-request analysis would require a separately supported setup
  beyond the selected Community Build capability.

## Consequences

Maintainers must invoke the command after each merge. An offline laptop or a
missed invocation delays the dashboard update. The SHA identifies the analyzed
commit; later merges need another scan.

SonarQube results arrive after merge and cannot serve as this lane's pre-merge
check. Candidate fixes need appropriate local tests and review before merge;
their SonarQube verification follows afterward. A passed quality gate can
coexist with outstanding baseline findings, which still require triage.

The initial command performs static analysis without executing tests, importing
coverage or auditing dependencies. Missing coverage data is not measured test
coverage. The qualified Community Build also excludes critical injection
analysis such as SQL injection and XSS. Keep independent testing and security
review appropriate to the change; the dashboard alone establishes no complete
security assurance.

## Validation and review

The launcher has isolated checks for merged-main selection from a dirty feature
checkout, scanner failure propagation, dry-run behavior, hosted-CI rejection,
scanner override rejection and a missing main branch. A local analysis of
merged main completed successfully on 2026-10-07. Implementation and operating
instructions are in the [SonarQube runbook](../sonarqube.md).

Revisit this decision if analysis moves to an automated runner, the available
edition supports additional branches, or this lane gains test/coverage reporting.
Any revised flow must preserve accurate source attribution and scoped credentials.

References: [Community Build features](https://docs.sonarsource.com/sonarqube-community-build/feature-comparison-table),
[analysis overview](https://docs.sonarsource.com/sonarqube-community-build/analyzing-source-code/analysis-overview),
and [setup PR #69](https://github.com/Running-Digitally/radhouse/pull/69).
