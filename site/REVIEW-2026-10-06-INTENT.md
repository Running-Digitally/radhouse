# Radhouse visual revision: one assignment over time

Historical revision. Superseded by the accepted smaller web scope in
[the current review receipt](REVIEW-2026-10-06-WEB-ONLY.md). Its Buzz and
assignment explanation no longer appears on the public page.

6 October 2026. Local candidate at http://127.0.0.1:8931/?analytics=preview.
No public release, commit, push, PR, branch switch or application change.
This supersedes the house illustration in the first review receipt.

## Owner direction and reference

The owner preferred the clearer page but disliked its visual and interaction.
They asked to apply Tomas Pueyo's
[Shallow Intent: Why People Don't Like AI Content, and How to Make It Great](https://unchartedterritories.tomaspueyo.com/p/shallow-intent-why-people-dont-like)
and its supplied extract at
`[private local workspace]`.
Both were read. The extract contains the article's poster discussion and
conclusions; the live page confirms the article and its publication context.

The design principle taken from the article is to make visible detail repay
closer attention, with a reason for each element and movement. This is an
application to Radhouse, not an endorsement of every general claim about AI
in the essay. The cupboard's hinges and roof did not explain retained work,
follow-up or the person's authority. They have been removed.

The accepted sati.sh and Running Digitally references remain the basis for
the restrained page, deliberate interaction, single reading path and truthful
copy. Their references and maturity grounding remain in the historical
[first receipt](REVIEW-2026-10-06.md).

## What the drawing means

A hand-authored SVG shows one Researcher and one assignment over time. Its
simple planes use the existing green, cream and clay palette. No generated
texture or borrowed poster artwork is used.

| Element | Meaning and behavior |
| --- | --- |
| Clay question slip | A person's ordinary Buzz message enters the assigned agent's workspace. |
| Fixed green frame | The retained workspace on the operator's infrastructure. It stays in place throughout the example. |
| Comparison sheet | An illustrative draft organized by recovery time, cost and upkeep. No actual backup recommendation is invented. |
| File holder | The comparison and source notes stay with the agent during follow-up and after review. |
| Follow-up slip | A second question reaches the same Researcher and can use its earlier work. |
| Result moving out | The result returns to the person for review. The diagram stops there; it never animates publication. |
| Review label | The destination becomes signed-in Radhouse review, with exact result and audience checked before publication. |

Product grounding was checked in `README.md`, `PRINCIPLES.md` and the official
Buzz pilot packet. This remains an explicitly labelled illustration, not a
live agent, an actual output, a product screenshot, or a qualified V1 claim.
The public pilot/release copy is unchanged.

One next action advances Ask, Work, Follow-up and Review. The four stages can
also be revisited directly. One explanatory panel is exposed at a time. The
illustration is visible immediately and the opening link brings it into view.
There is no introductory opening/closing mechanic, autoplay or ambient motion.
The question's delivery lasts 0.7 seconds once; the result's travel is a finite
transition. Reduced motion presents the completed state without travel.

## Verification

Current evidence is under ignored `outputs/review-20261006-intent/`:

- `layout-checks.json`: 32 states across actual widths 319, 390, 521, 600,
  800, 1101, 1280 and 1440. No horizontal page overflow, reading-panel overflow
  or illustration height change between stages. Question and comparison text
  fit their paper boundaries. File positions stay identical in Work, Follow-up
  and Review. Settled geometry uses the reduced-motion fixture.
- `keyboard-checks.json`: Left/Right, Home/End and Tab navigate correctly.
  Enter advances and restarts the sequence while keeping focus on the next
  action. Exactly one panel is visible. The polite status region describes
  the changed stage.
- `motion-checks.json`: normal initialization has no animation; delivery runs
  once for 0.7 seconds. The source-backed reduced-motion fixture has no
  animation, zero transition duration and automatic scrolling. The unenhanced
  fixture has no scripts, hides inactive controls and exposes the complete
  prose explanation and 15 reading/navigation links.
- Desktop and narrow screenshots cover the finished page and follow-up state.
- `source-checks.json`: unique HTML/SVG IDs, resolving ARIA/anchor targets,
  existing local assets, all nine external destinations retaining new-tab and
  noopener/noreferrer attributes, and all 23 unrelated dirty/untracked files
  remaining byte-identical to the starting snapshot.
- `source-manifest.json` and `served-assets.json`: source hashes and loopback
  responses under the deployment's actual security headers.

The three existing brand tests and four analytics-policy tests passed.
JavaScript syntax and Git whitespace passed. The normal preview reports
PostHog initialization as ready and has no browser warning/error logs.
Analytics events now record the assignment stage and whether it was selected
with a tab, keyboard or next action; no old opening/closing event is emitted.

Reduced-motion and unenhanced checks use isolated preview fixtures, not an
OS preference change or a browser with JavaScript disabled. Physical phones,
Safari/Firefox and screen-reader speech are not tested. Earlier external-link
HTTP checks still apply to the unchanged destination set.

Private PostHog ingestion/replay verification remains pending the dashboard
permission requested in the first round. This revision does not seek private
analytics access or change the existing analytics policy. No deployment has
been authorized. Only `site/` was changed; the active branch and HEAD remain
`fix/project-deploy-after-cancelled-review` at
`64c75cd8b6676226a148fb2efd83c30bc531daff`.
