# Supplied Linux VM deployment

This path installs the Radhouse controller on one operator-supplied, systemd-based
Linux VM. Hermes remains on a separately isolated bot VM. The repository contains
no deployment hostnames, addresses, credentials, or user data.

`radhouse_vm.py` owns a small controller release lifecycle: verify one exact clean
Git revision, build it into a root-owned versioned directory, select it through
`/opt/radhouse/current`, report service state, upgrade behind a verified backup,
and roll back when the storage schema remains compatible. It does not change the
firewall, issue certificates, create database credentials, configure Hermes or
Buzz, or start a new installation before those private values are ready.

The controller runs as an unprivileged host service. PostgreSQL publishes only
to host loopback and uses the fixed `172.30.220.0/28` container subnet. The host
firewall must deny new outbound connections from that subnet while preserving
established replies to the loopback-published database port. A separate unprivileged
SSH identity forwards only the Hermes gateway and the deployment's bounded model
catalog endpoint to loopback. Radhouse terminates HTTPS itself for this early
pilot; expose the selected HTTPS port only to explicitly admitted operator
sources.

## Install the controller

The VM needs Git, Node.js 20.19.0 or newer with npm, uv, a C compiler,
`pkg-config`, systemd, `useradd`, Docker Engine with Compose, and CPython 3.14.4
available as `python3.14`. The compiler and `pkg-config` are required because the
frozen Python dependency set contains a source-built native extension. Start
from an exact reviewed commit in a clean checkout:

```sh
release_id="$(git rev-parse HEAD)"
python3 deploy/production/radhouse_vm.py preflight \
  --source . --release-id "$release_id"
sudo python3 deploy/production/radhouse_vm.py install \
  --source . --release-id "$release_id"
```

Installation builds the lock-pinned Python and browser dependencies, installs
the controller units, and leaves them stopped. It creates
`/etc/radhouse/config.yaml.example`; copy that to `config.yaml` and provide the
private configuration, secrets, TLS material and tunnel key before continuing.
Application code is immutable to the service identity; configuration and
PostgreSQL state live outside it.

Complete these bounded setup steps:

1. Copy `config.yaml.example` to `/etc/radhouse/config.yaml`, replace every
   example value in a private overlay, and store one-line secrets below
   `/etc/radhouse/secrets` as root with group-read only where required.
2. Create a private TLS key and certificate whose SAN exactly matches the
   configured origin. The CA certificate must carry critical `CA:TRUE` basic
   constraints, certificate-signing key usage, a Subject Key Identifier and an
   Authority Key Identifier. The server certificate must carry critical
   `CA:FALSE` constraints, server-auth extended usage, its IP/DNS SAN, a Subject
   Key Identifier and an Authority Key Identifier linked to the CA. Validate the
   chain with the pinned Python 3.14 runtime as well as `openssl verify`; current
   Python rejects a CA that omits the authority identifier even when OpenSSL's
   basic command accepts the chain. Keep the CA private key off the runtime data
   path and explicitly trust only the public CA certificate on admitted clients.
3. On the bot VM, install `model_catalog_proxy.py`. Keep the templated unit's
   fail-closed `IPAddressDeny=any` and loopback allowance, then add a private
   instance drop-in containing the exact model-server `IPAddressAllow`. It
   accepts only loopback `GET /v1/models`, performs one bounded upstream GET,
   follows no proxy setting or redirect, and has no generation route.
4. On the bot VM, install the tunnel public key with `restrict,port-forwarding`
   plus exact `permitopen` clauses for the two loopback endpoints. Add the
   dedicated account to `AllowUsers` when that directive is present. A freshly
   created system account is commonly shadow-locked and OpenSSH rejects it
   before public-key evaluation; use an invalid, non-lock password marker while
   retaining `PasswordAuthentication no`, `KbdInteractiveAuthentication no`,
   `AuthenticationMethods publickey`, an exact source restriction and a
   `nologin` shell. Verify the effective Match configuration and one key login.
   Do not grant a shell, agent forwarding, X11 forwarding, a PTY, or any other
   destination.

