# Make boundaries understandable

Status: accepted version 1.0 requirement; proposed interaction details below.
Updated: 2026-09-10. Implementation and usability qualification remain pending.

People should understand where work happens, who can see it, and what a bot can
access without learning infrastructure terminology. These are separate facts;
one reassuring lock icon cannot communicate all three.

## One small context card

Show this card when starting work and keep a compact version visible in its
conversation, files, and results. Expand details on demand.

| Example field | What an operator sees |
| --- | --- |
| Working in | **Project Cedar** |
| Visible to | **You and 2 project members** — view names |
| Working with | **Mira · Researcher**, **Rowan · Reviewer** |
| Available information | **Cedar project files and the 3 files you selected** — inspect full bot access |
| Internet | **Restricted access** — see what is allowed |
| Review | **Private review off** — security events still monitored |

These are synthetic examples. Derive labels from current effective grants and
audiences on the server. The selected task inputs are not the bot's complete
access: the expanded view must disclose other granted projects and retained
information when applicable. Do not describe a widely exposed bot as limited
to the three files just selected.

Use plain labels: **Only you**, **Project members**, **Shared with…**, and
**Supervised — these people can review…**. Show named recipients and the scope
of any supervised review. Explain the infrastructure administrator's underlying
access separately; “Only you” describes application visibility, not protection
from the machine owner. Use text and accessible icons, never color alone.

## Explain boundaries at the moment they matter

- **Starting work:** show context and audience before sending the brief to an
  inference route or bot. Keep recurring actions short when neither changed.
- **Adding a file:** show its destination and audience. Bringing private material
  into shared work needs the required content-and-audience review.
- **Sharing a result:** preview the exact version and named audience. Changed
  content or recipients invalidate the earlier approval. Do not share private
  history as an attachment to the result.
- **Moving work between projects:** treat any new audience as a publication
  decision. Offer to share an approved copy; dragging a card must not silently
  transfer its conversation, files, or a bot's permissions.
- **Requesting access:** say what is missing, why the task needs it, and who can
  decide. The operator can narrow the task or send an access request without
  needing to interpret a token scope or firewall rule. Do not reveal the names
  of resources the operator has no right to discover.
- **Reusing a bot across projects:** explain that it can retain what it has
  learned. For separate confidentiality boundaries, recommend a new bot from
  the same role template. A project switch does not erase memory or create
  isolation. Revocation blocks future access but cannot promise forgetting.

Task admission and publication must recheck the current audience, grants, and
content revision. A stale browser tab or a renamed project cannot bypass them.
Task labels, alerts, search suggestions, and filenames follow the same audience
rules as content. Private task summaries must not leak into global dashboards.

## Keep everyday use calm

Ask for decisions when access, audience, or consequential authority changes.
Use inline explanations for ordinary blocked actions. Reserve interrupting
warnings for an actual boundary change or material incident. Put fleet-wide
security findings and update plans in the administrator's view; operators see
their affected work and maintenance availability, and viewers remain read-only.

## Evidence before calling the experience intuitive

With unfamiliar non-technical participants, verify that they can start work,
identify its audience, explain the bot's wider access, share a selected result,
and request missing access without coaching. They should distinguish private
content review from security-event monitoring and understand the retained-data
warning when reusing a bot. Test keyboard/screen-reader use and text labels.

Pair usability checks with server-side denial tests for stale approvals,
unauthorized names/search, cross-project moves, and grant changes. A clear screen
is useful only when the underlying boundary holds.

See the [work model](work-model.md), [security supervisor](security-supervisor.md),
and [naming preferences](naming-preferences.md) for the related contracts.
