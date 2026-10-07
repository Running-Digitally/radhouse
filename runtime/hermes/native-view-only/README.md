# Native browser view-only artifact

This patch owns the native transport boundary for the Radhouse observer. It
applies only to official `agent-browser` v0.38.2, commit
`39a74c70d7759d5a6de7a22c04570bb626bbd081`. The private Hermes relay observes
the same browser that the admitted seven native tools control through the
existing CLI and Unix socket. No new network policy, proxy, service or VM is
introduced.

Upstream's Apache-2.0 license is retained in `AGENT-BROWSER-LICENSE.txt`.
`native-view-only.patch` records Radhouse's changes to the six source files in
`source-lock.json`; the upstream source archive remains unchanged. Retain the
upstream and bundled third-party notices with any distributed native artifact.

## Resulting contract

- Both native session HTTP and optional dashboard HTTP reject all methods
  except GET, before reading bodies or invoking command, exec, kill, chat or
  session creation handlers. Matching origins and dashboard tokens cannot
  enable those routes. Requests carrying any Origin header are rejected too.
  Every `/api/` HTTP route is disabled even for a no-Origin GET, closing
  inventory/status disclosure through same-origin DNS rebinding. Only embedded
  static assets remain available over HTTP; the private relay receives status,
  tabs and frames over its no-Origin WebSocket.
- The session WebSocket rejects the presence of any Origin header, including
  loopback, file, opaque `null`, empty and invalid values. A private nonbrowser
  relay without Origin can still receive the native stream.
- Both HTTP entry points inspect the complete header through its terminator
  before dispatch. Headers are bounded to 16 KiB with a two-second deadline;
  incomplete, oversized, malformed or duplicate-Host requests fail closed.
  The bytes stay unread for an accepted WebSocket handshake. Socket tests
  cover split Origin delivery and Origin beyond the former peek limits.
- The WebSocket reader discards all text/binary application messages before
  parsing or touching CDP, browser input, activity or delivery settings.
  Protocol Ping/Pong and Close remain functional. Pong flushes also work when
  a stationary page produces no new frames.
- Server frames, status, tabs, latest-frame caching, generation clearing and
  lifecycle ownership remain upstream behavior. The handshake FPS cap remains
  available, but application/URL acknowledgement pacing cannot hold frames.
  The Radhouse relay bounds its own retained JPEG and polling.
- Global native configuration stops at the first literal `--` boundary.
  `clean_args` removes that boundary and preserves every following argument.
  The Hermes adapter must put fixed configuration/session globals before the
  admitted command, then `--`, then all model-derived command arguments.
  Snapshot references and key names still require the adapter's narrow checks.
  The main program's help/version scans honor the same boundary.

The patch updates positive upstream control tests to expect denial and adds
native regressions for HTTP mutation/origin denial, an untouched CLI socket,
WebSocket Origin denial, no CDP input dispatch, continued frame progression,
stationary Pong delivery and literal flag-like text parsed as a fill value.
Interactive helper code needed only by old isolated upstream unit tests is
compiled under `cfg(test)`; the release stream module has no input dispatcher.

## Frozen inputs and build

`source-lock.json` owns the source archive, exact modified-file before/after
hashes, patch hash and Cargo lock hash. The bootstrap's `source_sha256` means
the archive SHA256; `patch_sha256` means the patch file SHA256. Upstream npm
integrity is provenance only: a patched executable requires its own actual
binary hash. No upstream release binary is represented as patched.

Source archive:
`https://codeload.github.com/vercel-labs/agent-browser/tar.gz/39a74c70d7759d5a6de7a22c04570bb626bbd081`

Archive SHA256:
`f95f730316f2849fd62f41b2153f06fc6b78c76636270f98495c7e773ef77274`

The selected build toolchain is Rust/Cargo 1.99.0 in an official
`rust:1.99.0-bookworm` image pinned by digest in the build receipt, targeting
`x86_64-unknown-linux-gnu`, using the source-defined optimized `ci` Cargo
profile (thin LTO, 16 codegen units). Upstream release automation uses its
`release` profile; this reviewed artifact uses `ci` to shorten validation
rebuilds. Both are optimized profiles, and the actual choice belongs to the
build receipt. No runtime contract requires upstream full-LTO output.
Upstream itself uses moving Rust stable. This folder
does not claim compilation or qualify a toolchain until an actual receipt
records `rustc --version --verbose`, `cargo --version`, the image digest,
build/test results and the produced binary hash.

From the unpacked source root, with `PATCH_DIR` pointing to this directory:

```sh
python3 "$PATCH_DIR/verify_source.py" .
git apply --check "$PATCH_DIR/../native-view-only.patch"
git apply "$PATCH_DIR/../native-view-only.patch"
python3 "$PATCH_DIR/verify_source.py" . --patched
cargo test --locked --manifest-path cli/Cargo.toml radhouse_ -- --test-threads=1
cargo test --locked --manifest-path cli/Cargo.toml native::stream -- --test-threads=1
cargo test --locked --manifest-path cli/Cargo.toml flags::tests -- --test-threads=1
cargo build --locked --profile ci --manifest-path cli/Cargo.toml --target x86_64-unknown-linux-gnu
sha256sum cli/target/x86_64-unknown-linux-gnu/ci/agent-browser
```

Rust's existing build script creates a placeholder dashboard asset when its
generated directory is absent. A dashboard frontend build, Node/npm and a VM
Rust toolchain are unnecessary for this private frame-only transport.

`build-receipt.json` records the actual Linux artifact, toolchain image, passing
native suites and Chrome compatibility fixture. That fixture uses Rosetta on an
ARM controller, with an explicitly fixture-only executable mapping and sandbox
qualification disabled. It proves shared frames and control denial; it cannot
qualify the installed bot's executable identity or sandbox and cannot promote.

## Qualification before activation

Source hash checks and unit fixtures do not prove the installed runtime. The
actual Linux artifact plus the exact staged Chrome pair must demonstrate:

1. Native CLI navigation/snapshot/type still work, with `--cdp`, `--profile`
   and `--config` delivered as literal page text, never global overrides.
2. One exact native session emits frames showing two known page transitions
   through the private relay, then retains the actual stationary frame.
3. HTTP mutations on session and optional dashboard endpoints fail for absent,
   public, LAN, matching-loopback and forged metadata; no command/session is
   executed. Every browser-originated WebSocket fails, while the private
   no-Origin relay receives frames. A no-Origin client cannot dispatch input
   or stall frames by sending config/ack messages.
4. The real browser sandbox, fresh isolated profile, owned native/Chrome process
   tree and generation cleanup pass the bootstrap's checks. Page access to the
   native and Chrome control endpoints must be tested, not inferred from
   loopback binding or an unverified firewall.

The installation feature remains unqualified until those checks pass. Neither
this source patch nor local web fixture tests are deployed-runtime evidence.
