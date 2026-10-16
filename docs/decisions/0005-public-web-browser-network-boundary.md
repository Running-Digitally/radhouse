# ADR-0005: Public-web-only browser networking

Date: 2026-10-15. Status: accepted policy; enforcement qualification and rollout
remain open. Owner: repository maintainer.

## Context

The owner selected public-web-only access for the agent-controlled browser,
with future private-network access requiring explicit grants. The browser visits
untrusted content; a private application deployment does not itself contain that
content's outbound requests. Renderer sandbox proof, URL classifiers and an
informational network descriptor do not establish browser egress enforcement.

The separate review browser has a qualified public-only proxy and route boundary.
Its proof does not automatically apply to the integrated agent-owned browser.
S5 must use evidence from the active implementation and deployment.

## Decision

The integrated browser must reach public web destinations only through a vetted
public HTTP/CONNECT proxy, with an independent routing boundary preventing
direct egress. Deny private, loopback, link-local, metadata, reserved and multicast
destinations, unsafe ports, mixed DNS answers and resolution changes that could
retarget an approved connection. TLS stays end to end; do not bypass certificate
checks. Redirects and new connections must undergo the same checks. Proxy failure
must not enable a direct connection.

Keep model-provider, document-callback and other authorized backend network
access outside this browser boundary. Do not block the entire runtime's private
network to imitate browser isolation, or grant the browser the runtime's backend
exceptions. No upstream engine or viewer fork is required by this policy.

A future LAN grant must name the destination, purpose, owner, expiry and enforcing
mechanism, and pass equivalent negative tests. A model instruction or reachable
URL cannot create a grant. There is no blanket LAN exception in the default mode.

The network summary remains descriptive. Mark it verified only after exact
installed artifacts, effective routing/proxy controls and actual-browser negative
probes agree. Neither a configuration label nor a passing public navigation is
acceptance evidence by itself.

## Implementation and consequences

Use an owned Linux worker with a separate temporary OS identity and network
namespace containing only loopback. A second temporary identity runs the existing
public-only proxy on the host network. Group-restricted Unix sockets carry a
narrow start/status/stop protocol and fixed CDP transport. The worker checks the
caller’s kernel UID and exact service cgroup; the client checks root-created
socket ownership and kernel peer identity. Only the generated X11 cookie crosses
the control boundary, never the backend environment or owner profile.

The native adapter reserves ownership before a launch request. A missing launch
or stop acknowledgement retains that reservation and blocks replacement. Only
a positive retirement acknowledgement after child reaping and relay cleanup
releases it. Worker restart without retained state requires an operator-managed
paired restart; it cannot infer that an unknown generation is safely retired.
All three services share an aggregate memory/CPU/task budget, with narrower
worker and proxy ceilings. The root-managed deployment binds the exact adapter,
units, browser, policy and runtime receipt before selection. Preserve browser generation,
privacy, native acknowledgement, interruption and retirement contracts. Fail
closed on unavailable or incompatible isolation rather than silently launching
an unrestricted browser.

S5 remains open until this boundary is implemented, qualified and selected, or
the unsafe capability is explicitly contained/disabled and its follow-up owned.
The existing owner-only pilot is not evidence of public-only containment or
production readiness. Raw deployment/network findings remain private.

Validation must cover real browser HTTP/HTTPS, redirects, DNS changes/mixed
answers, private and IPv6 destinations, bypass routes, proxy loss, native endpoint
authorization, actual input/video/privacy/handback and complete generation cleanup.
Record actual coverage and untested conditions separately.

Alternatives rejected: setting the descriptor to verified; relying only on proxy
flags, classifiers, renderer namespaces or LAN-only ingress; giving the browser
backend LAN exceptions; or rewriting upstream engines to hide an owned boundary.

Review before broader users/ingress, any LAN grant, engine/provider change or
network-policy change, and no later than 2026-11-14. See the
[stabilization plan](../plans/2026-10-15-boundary-stabilization.md) and
[ADR-0004](0004-replaceable-runtime-adapters.md).
