# Browser–Library transfers (DW-2)

Status: implemented candidate; installed acceptance in progress. Automated
qualification is recorded below. The browser lifecycle correction is deployed;
visible transfer and Private-mode acceptance remain open, so DW-2 is not yet
accepted as a delivered capability.

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

## Qualification and integration findings

The initial complete candidate (`71d5462`) passed 2,115 tests, with no failures,
errors or skips, and three JavaScript browser checks against an owned PostgreSQL fixture and pinned Hermes source. Coverage
includes original-byte integrity, ownership and Private grant exclusion,
explicit sharing, stale chooser and revoked lease refusal, outbox reconciliation
after a lost acknowledgement, and UI rendering with hostile filenames. Combined
line/branch coverage for the new web, native and guest transfer modules is
86.36%, 82.53% and 83.30%, respectively. This is local fixture coverage, not a
SonarQube feature-branch gate result.

Installed integration exposed three gaps beyond those initial fixtures:

- The bootstrap runtime map needed capacity for the additional verified module.
  Its bounded maximum is now 64, with exact path and digest validation retained.
- Non-secret qualification receipts must be readable by the unprivileged
  runtime even when an operator promotes under a private umask. Publication now
  explicitly sets their mode; configuration and recovery data remain private.
- The guest file observer needs the owned browser WebSocket endpoint, not the
  HTTP debugging origin. The real-Chrome transfer test now calls the production
  guest startup method, exercising that wiring before uploads and downloads.

The installed browser subsequently opened but retired during streamed input.
Content-free diagnostics identified a file-observer attachment failure. A real
Chrome regression reproduces the same failure by closing transient targets while
attachment commands are in flight. The correction tracks attached sessions and
ignores that command failure only after Chrome positively reports the session's
detach; errors for still-attached targets and transport loss remain fail-closed.
The regression fails before the correction and passes afterward. All 32 targeted
guest, file and real-Chrome tests pass, including live-target failure and detach
before the attachment task starts.

The complete synthetic qualification of `2b04659` also passed: 2,118 tests,
zero failures/errors/skips, three JavaScript browser checks and complete fixture
cleanup. Combined guest file-module line/branch coverage is now 85.54%; the web
and native file modules retain 86.36% and 82.53%. No feature-branch SonarQube
analysis or gate result is implied.

The correction is deployed and its cold-recovery source selects the same verified
module. Application health passed after admission was released. The visible
transfer and Private-mode walkthrough remains outstanding; successful synthetic
tests and deployment do not close that acceptance gap. Installation identities,
the resolved administration-access issue and operational evidence are retained
in the private deployment record.

This slice does not retain cookies or a browser profile across replacement;
that remains DW-3. Uploads currently select one original per chooser. A device
original saved through this picker starts Private, including when the browser is
in Observe mode, and can be shared explicitly from Library.
