# Mail and account security

Status: accepted for version 1.0. Account-security mail remains human-controlled
by default. Tested integrations may complete explicitly approved verification
and sign-in flows for named bot-owned accounts. Password resets and security-setting
changes remain human-controlled. Integration details are not yet qualified.
Updated: 2026-09-10. Nothing is deployed.

## Separate ordinary mail from account authority

The optional bot mail service receives work material for
[proactive assistance](proactive-assistance.md). Reading a message does not grant
permission to verify an account, sign in, reset credentials, accept new access,
or send email. Personal-inbox integration and outbound bot email remain outside
the accepted V1 scope. External account creation remains a human responsibility.

Register account-security correspondence to a protected human-controlled inbox
where the service supports it. Bots receive scoped status and requests for human
help without the codes or links. When a service mixes security and ordinary mail
at one address, require a qualified mediated view or keep that inbox protected;
do not grant unrestricted inbox access and rely on a model to ignore secrets.

Enforce separation in account/address configuration, mailbox permissions, and
the integration. Message labels, sender display names, or LLM classification
alone cannot establish a credential boundary. Forwarding, aliases, exports,
search, summaries, notifications, logs, and backups must preserve that custody.

## A narrow automation option

An administrator may approve a tested integration for a named bot-owned account
and specific verification/sign-in operations. A standing grant may cover repeated
matching flows; this is not a requirement for a human click on each normal login.
The bot can request an admitted operation, but the trusted integration enforces
the grant and handles security material outside ordinary bot-readable content.

The integration must bind each execution to:

- The exact account, service, requesting bot, and current authorization.
- An expected pending transaction and its permitted verification/sign-in purpose.
- The expected service origins and callback/redirect behavior; arbitrary URLs
  from email are not executable instructions.
- Current expiry/revocation, token-use state, and a bounded execution budget.
- The resulting session's permitted account, resource, and operation scope.

Use the provider's qualified protocol and libraries. Do not build a generic
"click any verification link" capability or let the model reclassify a password
reset as a sign-in flow. If purpose, identity, or resulting access cannot be
established, hand the operation to an authorized human without guessing.

Return a bounded status or pass the resulting credential/session through its
approved service-access path. Do not expose raw email secrets to the worker.
Login must not give a bot a broader session than its admitted access; if the
upstream service cannot enforce the needed scope, require an adequate mediated
path or mark that automated combination unsupported. Existing mediated/direct
GitHub credential modes keep their separate grants and security guarantees.

Password reset, recovery-email changes, MFA/security-setting changes, consent
to broader scopes, new accounts, and privilege elevation require human action
through their own authority. Provider-generated mail during an approved sign-in
flow does not authorize the bot to compose or send arbitrary email.

## Recovery, visibility, and qualification

Keep transaction and result receipts outside worker-editable state, without
tokens, codes, full credential-bearing URLs, or cookies. Show waiting for a
human, unsupported, failed, expired, completed, and unknown distinctly. A browser
page claiming success is not proof of the correct account or effective scope.

Recheck grants before completing a flow or releasing a session. Reconcile
ambiguous results after retries/restarts instead of blindly reusing tokens or
creating duplicate sessions. Revocation must address any issued session at its
enforcing service; deleting a local record alone is insufficient evidence.

Qualify each supported provider/flow against forged mail, wrong-account tokens,
unexpected redirects, replay/expiry, mixed-use security messages, changed grants,
session overreach, account reassignment, and interrupted execution. Prove that
ordinary triage, notification, and artifact paths do not expose security material,
and that password-reset/security-change paths are inaccessible to automation.
This contract does not assert that any provider integration already passes.

OWASP describes emailed tokens as a means of proving identity during password
reset and requires secure handling. That supports treating these messages as
account authority. The default custody and automation boundaries above are
Radhouse design decisions.
[OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).
