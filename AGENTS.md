# Radhouse agent capabilities

## Public engineering and private commercial strategy

Use [ADR-0007](docs/decisions/0007-public-engineering-private-commercial-strategy.md)
when placing research, proposals and roadmap work. This public repository owns
features, user experience, technical research, architecture, security posture,
reliability and sustainable maintenance. A feature's possible future revenue
does not make its technical design private. Keep monetization, pricing,
commercial positioning, business economics and investment hypotheses in the
private venture repository. Maintain one public engineering backlog; private
commercial work may reference it but must not duplicate its delivery status.

Separate mixed documents into self-contained technical and commercial parts.
Do not copy private conversation archives, customer records, credentials,
operational topology or restricted security evidence into public documentation.
Use synthetic examples and independently attributable public sources. When the
boundary is genuinely unclear, give Satish a specific placement recommendation
and check before publishing the ambiguous material. A proposal is not deployment
authorization or evidence that a feature exists.

## Local post-merge SonarQube analysis

When Satish requests a SonarQube scan or rescan for this repository, use the
bounded capability documented in [docs/codex-capabilities.md](docs/codex-capabilities.md).
The established destination is `https://sonarqube.satishsurath.com`, project
`Running-Digitally_radhouse`; the payload is committed merged-main source and
owned synthetic-fixture Python/JavaScript coverage. The owner explicitly
approved that destination and payload in the 7 October 2026 remediation chat
and requested making the capability reusable.

Use the reviewed `scripts/sonarqube.py` launcher and the existing project analysis
token from macOS Keychain or its documented environment variable. A request to
scan invokes this known capability; do not ask for the same destination/payload
approval again unless scope changes or automatic approval review rejects it.
Credentials, live chats, server configuration and unrelated files are excluded.
No issue suppression, rule/profile/gate change, feature-branch analysis, merge
or deployment is included in the scan capability. Server rollout keeps its
separate current-task authority and recovery requirements.

### Community Build sequencing and follow-up work

The installed SonarQube Community Build analyzes this project's single main
branch. It does not provide this repository with branch/PR analysis. The local
launcher deliberately clones committed remote `main`; changing files only in
a feature branch or the invoking checkout does not change the analyzed source.
Never pass a feature commit off as main or bypass the reviewed launcher.

Use the normal review/merge/scan/follow-up cycle when the user authorizes that
cycle. The owner explicitly authorized it on 15 October 2026 for the runtime
scope expansion and bounded stabilization effort. Prepare and validate a small
change, integrate it into main, scan the exact merged SHA, then use a follow-up
branch/PR for relevant findings. Do not try to reopen a merged PR. Confirm each
new branch starts from the appropriate updated main and preserve other sessions'
dirty work. Routine follow-up merges within an explicitly authorized cycle do
not require asking the same sequencing question again.

A scan-only request still does not independently authorize merge or deployment.
The post-merge scan is not a pre-merge required check. A quality-gate failure
does not by itself mean the analysis failed to process; inspect server status,
SHA and measures. Keep all-code findings as well as new-code findings, and
honor the bounded remediation scope instead of initiating a zero-issue sweep.
See the [stabilization plan](docs/plans/2026-10-15-boundary-stabilization.md).
