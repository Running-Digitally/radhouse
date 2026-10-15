# Security and development status

Radhouse is developed in public and currently qualified for a limited private
pilot. The owner reports a single-owner, private-LAN installation with no public
ingress and no customers. That description is not a security assessment of any
other deployment. The project does not currently claim a supported public
service, multi-tenant isolation, independent security audit or response-time SLA.

Source visibility does not grant access to the owner's deployment. Keep actual
credentials, private configuration, conversations, customer data and operational
evidence out of this repository. Use synthetic examples and the repository's
public-source privacy check before publishing changes. That check is useful but
does not prove that the full Git history contains no secrets.

## Reporting a suspected vulnerability

Do not put credentials, private data or exploit details in a public issue or PR.
Use GitHub's private **Report a vulnerability** flow when it is available on
this repository's Security page. At the 2026-10-15 review, private vulnerability
reporting was disabled; enabling and verifying that channel is an immediate
maintainer action. This document does not imply that the channel is enabled.

Until a private reporting channel is verified, use an existing private contact
with the maintainer. If you have none, open a public issue requesting a private
contact without technical vulnerability details. The maintainer must provide a
working private channel before asking for sensitive evidence. No monitored
security email address is currently advertised here.

A useful private report identifies the affected revision/version, required
access, affected capability, expected versus actual behavior and a minimal
synthetic reproduction. Do not test against someone else's deployment.

## Responsibility and response

Radhouse owns its application, adapters, permissions, patch deltas and recovery
behavior. Upstream maintainers own their packages, but Radhouse must assess the
versions it selects and the authority it grants them. A severe reachable issue
requires a qualified update, demonstrable containment, disabling the affected
capability, or a qualified replacement. Private-LAN deployment is context for
that assessment, not a reason to ignore the issue.

The immediate programme prioritizes authentication and admission, browser
ownership, secret handling, terminal boundaries, data preservation and release
recovery. Broader upstream cleanup and speculative architecture rewrites are
outside that programme. No release is automatically safe merely because a
static-analysis gate passes.

Review exposure before new users, internet ingress, additional tools or
unattended effects are introduced. Preserve existing recovery requirements and
obtain the applicable rollout authority before changing a live installation.
Security fixes should include a regression check and a sanitized public account
after coordinated handling where appropriate.

See [ADR-0003](docs/decisions/0003-proportionate-security-and-public-development.md),
[ADR-0004](docs/decisions/0004-replaceable-runtime-adapters.md),
the [ownership map](docs/runtime-ownership.md), and the
[implementation plan](docs/plans/2026-10-15-boundary-stabilization.md).
