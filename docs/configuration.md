# Configuration and private overlays

Radhouse uses one strict YAML schema for both guided Proxmox deployments and
operator-supplied Linux VMs. The public base describes product roles and safe
defaults. An optional private overlay supplies installation-specific endpoints,
secret-file references, and worker settings. Lists replace the public list;
nested mappings merge by key; the resulting document is validated as one unit.

Start from [`examples/config/radhouse.example.yaml`](../examples/config/radhouse.example.yaml).
It contains only synthetic names and reserved example domains. Do not edit the
public example with real inventory. Keep the private overlay outside this
repository or in an explicitly private deployment repository.

Version 1 of the schema covers the currently implemented controller pieces:

- an expected database name and deployment identity, with the DSN supplied
  through an absolute secret-file path;
- one bounded coordinator identity, interval, and per-cycle task limit;
- an explicit absolute path to the built operator assets; and
- one or more stable OpenAI-compatible provider bindings with an exact model
  alias and an operator-qualified capability ceiling; and
- one distinct Hermes-home endpoint, token-file path, profile, pinned runtime
  revision, and stable provider binding for every configured bot.

Configuration never contains an inline password or token. Plain HTTP runtime
endpoints are accepted only for literal loopback IP addresses, supporting an
operator-managed local tunnel. Remote runtime origins require HTTPS. Userinfo,
query strings, and fragments are rejected so credentials cannot be hidden in a
URL. One endpoint cannot be assigned to two bots because one Hermes gateway owns
one bot home in the first supported profile.

Loading uses PyYAML's safe loader, rejects unknown fields, applies a 1 MiB input
limit, and returns only bounded error codes. Parsing a file does not prove that a
secret exists, a TLS origin is trusted, a database is ready, or a runtime is
reachable. Those checks belong to deterministic deployment preflight and must
run before starting a listener or coordinator.

The composition root reads the referenced database and Hermes token files,
builds the durable bot-ID routes, and owns client shutdown. Construction does
not connect to PostgreSQL, contact Hermes, inspect a provider, or start a
listener. A deployment supplies the separately qualified provider and
authentication adapters before it can serve operator traffic.

Provider probes use only `GET /models`; they never submit generation requests.
HTTPS or a literal loopback address is the default. A private overlay may admit
plain HTTP to a literal RFC1918 address when the deployment supplies the network
boundary, as in a source-fenced homelab inference VLAN. Hostnames and public
addresses cannot use that exception. Each bot must name one configured binding,
and an operator task request cannot override that durable assignment.

Identity configuration is intentionally absent until the local-account and OIDC
adapters have concrete, tested session and assurance contracts. A deployment
cannot infer or enable synthetic authentication from this file.

Validate a base and optional private overlay without reading any referenced
secret or contacting any endpoint:

```sh
radhouse config-check --config /etc/radhouse/base.yaml \
  --overlay /etc/radhouse/private.yaml
```

After installing protected secret files, validate their ownership, permissions,
DSN boundary, and complete provider/bot composition without opening a database
connection or contacting a provider or Hermes endpoint:

```sh
radhouse preflight --config /etc/radhouse/base.yaml \
  --overlay /etc/radhouse/private.yaml
```

A successful result is `offline_ready`. It is a prerequisite for online health,
identity, database, and runtime checks; it does not claim that any service is
reachable or start the controller.
