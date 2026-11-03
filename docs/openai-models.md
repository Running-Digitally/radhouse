# OpenAI models in connected chat

Radhouse can enroll a named OpenAI provider alongside existing local providers.
Web and native mobile discover it from the authenticated chat server. Enrollment
is opt-in and does not change the configured default model or existing Nemo/Lucy
entries.

| Display name | API model ID | Explicit thinking choices |
| --- | --- | --- |
| GPT-6 Astra | `gpt-6-astra` | low, medium, high, xhigh, max |
| GPT-6.1 Terra | `gpt-6.1-terra` | off, low, medium, high, xhigh, max |
| GPT-6.1 Sol | `gpt-6.1-sol` | low, medium, high, xhigh, max |

Default preserves the configured reasoning setting. Terra's Off serializes as
`reasoning.effort: none`. Ultra is not offered as a distinct API reasoning level.
These choices were checked against the [OpenAI model guide](https://developers.openai.com/api/docs/guides/latest-model)
and [Astra model reference](https://developers.openai.com/api/docs/models/gpt-6-astra)
on 2 November 2026. Models are additionally checked against the account's live
`/models` response; a missing model remains unavailable.

## Server setup

Merge [the example entries](../deploy/production/hermes-openai.example.yaml)
into the existing Hermes profile, preserving the existing provider list. The
provider selector is `custom:openai`; its only qualified endpoint is
`https://api.openai.com/v1`, with native `codex_responses` transport. The provider
reads the environment variable **`RADHOUSE_OPENAI_API`**. Supply just that value
through the runtime's existing private secret/environment mechanism. Do not
copy a complete operator dotenv file into the repository, image, mobile app,
or web server's public configuration.

The user interface receives model IDs, labels, availability and capabilities.
It never receives the key or endpoint configuration. Explicit choices are
frozen with each request and revalidated before execution. Configuration drift
or unavailable models fail visibly; they do not silently switch provider.
Default remains the existing default-model path.

The Hermes overlay adds `gpt-6.1-terra` to the pinned Responses effort family.
Without this adjustment, upstream's serializer clamps Terra's `max` to `xhigh`.
The overlay validates source hashes and exact replacement context and fails
closed if upstream changes. Regression tests exercise the actual pinned
Responses serializer with function tools and every offered effort, including
Terra Off.

## Rollout acceptance

Build and qualify the source-pinned runtime overlay, inject the named secret
into the private runtime environment, merge the provider entry without replacing
local providers, then restart through the normal recoverable rollout procedure.
Verify authenticated discovery from web/mobile and one synthetic tool-backed
reply per model before treating the provider as deployed. Keep rollback to the
prior runtime/configuration available. Selecting OpenAI sends conversation and
included tool/context data to OpenAI; both clients disclose this when choosing
models.

Implementation checks included account visibility for all three model IDs and
successful synthetic tool-call/answer round trips. These checks do not mean the
production runtime or released mobile apps have been updated. The usability
audit and implementation evidence are in the [connected-chat audit](research/2026-11-02-connected-chat-audit.md).
