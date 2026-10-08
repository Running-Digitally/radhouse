# Bounded Codex capabilities for Radhouse

## SonarQube scan on request

Owner: Satish. Authorized destination: `https://sonarqube.satishsurath.com`.
Authorized project: `Running-Digitally_radhouse`.
Payload: this repository's committed remote `main` source plus measured Python
and JavaScript coverage from the owned synthetic local PostgreSQL/browser fixture.
The owner explicitly approved the destination and payload on 7 October 2026
and asked for reusable repository capabilities after automatic review required
an extra approval despite the existing scan request.

A future explicit request to scan/rescan invokes this known bounded capability.
It does not start a scheduler or permit analysis when the owner has not requested
it. Use the reviewed local [launcher and runbook](sonarqube.md). The launcher
requires a clean temporary clone of remote main and refuses source movement,
failed/skipped tests, incomplete cleanup and report-digest mismatch. It strips
the analysis token from test and dependency environments and uses HTTPS for
submission. The token remains in macOS Keychain (`radhouse-sonarqube`, account
`local-analysis`) or the documented environment input.

The scan excludes live chats, deployed configuration, credentials, unrelated
local files and other private owner data. Different destinations/projects,
feature-branch analysis, arbitrary uploads, rule/profile/gate changes or issue
suppression require separate authority. Merge and server deployment remain
separate actions with their existing review and recovery requirements.

## Codex configuration and limits

[AGENTS.md](../AGENTS.md) exposes the capability to agents. The project-local
`.codex/config.toml` adds the same exact scope through `auto_review.extra_policy`
for the automatic approval reviewer. It changes no approval mode, sandbox,
network permission or global settings. Codex loads project-local configuration
only for trusted projects; Radhouse is trusted on the owner's current laptop.
New sessions load the configuration; the active chat is already authorized by
its explicit owner response.

[OpenAI's configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
documents project configuration and `auto_review.extra_policy`; managed
`guardian_extra_policy` takes precedence. This records the authorization clearly
and reduces repeated ambiguity; it cannot guarantee that a managed reviewer
will accept every future action. A network allowlist grants technical reachability
and does not establish payload authorization. If automatic review rejects an
otherwise matching scan, surface its stated reason and stop that upload rather
than changing modes or bypassing it.

## Latest authoritative baseline

Merged source `bfb66f309cfb9e7bc4b872c7c7b68acbc7866342` was scanned on
8 October 2026 at 02:29 UTC. The processed dashboard shows 81.3% new-code coverage
(required 80%), 81.4% overall coverage, zero new security/reliability issues and
six new maintainability issues in verification/parser tests. The quality gate
fails only on the six new issues. Existing contextual security flags remain open.
This follow-up addresses the six findings without lowering the gate or changing
profiles/exclusions. Authoritative proof requires another owner-requested scan
of merged main after this follow-up is reviewed and merged.
