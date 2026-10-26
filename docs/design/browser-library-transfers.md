# Browser–Library transfers (DW-2)

Status: implementation in progress. This document specifies the candidate; it is
not evidence that it has been deployed.

## User contract

A website's file chooser opens a Radhouse picker with **Your device** and
**Library**. A device selection is saved in Library before it is sent to the
website. Completed browser downloads are saved to the same Library automatically.
The existing save-to-device link downloads the original bytes.

Private mode is unchanged. Files acquired during Private takeover are visible to
the owner, excluded from assistant file catalogs and grants, and carry one small
Private label. **Share with assistant** is an explicit, persistent change for
that file. Ordinary transfers require no additional approval taxonomy. A file
chosen for a website grants that website the bytes; it does not grant a shell or
the assistant access to the rest of Library.

## D2 implementation contract

The web service owns durable file bytes, ownership and assistant visibility.
The existing native browser controller owns human leases, agent commands,
generation checks and Private/Observe policy. The SPACE guest owns only temporary
upload staging and a durable download outbox, observed through Chrome's fixed
file chooser/download protocol. Neither URLs nor filenames become filesystem
paths. No generic CDP endpoint is added to a user or model API.

The bridge moves bounded chunks with offsets and digests through the existing
authenticated service channel. It never assembles an entire original in RAM.
Upload commit rechecks the chooser identity, frame/document and destination,
then sets exactly the selected input. Navigation invalidates the chooser.
Uncertain website effects are not replayed automatically. Download intake uses a
stable launch/download identity, commits original bytes and metadata before
acknowledging the outbox, and is safe to reconcile after web-service interruption.
Private is the default when download provenance cannot be established.

Call paths and owned components:

1. `browser-files.js` → authenticated app routes → Library file service →
   `BrowserSessionService` → native controller → fixed guest file bridge → the
   intercepted file input. Device selection first uses the existing streamed
   upload store. UI IDs never identify host paths.
2. Chrome download events → guest outbox → native owner-scoped file bridge →
   web collector → `ChatStore` durable original and browser-file metadata →
   outbox acknowledgement. Closing must not discard an unacknowledged original.
3. Explicit file sharing → owner-scoped metadata update → subsequent frozen
   document grants. The host records first-observed download provenance outside
   the guest and can only tighten privacy thereafter. A run's own acknowledged
   download may enter that run's grant; this does not expose other Library files
   or expand an earlier grant after the owner shares a pre-existing file.
   Agent upload uses a scoped file capability and the existing
   agent command reservation; takeover revokes its ability to act.

Public schemas are additive. Existing upload rows retain their current behavior.
New browser metadata records provenance and sharing independently of filenames.
No cookies, browser profile, credentials, live content or operational topology is
included in public documentation or diagnostics.

## Delivery and validation

Deliver three slices: durable metadata and visibility; guest/native transfer
boundary; simple picker, collection and agent integration. Use synthetic tests
for ownership, stale generations/destinations, revoked leases, private grant
exclusion, explicit sharing, interrupted and duplicate intake, hostile names and
symlinks, multi-chunk binary integrity and close/restart races. Then qualify the
paired app/native/guest release and exercise device upload, Library upload,
human/agent download and Private sharing in the installed application.

Deployment retains existing stores and requires a protected pre-change recovery
set, idle native admission, exact release identities and health checks. Stop on
unresolved transfers, identity drift, failed authority checks or data mismatch.
Recovery reselects the qualified prior runtime while retaining durable Library
bytes; additive metadata must not be discarded by restoring an older database.

Chrome protocol references: [file chooser interception](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-setInterceptFileChooserDialog),
[file input assignment](https://chromedevtools.github.io/devtools-protocol/tot/DOM/#method-setFileInputFiles),
and [download events and behavior](https://chromedevtools.github.io/devtools-protocol/tot/Browser/#method-setDownloadBehavior).
