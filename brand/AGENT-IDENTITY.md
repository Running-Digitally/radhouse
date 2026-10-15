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
implemented; this mockup offers an interactive synthetic state arc around the portrait.

The profile has Identity and Appearance tabs. Identity follows a visible sequence:
choose a theme, pick its character, then optionally personalize the name. A short
introduction and the selected character’s backstory are disclosed only on request.
An uploaded raster portrait remains available below the character choices.
Appearance offers profile accent, independent agent-state and interface-icon
motion controls, and paper/evening/device surfaces. Device reduced motion always
wins. Existing Settings remains available for application and infrastructure
configuration; its mockup shortcut opens Appearance.

## Character collections

The original four portraits form **Hearthside**. The owner directionally accepted
the images across all four collections for the first version on 2026-10-08 and
liked the Appearance settings. Identity and the state arc are being refined for
review. Each collection has a different material and character language; all
are identities for one agent.

| Collection | Visual language | Characters |
| --- | --- | --- |
| Hearthside | Woodland storybook | Ember, Moss, Aster, Lumi |
| Kiln Club | Handmade ceramics | Miro, Nori, Pebble |
| Paper Trails | Cut-paper adventurers | Rue, Kit, Sol |
| Signal Station | Retro-future explorers | Beacon, Echo, Orbit |

| Character | Collection | Small backstory |
| --- | --- | --- |
| Ember | Hearthside | Once the keeper of a tiny hillside inn. Now keeps the light on while you find your next good idea. |
| Moss | Hearthside | A collector of overlooked details and well-thumbed notebooks. Believes good ideas grow with a little patience. |
| Aster | Hearthside | A quiet navigator with a sky full of questions. Turns faraway possibilities into a next step you can take. |
| Lumi | Hearthside | A moonlit storyteller who sees connections others miss. Makes a little room for the unexpected. |
| Miro | Kiln Club | Born beside a potter’s warm kiln, with a leaf for a lucky charm. Finds a useful shape for ideas that are still a little soft. |
| Nori | Kiln Club | A sea-glass spirit who tends a windowsill garden. Notices what needs care before it asks. |
| Pebble | Kiln Club | Smoothed by a thousand quiet river mornings. Patient with tangled plans and very good at one thing at a time. |
| Rue | Paper Trails | A courier who knows every shortcut through the paper city. Carries good questions wherever they need to go. |
| Kit | Paper Trails | Keeps a workshop full of promising offcuts and half-finished wonders. Can usually make something work with one more fold. |
| Sol | Paper Trails | Maps places that haven’t quite been imagined yet. Leaves enough blank space for a happy detour. |
| Beacon | Signal Station | Tends the welcome light on a quiet orbital station. Makes unfamiliar territory feel like somewhere you belong. |
| Echo | Signal Station | An old radio operator with a talent for hearing the useful bit through the static. Keeps a dry joke on the spare channel. |
| Orbit | Signal Station | Collects star charts and improbable routes home. Turns big possibilities into a course you can actually follow. |

Portraits are generated raster images; UI/status glyphs reuse the accepted V1
SVG icon family. Backstories are profile flavor, not agent instructions or new
runtime capabilities. The separate [character catalog](characters/catalog.js)
provides stable portrait and collection IDs for later main-UI reuse.


## Interaction and persistence

The Identity flow follows [the no-manual principle](../PRINCIPLES.md): theme,
character, optional name. Theme cards show their characters visually. Changing
theme immediately selects its first character, or the character last selected in
that theme during the current edit. The radio selection, preview, and header
portrait stay in agreement. The full character set is visible together where
space allows. Long backstories are available behind About in the preview instead
of competing with every portrait choice.

Edits update the portrait, menu name, header, and chat preview immediately.
Save commits only to the preview's namespaced browser-local storage. Discard
restores the saved draft. Reset stages defaults, requiring Save to keep them.
The empty-name fallback is Your Agent. Character names are optional suggestions;
an explicitly entered personal name/introduction survives theme and portrait
changes. On compact screens, the form comes first, the live profile follows,
and Save comes after the preview. The fixed header provides immediate identity
feedback throughout.