## Database and service order

Start PostgreSQL from the selected release's `compose.postgres.yaml`, create the
non-owner runtime role, then run the selected release's `radhouse migrate
--apply` with the owner DSN file. The runtime service uses a separate DML-only
role. Run `radhouse preflight` as the `radhouse` service identity before enabling
any unit. The exact commands depend on the private database and overlay paths;
the public shape is:

```sh
sudo docker compose \
  -f /opt/radhouse/current/deploy/production/compose.postgres.yaml up -d
sudo /opt/radhouse/current/.venv/bin/radhouse migrate \
  --config /etc/radhouse/config.yaml \
  --owner-dsn-file /etc/radhouse/secrets/database-owner-dsn \
  --runtime-role radhouse_runtime --apply
sudo -u radhouse /opt/radhouse/current/.venv/bin/radhouse preflight \
  --config /etc/radhouse/config.yaml
sudo systemctl enable --now radhouse-hermes-tunnel.service \
  radhouse-api.service radhouse-coordinator.timer
```

Verify the tunnel,
`/healthz`, a denied unauthenticated work-home request, one local-account login,
one bounded task, protected review, and restart recovery. A passing offline test
or health endpoint does not authorize a model call, a network grant, or a user.

`radhouse local-user --apply` provisions one explicitly named local person,
project, bot grant, Radhouse conversation binding, Argon2id password, encrypted
TOTP secret, and revokes that person's earlier sessions. Passwords, TOTP secrets,
database credentials, and the local-auth encryption key are accepted only by
protected file reference and are never emitted in the command receipt.

For an additional configured bot, use `radhouse bot-grant --apply`. It adds the
bot profile and grant to an existing active person's existing project without
reading or rotating password, TOTP, binding, or session state. A mismatched
existing bot profile is a refusal.

The installed `radhouse-hermes-tunnel@.service` supports one restricted SSH
transport per additional bot. Add a matching `Host radhouse-hermes-NAME` block
to the protected SSH configuration, then enable the `NAME` instance. Each bot
retains a distinct key, loopback port and remote Hermes home.

## Upgrade and rollback

Before an upgrade, create a consistent database backup with the installation's
qualified backup tool and verify that it can be read. The deployment manager
requires its exact SHA-256 digest before it stops a writer:

```sh
release_id="$(git rev-parse HEAD)"
backup=/path/to/verified-radhouse.dump
backup_sha256="$(sha256sum "$backup" | cut -d' ' -f1)"
sudo python3 deploy/production/radhouse_vm.py upgrade \
  --source . --release-id "$release_id" \
  --backup-file "$backup" --backup-sha256 "$backup_sha256" \
  --owner-dsn-file /etc/radhouse/secrets/database-owner-dsn
```

The manager builds and preflights the release before stopping the API and
coordinator. It then migrates, atomically selects the new release, restarts the
writers and checks their systemd state. A pre-migration failure restarts the old
release. A post-migration startup failure rolls back automatically only when the
old and new releases use the same storage schema. A schema-changing failure keeps
the new release selected for diagnosis and a forward fix; database restore remains
an explicit operator decision.

Inspect the exact selected release and unit states with:

```sh
sudo python3 /opt/radhouse/current/deploy/production/radhouse_vm.py status
```

To select an already installed, schema-compatible release:

```sh
sudo python3 /opt/radhouse/current/deploy/production/radhouse_vm.py rollback \
  --release-id REPLACE_WITH_FULL_40_CHARACTER_COMMIT
```

The current application storage schema is 6. The official Buzz integration is
server-side and works with unmodified clients. The retained custom desktop branch
is superseded and is not part of this deployment path. Configure per-bot
`approval_commands` only for commands already granted to that bot; the empty
default grants no runtime execution authority.
