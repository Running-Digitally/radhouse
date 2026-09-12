# OpenAI-compatible local inference

Radhouse treats a provider binding as a stable deployment-owned name. Hermes
requests that name for every main, helper, and auxiliary model call. The
controller checks only the provider catalog before task admission; it never
changes the served model and never selects a fallback provider.

The implemented probe issues one bounded `GET /models` request with proxy
inheritance and redirects disabled. It requires exactly one entry matching the
configured alias. Connection failures, non-200 responses, oversized or malformed
JSON, a missing alias, and duplicate aliases all project to a visible unavailable
provider. They do not trigger a generation request or expose a vendor response.

Configuration records both the capabilities required by the bot profile and an
operator-qualified capability ceiling for that binding. A standard catalog can
also publish `max_model_len`. If a deployment-owned compatibility adapter adds a
`capabilities` list or boolean mapping, Radhouse intersects it with the qualified
ceiling; server metadata cannot expand an administrator grant. Missing required
context or capability evidence makes the binding incompatible.

Ordinary OpenAI-compatible catalogs often expose only the stable alias. In that
case Radhouse records the alias as the observed model. A deployment-owned adapter
may add a bounded `radhouse_model_id` field to the matching catalog entry so
Radhouse can record a physical backing revision without changing the model sent
by Hermes. This extension is observation only. The operator's model selector
remains the sole switch authority.

Some self-hosted servers publish exactly two catalog entries: the configured
alias and its current physical model. A deployment can explicitly select
`model_identity: catalog_sibling` for that contract. Radhouse records the sole
other valid model ID and uses its context/capability metadata when present. Zero
or multiple sibling entries fail closed as incompatible because the physical
identity is ambiguous. The secure default remains `alias`; the alternative
`radhouse_extension` mode requires the explicit field described above.

Plain HTTP defaults to literal loopback. An administrator can explicitly admit
a literal RFC1918 endpoint for a deployment whose network policy provides the
trust boundary. The public default and remote-provider path use HTTPS. Provider
tokens, when needed, are read from protected single-line files and never appear
in YAML.

The current adapter and composition tests use an in-process mock transport. They
prove request shape, stable-alias continuity, model-attribution changes,
capability/context refusal, redirect denial, bounded response handling, exact
routing, and cleanup. They make no request to a live inference service.
