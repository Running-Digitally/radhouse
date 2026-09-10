# Naming preferences

Status: four changeable presets and individual overrides are accepted version
1.0 requirements. Defaults, examples, and precedence below are proposed design.
Updated: 2026-09-10. No naming implementation exists yet.

Give an installation a personality without changing how its boundaries work.
Offer a live preview in **Setup → Preferences → Naming**, and make the same
setting available later. Installation should not require inventing a naming
convention before anyone can start useful work.

## Four presets

| Preset | Bot example | Project example | Task example |
| --- | --- | --- | --- |
| **Numbered** | Bot001 | Project001 | Project001-Task001 |
| **Friendly names — recommended default** | Mira | Cedar | Compare three approaches |
| **Themed names** | Nova | Orion | Compare three approaches |
| **Custom — no preset** | Name it yourself | Name it yourself | Name it yourself |

The first uses type plus a zero-padded counter. Bot and project counters are
installation-wide; task counters are within their project, including a private
work context. Counters are allocated atomically, never recycled, and expand
beyond 999. They are readable labels, not authorization tokens. Explain that
sequential names can reveal approximate object counts to people who see them;
use friendly names where that information matters.

Friendly names use neutral bot names and neutral project codenames. Task titles
summarize the requested work in ordinary language. Themed names add a choice
such as **Astro**, **Mythical**, **Modern**, or **Popular names** for bots and
projects. Preview the actual word lists: “popular” depends on language and
culture. Task titles stay descriptive; avoid making a routine comparison sound
like a mythical quest. Offer separate bot/project theme choices in advanced
preferences without making first setup longer.

Custom asks for a display name at creation and offers no invented identity or
theme. A blank draft may use a neutral temporary label such as “Untitled task”;
its permanent internal ID already exists. Before starting or saving a named
object, the person supplies its name or explicitly selects a generated suggestion.

## Defaults and overrides

Proposed precedence: an explicit name on an item wins over its context's naming
preference, which wins over the installation default.

- Administrators set the installation default and name/provision new bots.
- A personal preference can govern objects a person is permitted to create.
  A shared project's authorized settings editor can choose its task-title
  preference; this takes precedence over a member's personal preference there.
- Creators can override suggestions within their normal create/edit rights.
  Existing shared items need the corresponding rename permission. A naming
  preference never grants creation, project administration, or extra bots.
- Changing preferences affects **future items**. Existing names and explicit
  overrides remain. Individual renaming is available immediately; a future bulk
  rename would require an explicit preview and apply action, not a theme change.

The UI should show where an inherited preference comes from and offer **Use
installation default**. Exact project settings permissions remain part of the
human-role design; operators do not receive them solely by selecting a preset.

## Permanent identity, editable name

Keep immutable IDs and stable references separate from display names. Renaming
must preserve links, grants, memory, task references, and audit history. The
numbered task label remains stable if a project is renamed; do not cascade
renames. Archived objects retain their old identity and reserved references.

Allow duplicate human names with a short stable disambiguator wherever selection
could be ambiguous. Recheck collisions without exposing hidden objects. Always
show role and project context alongside names at consequential choices. The
platform's verified **Security supervisor** badge comes from its system identity;
calling an ordinary bot “Security supervisor” must not impersonate that role.

Neutral and themed suggestions should work from bundled, reviewed local word
lists without inference. A task summary can use the brief's first line or an
explicitly selected compatible local inference route; title generation must not
send private content elsewhere or silently switch providers. Store and display
generated titles under the task's audience rules. Never summarize secret values
into notifications. People can edit every suggestion before accepting it.

## Acceptance examples

Verify all four presets, collisions and concurrent counters, numbers beyond
999, per-item overrides, future-only preference changes, theme reset, and rename
permission denial. Renaming must preserve old links and audit references.
Private titles must remain absent from unauthorized search, notifications, and
name-collision responses. Verify useful offline naming and manual fallback when
the selected inference route is unavailable.

See [boundary experience](boundary-experience.md) for audience disclosure and
the [work model](work-model.md) for persistent identity and role templates.
