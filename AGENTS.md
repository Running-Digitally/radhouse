# Radhouse agent capabilities

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
