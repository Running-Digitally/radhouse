# Explicit inference providers

Owner direction, 16 October 2026: support both configured Nemo and Lucy endpoints persistently. D2 bounded change across native catalog, web admission and the existing model control. Operational addresses and credentials remain private.

## Contract and responsibilities

Hermes continues to own provider registration, endpoint resolution, credentials, serializers and execution. Radhouse discovers only the default engine plus explicitly enrolled named engines in native `radhouse_inference.providers`. Each enrollment names an existing native provider, its default model and a display label; it contains no browser-supplied URL. Admit at most four distinct providers. No new gateway, proxy, credential store or database schema.

The existing v1 catalog retains `engine` and `current_model` as the default. Add `engines` with per-provider availability/current model, and add `provider` to each model row. Identity is the pair `(provider, model)`; two providers may offer the same model ID. Discovery runs independently in a bounded pool so an unavailable default does not hide a healthy alternative. Failed refresh removes selectable stale rows from only that provider. No network/error bodies reach the browser.

The existing model menu labels each row with its provider. Its opaque option value encodes the pair; requests carry an optional provider ID alongside model/thinking. Legacy selections retain their default-engine meaning and exact stored request shape. Default continues to use the operator's configured default. Switching providers is explicit; submitted/queued/retried turns retain their frozen provider/model/options.

Web normalization accepts only sanitized provider/model/capability fields. Web resolution checks the selected pair. Native admission independently checks that provider is still enrolled, its endpoint/transport/selected-model capabilities have not changed, and the selected model is currently offered. Credential rotation does not invalidate an otherwise unchanged route. Existing native confirmed-runtime locking prevents session/model-route/fallback overrides. An offline endpoint never silently redirects an explicitly selected turn.

## Native enrollment example (synthetic)

```yaml
radhouse_inference:
  providers:
    - provider: custom:secondary
      model: secondary-chat
      label: Secondary
```

The default engine need not be repeated. Native provider registration remains separate and private. Enrollment is validated before discovery; unknown or malformed registration is unavailable rather than routed by guessed URLs.

## Call path and affected files

`InferenceSelection` → immutable message request options → `InferenceService.resolve` → native run body → native group catalog admission → existing locked Hermes runtime → registered endpoint. Browser networking is separate and remains public-web-only.

- `runtime/hermes/native_inference.py`: enrolled-engine resolution, independent child catalogs, provider-pair admission and enrollment-drift check.
- `src/radhouse/chat/inference.py`, `app.py`: optional provider selection, sanitized catalogs, backward-compatible request snapshots.
- `src/radhouse/chat/static/inference-controls.js`: provider-qualified model options, selection preservation and capability lookup by pair.
- Existing inference Python/native-runtime/browser tests: failure isolation, duplicate model IDs, configuration/removal drift, frozen selection, real controls, serializer and no-fallback regression.

## Slices and acceptance

1. Native enrolled catalog and source-qualified provider resolution; preserve existing single-engine behavior and no secret/URL export.
2. Web pair validation and existing control; preserve legacy request snapshots, explicit unavailable selections and queue/retry semantics.
3. Focused and full owned verification, normal review/merge/main Sonar analysis and relevant-finding review.
4. Private operational packet: enroll both providers, grant only native backend access to the secondary text port, qualify actual streaming/tool continuation/context fit, then deploy exact source under current privileged authority. Do not infer VM220 rollout authority from the earlier VM270/Lucy temporary test grant.
5. Actual current-release S5 tool journeys, browser isolation, data preservation and strict lifecycle cleanup. Update private operational truth and close operator authority. Persistent provider enrollment and narrow backend admission remain selected; no automatic model startup or fallback is introduced.

Stop on source/configuration drift, foreign work, an unsupported native route, unknown retirement, 32K overflow or failed isolation. Preserve failed proof. Current endpoint performance/model quality is separate from routing and boundary acceptance; changing provider does not qualify a different model's behavior.
