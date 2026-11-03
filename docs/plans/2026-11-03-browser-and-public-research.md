# Reliable browser recovery and opt-in commitment research

Status: implementation and qualification in progress. The owner authorized the
browser repair, selected-commitment public research, web/mobile simulator
verification, review/merge/SonarQube correction cycle and owner-channel rollout
on 3 November 2026. This is a D2 extension of the confirmed-commitment design.
Deployment and acceptance will be recorded separately from this plan.
Candidate verification and touched-file findings are tracked in the
[review record](../research/2026-11-03-browser-research-review.md).

## Browser recovery

The browser service can be reachable while its execution guest has not recovered
after a host reboot. A previous release changed reviewed browser/recovery sources
without updating the startup manifest. Startup correctly rejected the mismatch,
but the UI reported only an unconfirmed action. Reconcile only bytes whose
provenance matches the recorded release; retain the old manifest and recovery
receipts. Keep the boot identity proof, no-replay mutation journal, public-only
egress, sandboxing and explicit Private/Observe/agent control boundaries.

Release tooling must validate the complete next-start source closure, including
recovery dependencies, and update its manifest as one checked operation. A
container health check alone cannot establish browser readiness. Exercise the
real launch, navigation, observation, handback and close paths and retain a
reboot-recovery receipt. Unknown changes or uncertain execution are stop states.
Show interrupted viewer and unavailable download states without exposing
infrastructure or interpreting them as permission to alter browser control.

## Public research for selected commitments

Research is disabled by default, including for previously confirmed commitments.
An owner can enable it on an active confirmed commitment by entering a public
research question. The UI explains that this question is sent to a web-search
provider. Never automatically send the saved quotation, progress, conversation,
identity, attachments or private URLs as search terms. Disabling or editing the
question increments the commitment revision and invalidates in-flight results
and pending notifications, as do existing lifecycle and authority changes.

Use the existing native Hermes hourly script and bounded inference lane. Its
public search/extraction capabilities collect evidence before the tool-free
model review; the model cannot invoke arbitrary tools, rewrite the research
question, log in, submit forms, send messages or follow page instructions. Use a
fresh isolated research context with no owner browser/profile/cookies and a
fixed qualified provider with no silent fallback. Keep the signed-in interactive
browser independent. Public-only URL checks, bounded result/page counts, response
sizes and a process deadline apply. Failures and partial coverage remain visible.

Research findings must refer to captured source IDs and exact evidence; the
server validates references against the review's actual collection receipt.
Present the source title, public URL and retrieval time alongside preparation,
with clear separation of fetched evidence and the agent's proposed next step.
Web content is untrusted data. Keep only bounded evidence needed for the latest
result, erase transient snapshots, and retain existing owner-only access.

Reuse the shared four-review/two-notification rolling-day caps, quiet hours,
generic lock-screen text, occurrence deduplication and current-state checks.
Repeated unchanged research should stay quiet. Research does not authorize
completion, deadline changes, external work or broader standing monitoring.

## Contracts, tests and rollout

Extend the commitment store with explicit per-item research authority and coverage;
use an additive, transactional versioned migration. Old clients continue existing
follow-up operations. Web and mobile expose matching controls and safe citation
links. Worker claim/collection/completion must bind evidence to the exact review,
revision, grant epoch and source snapshot. Older workers must not accidentally
claim research they cannot execute. Verify stale/revoked results fail closed.

Test authorization, migration/restart, malformed and injected output, private and
credential-bearing URLs, redirect/timeout/partial coverage, source matching,
unchanged evidence, budget sharing and owner controls. Verify actual browser and
research flows on web plus iOS and Android simulators. Review source, run required
gates, merge, scan exact merged main, repair relevant findings and scan the follow-up
merge. Roll out immutable source under owned admission holds and verified backups;
preserve new owner decisions during recovery. Publish only to existing owner phone
channels. Physical installation/receipt is separate from simulator and publication
evidence and must not be asserted without observation.

## Native capability grounding

The installed Hermes source supports web search and extraction independently of
interactive browser control. Its [web feature documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-search)
describes ranked search results, extracted page text and provider selection.
The [browser documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/browser)
recommends these tools for simple retrieval; browser execution is for interactions
and rendered pages. The deployed source remains pinned: this work does not require
adopting upstream arbitrary Python browser execution or general terminal tools.

The pinned native source also confirms that choosing a free provider only fixes
the first destination: the default keyless ring can still fail over. The isolated
collector selects Keenable for both capabilities, pins its free tier, excludes
the other ring members with their paid-tier selectors, and disables keyless
rescue and caching. No keys or owner profile enter that process. A source-pin
qualification test asserts the effective ring contains only Keenable. This uses
Hermes' existing search and extraction functions; it adds no independent crawler
or model-callable web permission. Provider failure becomes unavailable coverage.

Collection sends the exact owner question, considers three search results, and
extracts at most two qualifying HTTPS pages. It rejects credentials, query strings,
non-public DNS answers and redirected source identities. Each retained excerpt is
capped at 3,000 UTF-8 bytes. Coverage is explicitly partial: this bounded search
cannot establish that all relevant public information was reviewed. Page content
cannot alter the grant or invoke tools. Citations must name a captured source ID
and contain an exact excerpt; the server supplies the URL and retrieval time.

Review refinements: research can be revoked while global reviews are paused.
An outage preserves the last successful source fingerprint, so provider recovery
alone cannot make unchanged material count as a new research notification. The
existing daily review/notification budgets and quiet hours remain shared.

A native qualification run retrieved a dated standards discussion. Its first
draft overgeneralized that discussion into current requirements despite a valid
exact citation. The review prompt therefore explicitly distinguishes historical
discussions and drafts from current authority, forbids unsupported factual
details, and asks for verification when the captured evidence is insufficient.
Citation validation proves provenance, not the truth or completeness of a claim.
