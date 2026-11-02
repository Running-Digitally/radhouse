# Session-bound mobile reply notifications

Status: implemented and locally tested candidate, not deployed. Date: 2026-11-02.

Radhouse Mobile needs reply-ready notifications while the handset is inactive.
The backend now has optional authenticated device registration, a durable outbox
and an FCM v1 sender. The mobile repository owns permission prompts, secure local
preferences and authenticated notification navigation. Provider credentials and
deployment details stay in private operations records.

## Authority and storage

When configured, GET `/chat/push/status` reports availability. PUT and DELETE
`/chat/push/devices/{installation_id}` require the existing owner session, origin
and CSRF checks. The caller supplies only platform and token; the server derives
owner, conversation, revision, hashed session identity and expiry. An old
session's delayed DELETE cannot remove a newer session's registration.

A separate private SQLite file stores encrypted registration tokens and delivery
metadata. It stores neither raw session credentials nor conversation content.
Limit active devices to 16 per owner. Rotation increments a generation and
retargets pending work; a new session starts a fresh consent boundary. Reconcile
durable completed turns independently of mobile polling, including out-of-order
completion, using deterministic event IDs and unique per-device delivery rows.
Only requests submitted after opt-in and within the latest day are eligible.

Before each send, read current actor activity, session expiry/revocation and
conversation binding from the existing authentication database without extending
session lifetime. Serialize provider dispatch and registration mutation using
the separate outbox write lock. A provider-accepted notification cannot be
recalled by a later logout. Notification content is generic and the four data
fields are version, kind, event ID and request ID. The handset must recheck
ownership before opening a request.

Retry transient failures at most five times with bounded backoff and expiry.
Explicit invalid-token responses deactivate registrations; provider configuration
failures do not delete otherwise valid tokens. Retain delivery metadata for at
most 30 days. Network ambiguity can cause duplicate presentation; no exactly-once
claim is made. Push registration expires no later than its captured session
expiry, even if later app activity extends that session.

## Configuration and rollout

The optional `push` object requires exactly `project_id`, `credentials_path`,
`database_path` and `encryption_key`. Use a separate Fernet key and a private
service-owned database. The service-account file must be private, service-owned,
regular, and match the configured Firebase project and fixed Google OAuth token
endpoint. Use least-privilege FCM send authorization. Credential values never
belong in source, mobile bundles, logs or test fixtures.

Absent configuration preserves current behavior and exposes no push routes.
Native client configuration alone does not enable server delivery. Before rollout,
qualify Radhouse's separate APNs registration, signing profile, provider identity
and egress. Freeze the reviewed source and prepare a separate operational change
with health checks and recovery. Rollback removes the optional configuration and
restores the prior release without restoring or overwriting chat/auth databases.
Preserve the separate outbox for diagnosis; revoke provider access independently
if required. This proposal does not authorize deployment or credential creation.

Acceptance requires a real signed iPhone and a Google Play services Android
device, foreground/background/cold-start receipt, denied permission, token
rotation, offline logout, expiry, duplicate taps and ownership checks. Provider
acceptance and device receipt are separate evidence. See the
[mobile contract](https://github.com/Running-Digitally/radhouse-mobile/blob/main/docs/push-delivery.md).
The sender follows the official [FCM v1 authorization](https://firebase.google.com/docs/cloud-messaging/send/v1-api)
and [error handling](https://firebase.google.com/docs/cloud-messaging/error-codes)
contracts using Google's maintained authentication library.

## Validation and SonarQube

75 focused outbox, transport, route, credential, factory and chat tests pass.
Ten owned-fixture PostgreSQL tests cover current session authority, revocation,
expiry, actor inactivity and binding changes without extending session lifetime;
the disposable fixture was cleaned up. No live database was used for these tests.
Provider/device delivery has not been demonstrated.

The latest dated main index has no findings for `chat/main.py`. For the touched
`auth/local.py`, S5886 findings `37ae676b-b505-4210-8e37-86209bd844bc`
and `054419c2-af75-4089-8908-7a8fba7d7340` remain deferred to the focused
type-contract review described in the additional-origins plan. Both concern
existing `dataclasses.replace(LocalSession)` return inference, outside the new
read-only authorization method. A fresh server issue read returned HTTP 403, so
this candidate does not assert their current server disposition. No suppression,
gate change, accepted finding or scan closure is claimed. New files need the
normal authorized merged-main scan and findings follow-up.
