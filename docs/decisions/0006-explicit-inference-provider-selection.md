# ADR-0006: Select enrolled inference providers explicitly

Status: accepted owner direction; implementation and operational qualification in progress.

Date: 2026-10-16

## Context

The local pilot's default inference endpoint can be unavailable during independent model work. Another owner-operated endpoint is useful both for product use and for real tool/boundary testing. Repeated temporary default-provider rewrites would hide configuration changes and make retries harder to attribute. The existing model control discovers only the configured default engine.

## Decision

Support a bounded operator-enrolled set of native provider/model pairs in the existing model control. Reuse Hermes provider registration, resolution and execution. Keep endpoints, headers and credentials native. Show per-provider availability; do not hide a healthy alternate when the default is offline. Require an explicit user choice for an alternate, and preserve that choice through queueing, retries and native admission. Reject stale, removed or redirected selections without fallback.

Keep the browser's public-web-only network boundary independent. Backend admission to an inference endpoint does not grant web content LAN access. Store operational addresses, firewall evidence and credentials privately; publish only synthetic contracts and sanitized qualification.

## Consequences and alternatives

The default remains an operator setting; adding a second provider does not migrate it. Model IDs are scoped to provider IDs, and reasoning controls require metadata supported by the actual serializer. Discovery is bounded and independent. The model/quant/context/performance of each endpoint remains visible operational evidence, not an interchangeable capability guarantee.

A new routing gateway or generic browser-configurable endpoint is unnecessary. Silent fallback obscures which model received a request and can change behavior or privacy unexpectedly. A temporary profile swap remains an operator recovery mechanism rather than the normal product flow.

See the [design and acceptance contract](../design/inference-providers.md), [replaceable adapters](0004-replaceable-runtime-adapters.md) and [public-web browser boundary](0005-public-web-browser-network-boundary.md). Revisit on provider replacement, additional users, public ingress, new credentials/authority or a different native transport.
