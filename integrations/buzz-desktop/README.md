# Maintained Buzz desktop Researcher integration

The owner approved this minimal desktop patch on 2026-09-13. It targets Buzz
0.5.23, upstream `092c6a7277698bd373ccbc1d008fc1507094ae74`. It adds a
**Review work** button to the member's channel header. The approved redirect
connects an actual Researcher identity in Buzz's agent directory and private DMs.
The contextual review component bundles the same operator components as Radhouse
and uses the existing native signing key;
it does not load executable code from the controller.

`manifest.json` pins the upstream, patch digest and canonical shared-source
digests. Buzz retains its upstream license/notices; the copied Radhouse files
include their Apache-2.0 license. No relay or mobile source is patched.

## Apply and build

Use a clean checkout of the exact upstream commit. Read Buzz's `AGENTS.md`,
`CONTRIBUTING.md` and `TESTING.md`; activate its Hermit environment before build
or Git hooks. From Radhouse:

```sh
python3 integrations/buzz-desktop/apply.py /path/to/buzz
python3 integrations/buzz-desktop/apply.py /path/to/buzz --apply
```

Before compiling, set three public, deployment-specific build values:

```sh
export BUZZ_RADHOUSE_ORIGIN=https://controller.example.test:8443
export BUZZ_RADHOUSE_RELAY_ORIGIN=https://buzz.example.test
export BUZZ_RADHOUSE_RELAY_PUBKEY=REPLACE_WITH_VERIFIED_64_CHARACTER_RELAY_HEX_KEY
```

Both origins must be exact HTTPS origins with no trailing slash. The relay key
must be verified from the admitted private relay and match the controller's
configuration. Missing configuration safely hides the panel. The native TLS
stack must trust the controller certificate; never disable verification.

Run the pinned desktop's documented dependency setup, `just ci`, and desktop
packaging command (`pnpm --dir desktop tauri:build`) with those values set.
For a local macOS qualification bundle without an Apple signing identity, use
`pnpm --dir desktop tauri:build --config '{"bundle":{"macOS":{"signingIdentity":"-"}}}'`
and verify it with `codesign --verify --deep --strict /path/to/Buzz.app`.
This produces a local ad-hoc signature, not Apple notarization. The default
unsigned packaging output is not sufficient evidence of a valid app signature.
Retain the original desktop bundle and qualify the patched bundle before
replacing the everyday installation. A Rust check without these values proves
compilation, not a configured installation.

## Controller and key registration

Apply the schema-3 upgrade described in `docs/storage.md` before starting the
new controller. The optional private overlay adds:

```yaml
buzz:
  relay_origin: https://buzz.example.test
  relay_pubkey: REPLACE_WITH_VERIFIED_64_CHARACTER_RELAY_HEX_KEY
  conversations:
    - channel_id: exact-existing-channel-id
      conversation_id: exact-approved-radhouse-conversation-id
```

The existing local-auth configuration must use HTTPS, secure cookies and the
default `radhouse_session` cookie name. Allow the controller one exact HTTPS
connection to the relay's fixed `/query` and `/events` routes and its authenticated
content-addressed `/media/` reads. Existing network controls still apply.

Bind the human's public key to an existing Radhouse principal and project using
the operator CLI. This command checks existing project access; it cannot create
roles, project membership or bot grants. A later key rotation revokes earlier
keys for that principal/conversation atomically.

```sh
radhouse buzz-bind --config /etc/radhouse/config.yaml \
  --overlay /etc/radhouse/buzz.yaml --principal-id existing-person \
  --project-id existing-project --channel-id exact-existing-channel-id \
  --pubkey VERIFIED_HUMAN_HEX_PUBLIC_KEY --apply
```

Configure a Researcher candidate under `buzz.agents` with `link_id`,
`conversation_id`, `principal_id`, `owner_pubkey`, `bot_id`, `project_id`,
`binding_revision`, `agent_pubkey` and a protected `signing_key: {path: ...}` file.
The controller verifies the public key matches this file; a client cannot choose
another identity. Leave `channel_id` and
`activated_at` absent for initial enrollment. See the configuration types and
`docs/operator-buzz-completion.md` for the exact enrollment contract.

In the admitted owner's native client, sign in to **Review work** and select
**Connect Researcher**. The native signer creates an owner attestation and
directory record, opens the owner/agent DM, then asks the controller to finish
the retained enrollment. After that, use Buzz's ordinary agent directory, DM,
composer and reply action. Radhouse provides the same conversation in its web
home. The native button handles protected decisions and result publication.
The attestation delegates relay membership through the owner; the controller
independently restricts work to the configured owner, bot, project and exact DM.
Enrollment therefore requires the explicit private identity/access decision.

## Qualification and rollback

Local tests exercise both surface directions through one task/publication
authority, real Schnorr signatures, current membership and key revocation,
replay denial, MFA/Origin/CSRF, changed content, lost replies and schema upgrade.
The shared component also completes a browser walkthrough against real local
PostgreSQL. The installed Tauri panel and live relay remain a required acceptance
exercise: start in web/review in desktop; start in desktop/review in web; close
and reopen the panel; switch identity/community; interrupt connectivity; confirm
no duplicate dispatch/publication and no private display after revoked access.

For a source rollback, run `git apply --reverse --check` with this patch, then
`git apply --reverse` only in the owned checkout. Retain unrelated changes.
For an installed client rollback, restore the retained upstream bundle and
disable the optional controller Buzz overlay. Preserve the schema-3 database;
an older controller binary cannot consume it safely. After new work is admitted,
restore of an older database requires an explicit data-loss decision.

For each upstream update, refresh the vendored operator files from their
canonical Radhouse sources, regenerate this patch/manifest, run both product and
Buzz checks, and repeat the native acceptance exercise. This maintenance is part
of the approved desktop-patch choice. Official mobile push and mobile protected
reviews are separate outstanding requirements.