Six state buttons form a semicircle around the preview portrait. Mouse/pen hover
temporarily previews a state in the profile and fixed-header house mark; leaving
returns to the clicked selection. Click or tap selects the state until another
is selected. Keyboard focus previews, arrow keys move focus, and Enter/Space
select. The selected state remains visibly marked while another is previewed.
These interactions do not dirty or save identity settings. The state examples
remain local to this page session and do not send runtime commands.

Uploaded PNG/JPEG/WebP portraits stay in the browser (1 MB limit); they are never
sent to a service. No live authentication, agent, model, or settings API is
connected. Adjacent menu items are context for this documentation mock.

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
The icon snapshot now pins the accepted V1 source at `f54fc1f`, with SHA-256
provenance in `agent-icon-snapshot/README.md`. Only presentation files are
snapshotted. Portrait prompts are saved in `characters/PROMPTS.md`.

The [runnable documentation mock and component reuse map](../docs/design/agent-identity.md)
is the integration handoff. This preview remains checked in as the visual reference
when its components move into the main UI. It has no external assets or framework
dependencies, and its relative paths also work under ordinary static hosting.

## Initial preview validation on 2026-10-08

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

## Previous theme iteration validation on 2026-10-08

The updated in-app browser verified all four collection controls and all new
gallery images. Browsing Kiln Club from the saved Ember identity left the portrait
and name unchanged and Save disabled. Selecting Miro, saving and reloading restored
Miro and its collection. A saved suggested name followed the next selected
character. A personal name and introduction survived portrait changes across
Paper Trails and Signal Station. Discard restored Miro and its collection, and
blank-name fallback remained Your Agent throughout the header/menu/profile.
Native ArrowRight changed the browsed collection without changing identity.

At CSS widths 1333, 390 and 320 there was no horizontal overflow. The header
portrait remained centered (x=195 at 390; x=160 at 320), and all displayed images
loaded. The mobile drawer retained the name above Chat and keyboard focus wrapped
between Close and Infrastructure; Escape dismissed it. The updated V1 icon
snapshot retained independent mock motion behavior: interface motion off left
thinking smoke animated, while agent-state motion off left static smoke visible
at opacity 0.65. The browser reported no warnings or errors.

All 21 explicit public routes returned their saved file bytes; five unrelated or
traversal paths returned 404. All nine new portraits match their original generated
files byte-for-byte. JavaScript/Python syntax and Git whitespace checks passed.
Documentation relative links were checked against the worktree. Desktop/mobile
captures are checked in with the documentation; the runnable mock remains the
canonical interaction reference. The same upload/storage/OS-preference limitations
recorded for the initial preview still apply. No product build or dependency
installation was required for this static documentation mock.

## Identity refinement validation on 2026-10-08

The revised Identity view was checked in the in-app browser. Choosing Paper Trails
selected Rue and changed the header/profile immediately; selecting Sol, switching
to Signal Station, then returning restored Sol. A custom name and introduction
survived theme changes. Discard restored the saved Miro identity and collapsed
the optional introduction. The external form-associated Save button persisted
Nori across reload; Miro was then restored and saved as the review fixture.

With Working selected, native pointer hover previewed Paused while the selected
button stayed Working; leaving restored Working. Clicking Paused and leaving
kept Paused. ArrowRight focused and previewed Completed without changing the selection;
Enter selected Completed and the state survived focus moving outside the arc.
The page contains no select/dropdown elements. State selection leaves identity
Save disabled.

CSS widths 1600, 1333, 1024, 390 and 320 showed no horizontal overflow. At 320,
all six state targets were at least 54 × 60 pixels, with no overlapping target
rectangles; the header portrait center was x=160. At 390 the center was x=195.
On mobile the Save bar follows the profile preview. Appearance's evening surface
and independent motion controls were exercised again; static smoke retained
opacity 0.65. No broken displayed images or browser warnings/errors were observed.
JavaScript syntax, relative documentation links and Git whitespace checks passed.
The 21 explicit fixture routes match their saved files; unrelated paths stay 404.

The updated screenshots and component map describe this revision. The owner
reviewed the mock and authorized committing the work so far on 2026-10-08.
Previously recorded upload/storage/OS-preference testing limitations still apply.
