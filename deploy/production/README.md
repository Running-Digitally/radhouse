# Supplied Linux VM deployment

This is the first production-shaped deployment path for one Radhouse control VM
and one separately isolated Hermes bot VM. The operator supplies private values;
the public files contain no hostnames, addresses, credentials, or user data.

The controller runs as an unprivileged host service. PostgreSQL publishes only
to host loopback and uses the fixed `172.30.220.0/28` container subnet. The host
firewall must deny new outbound connections from that subnet while preserving
established replies to the loopback-published database port. A separate unprivileged
SSH identity forwards only the Hermes gateway and the deployment's bounded model
catalog endpoint to loopback. Radhouse terminates HTTPS itself for this early
pilot; expose the selected HTTPS port only to explicitly admitted operator
sources.

## Prepare

1. Build `web/` with `npm ci && npm run build` and stage the reviewed source at
   `/opt/radhouse/app`.
2. Install the lock-pinned Python environment with Python 3.14:
   `uv sync --frozen --no-dev --python 3.14.4`.
3. Create the non-login `radhouse` and `radhouse-tunnel` users. Only
   `radhouse-tunnel` may read the dedicated SSH private key.
4. Copy `config.example.yaml` to `/etc/radhouse/config.yaml`, replace every
   example value in a private overlay, and store one-line secrets below
   `/etc/radhouse/secrets` as root with group-read only where required.
5. Create a private TLS key and certificate whose SAN exactly matches the
   configured origin. Keep the CA outside the VM and explicitly trust it on
   admitted clients.
6. On the bot VM, install `model_catalog_proxy.py` and enable the templated
   systemd unit with the exact model-server IP as its instance, for example
   `radhouse-model-catalog@192.0.2.20.service`. It
   accepts only loopback `GET /v1/models`, performs one bounded upstream GET,
   follows no proxy setting or redirect, and has no generation route.
7. On the bot VM, install the tunnel public key with `restrict,port-forwarding`
   plus exact `permitopen` clauses for the two loopback endpoints. Do not grant a
   shell, agent forwarding, X11 forwarding, a PTY, or any other destination.

## Database and service order

Start PostgreSQL from `compose.postgres.yaml`, create the non-owner runtime role,
then run `radhouse migrate --apply` with the owner DSN file. The runtime service
uses a separate DML-only role. Run `radhouse preflight` before enabling any unit.

Install the three systemd units and the coordinator timer. Verify the tunnel,
`/healthz`, a denied unauthenticated work-home request, one local-account login,
one bounded task, protected review, and restart recovery. A passing offline test
or health endpoint does not authorize a model call, a network grant, or a user.

`radhouse local-user --apply` provisions one explicitly named local person,
project, bot grant, Radhouse conversation binding, Argon2id password, encrypted
TOTP secret, and revokes that person's earlier sessions. Passwords, TOTP secrets,
database credentials, and the local-auth encryption key are accepted only by
protected file reference and are never emitted in the command receipt.
