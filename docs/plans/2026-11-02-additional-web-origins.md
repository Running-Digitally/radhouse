# Additional private web origins

Status: implemented and locally qualified candidate, not deployed. Date: 2026-11-02.

The owner requested an additional HTTPS application hostname usable through an
identity-aware access proxy without a device VPN. Keep the original private URL
usable and retain password/TOTP, session, CSRF and owner/conversation checks.
Installation-specific hostnames, certificates, route changes and authority remain
in the private operational record.

## Bounded design

Add optional `additional_origins` to standalone chat configuration and
`additional_origins` to `LocalAuthService`. The existing required `origin` remains
the primary origin. Resolve a fixed set at startup; login and every unsafe
session request use the same exact membership check. Do not derive trust from
Host, forwarded headers or a suffix match. Do not add CORS, cookie sharing,
Cloudflare identity mapping or a new session type.

Additional entries must be an explicit list/tuple of valid HTTPS origins, with
no credentials, wildcard, path, query, fragment, whitespace or malformed port.
Retain the existing primary-origin compatibility behavior. Existing deployments
that omit the setting keep their current policy.

Files: `src/radhouse/auth/local.py`, `src/radhouse/chat/main.py`,
`src/radhouse/chat/browser_transport.py`, focused synthetic
tests and configuration documentation. Call path: config -> factory -> auth
constructor -> login `verify_origin` / unsafe session check -> existing CSRF and
database ownership controls. Test old/new origin acceptance, missing/foreign
origin rejection, malformed configuration and CSRF rejection at both origins.
The browser-stream WebSocket handshake also invokes the configured auth origin
check; synthetic adapters retain their existing URL-based same-origin check.
The primary-origin field remains compatible with existing local browser fixtures.

Public edge admission must cover every path and validate the intended Access
audience before forwarding. The origin TLS certificate must be checked using its
existing CA. Publish DNS only after application and proxy checks pass. Rollback
removes the new public selection and restores the prior source/config without
restoring or overwriting chats or databases.

Mobile design lives in the separate
[mobile repository](https://github.com/Running-Digitally/radhouse-mobile).
This source change only enables an additional browser origin; native single-login
authentication remains a separate design.

## Touched-file SonarQube review

The latest processed main report and live file filter were checked on November 2.
`auth/local.py` has two open S5886 return-type findings:
`37ae676b-b505-4210-8e37-86209bd844bc` (`reauthenticate`) and
`054419c2-af75-4089-8908-7a8fba7d7340` (`refresh`). Both return
`dataclasses.replace()` on a `LocalSession`, which preserves that dataclass type.
They are proposed contextual analyzer limitations, not accepted server
dispositions. Replacing these unrelated session constructions merely to satisfy
inference would add authentication churn to the hostname change. Defer to a
focused type-contract review; no issue status, rule or gate was changed.
`chat/main.py` has no entries in the latest dated file index; verify any new
findings after the next authorized merged-main scan.

The stream file has `39288306-0bf9-47c9-be2c-bde5fbbf492e`, a redundant
`UnicodeError` catch beside its parent `ValueError`; the redundant class is
removed without changing handling. Complexity finding
`0cca92cd-eab0-4044-8e29-9126d17c96f7` covers the whole nested stream installer
(74 against 15). The origin check is extracted, but broader relay/task-lifecycle
refactoring is deferred to a focused transport change with disconnect/revocation
proof. Local changes do not establish server closure of either issue.

## Local qualification

156 focused application, authentication and stream tests passed, including real
loopback WebSocket transport. A separate owned PostgreSQL fixture passed 74
authentication/browser tests, including new-origin login/logout, retained CSRF,
revocation and the real-browser reload/lost-response flow. The two groups overlap;
their counts are not a unique-test total. Fixture cleanup completed. Public-source
privacy and whitespace checks passed. No live deployment, merge or new SonarQube
scan is claimed by these local results.
