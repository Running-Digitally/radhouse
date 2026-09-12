# Authentik identity profile

Radhouse supports local accounts and optional SSO. Authentik is the first bundled
SSO candidate. It proves how a person authenticated; Radhouse remains the owner
of installation membership, the administrator/operator/viewer role, bot and
project grants, content audience, and protected decisions.

**Qualification candidate:** Authentik `2026.8.2`, with a separately pinned
PostgreSQL 16 service. The reference composition uses Authentik server, worker,
and PostgreSQL. It does not add Redis or an outpost until a demonstrated feature
requires one.

## Admission and session contract

- Disable self-registration. An administrator explicitly invites a person and
  assigns their Radhouse role and eligible resources.
- Bind a Radhouse person to the validated `(issuer, subject)` pair. Email,
  display name, or identity-provider groups cannot silently link or promote an
  account.
- Use authorization code flow with PKCE S256, strict redirect allowlists,
  `state`, and `nonce`.
- Validate issuer, signature and algorithm, current JWKS, audience/authorized
  party, expiry and issued-at time on every exchange.
- Require MFA for every administrator and every remote user. Unknown ingress is
  treated as remote. Local non-administrator accounts may opt in.
- Recheck current Radhouse membership and grants on protected operations. A
  valid SSO session alone does not preserve a withdrawn permission.

Exact token, idle-session, absolute-session, reauthentication, and revocation
intervals remain qualification inputs. They should be short enough to bound a
withdrawn grant without making normal local use impractical.

## Recovery and outage behavior

Retain a designated local administrator sign-in with MFA whose factors and route
do not depend on Authentik. It carries only that person's current Radhouse
authority; it cannot revive a disabled account or provide hypervisor access.
SSO-only users wait for provider recovery. Local sessions end locally even when
provider logout is unavailable.

Protect the database, `/data`, configuration, signing and TLS material, and key
references as one recovery set. Store encrypted recovery material outside the
installation and prove an isolated restore. Restoring an older identity backup
must not silently revive known account, grant, session, or key revocations.

## Buzz key binding and protected decisions

Buzz uses signed keys, while Radhouse uses human identities and roles. Bind a
verified Buzz public key to an already authenticated Radhouse person through a
fresh, signed, one-time challenge. Do not link by email, display name, room
message, or administrator guess. A bot or service key cannot approve as a human.

A protected Buzz decision binds the action, task and revision, artifact digest,
audience, conversation, key-binding revision, human session, decision revision,
and expiry. Recheck identity, key binding, role, grants, audience, and freshness
when the decision commits. See the [Buzz profile](buzz.md).

Qualify wrong issuer/audience, key rotation, replay, disabled users, grant
withdrawal, MFA loss, stale sessions, provider outage, local-admin recovery,
backup/restore, and Buzz key rebinding before enabling SSO for retained work.
