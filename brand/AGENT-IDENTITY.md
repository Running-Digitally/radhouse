# Agent identity and appearance concept

This is a single-agent design proposal and a working local mockup, not a deployed
settings implementation. The owner requested an isolated worktree and branch,
reuse of the in-progress Radhouse icon family, and raster character identities.

## First-class identity

The first navigation item is the agent's display name. When the trimmed name is
empty it is **Your Agent**, above Chat, Library, Browser, Settings and
Infrastructure. Selecting it opens the agent profile. The desktop and mobile
fixed header centers the round portrait itself, not the combined portrait and
status group. A separate Radhouse house mark to its right communicates state.
Mobile navigation uses a focus-trapped drawer, keeping the identity above Chat
in the same vertical menu. Escape or the backdrop dismisses the drawer.

The portrait represents identity and does not morph into a thinking animation.
The adjacent status mark uses the shared icon family, with smoke, idle zzz,
working circulation, waiting, pause and completion. Text accompanies status. Actual
runtime states must come from existing authoritative reply/control status when
implemented; this mockup explicitly offers a synthetic state picker.

The profile has Identity and Appearance tabs. Identity offers a name, a short
introduction, themed character portraits and an optional uploaded raster image.
Appearance offers profile accent, independent agent-state and interface-icon
motion controls, and paper/evening/device surfaces. Device reduced motion always
wins. Existing Settings remains available for application and infrastructure
configuration; its mockup shortcut opens Appearance.

## Character collection

| Character | Theme | Small backstory |
| --- | --- | --- |
| Ember, fox | Hearth | Once the keeper of a tiny hillside inn. Now keeps the light on while you find your next good idea. |
| Moss, field mouse | Grove | A collector of overlooked details and well-thumbed notebooks. Believes good ideas grow with a little patience. |
| Aster, barn owl | Orbit | A quiet navigator with a sky full of questions. Turns faraway possibilities into a next step you can take. |
| Lumi, hare | Fable | A moonlit storyteller who sees connections others miss. Makes a little room for the unexpected. |

These are alternative identities for the same agent, not multiple agents or new
capabilities. Portraits are generated raster illustrations; UI/status glyphs
reuse the existing original SVG family. The visual language is tactile,
thoughtful, warm and slightly whimsical, with sage, ivory and terracotta tying
the character worlds together. Backstories are profile flavor, not instructions
or a promise of changed runtime behavior.

## Interaction and persistence

Edits update the portrait, menu name, header, and chat preview immediately.
Save commits only to the preview's namespaced browser-local storage. Discard
restores the saved draft. Reset stages defaults, requiring Save to keep them.
The empty-name fallback is intentional. Suggested names remain optional.
Selecting another character preserves an explicitly edited name/introduction.
Uploaded PNG/JPEG/WebP portraits stay in the browser (1 MB limit); they are
never sent to a service. No live authentication, agent, model, or settings API
is connected. Adjacent menu items are context for this mockup.

## Implementation proposal

Persist display identity separately from the agent's immutable runtime ID:
display_name, introduction, portrait_asset_id, character_preset, profile_accent.
Keep personal interface surface and motion preferences in user presentation
settings. For a shared installation, settle edit ownership and whether display
identity is installation-wide before connecting writes. Renaming must preserve
memory, saved conversations, permissions, runtime bindings, and links.

Store uploaded images as validated, decoded raster assets with bounded size;
reference them by asset ID. The mockup's local data URLs are a preview mechanism,
not the proposed production storage contract. Selecting a profile must not
rewrite system prompts, memory, model selection, permissions, or user biography.

## Preview

Run `python3 brand/preview_settings.py --port 61491` and open
<http://127.0.0.1:61491/>. The server binds only to loopback and serves an explicit
asset allowlist. No dependency installation or frontend build is needed.

The source worktree is based on `codex/icon-browser-design` at `61a4a13`.
The preview uses the current stateful icon iteration, copied into
`agent-icon-snapshot/` with SHA-256 provenance. Only its presentation files are
snapshotted; that chat's unfinished product behavior stays in its own branch.
Portrait prompts are saved in `characters/PROMPTS.md`.

## Validation on 2026-10-08

The in-app browser verified the initial Your Agent fallback, character selection,
name propagation in the menu/header/chat, a custom name retained across character
changes, Save followed by reload, Discard, and resetting to the Ember review
preset. Appearance controls and evening mode were exercised. With interface
motion off, thinking smoke still used rh-smoke; turning off agent-state motion
then left smoke visible at opacity 0.65 with no animation.

Measured CSS widths 1200, 390 and 320 showed no horizontal overflow. At 320,
the portrait center was x=160 and the brand did not overlap it. The menu,
portrait, and status controls measured 44 by 44 CSS pixels (rounding within
0.01 px). The 390px mobile drawer placed Ember above Chat, Library, Browser,
Settings and Infrastructure, made the background inert, closed with Escape,
and wrapped keyboard focus from Close to Infrastructure and back. Arrow-key
navigation between Identity and Appearance passed. The current renderer exposes
its actual shared named icon parts. No browser console errors were observed.

JavaScript syntax and Git whitespace checks passed. All eight public fixture
asset URLs returned 200. Requests for Git files, repository files and traversal
paths returned 404. No dependency installation or full product build was needed.
Device reduced-motion support is implemented in both the shared icons and the
mockup styles; the OS preference itself was not changed during verification.
Uploaded-image success and browser-storage exhaustion were not exercised.
