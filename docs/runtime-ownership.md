# Runtime ownership and analysis scope

Reviewed against merged source `00071e45a46eeed49acc5c5395503345f7a48220`
on 2026-10-15. This inventories repository ownership, not installed software.
Reconcile deployed revisions privately before making exposure claims.

## What Radhouse owns

| Area | Owned source | Obligation in the immediate stage |
| --- | --- | --- |
| Native runtime integration | `runtime/hermes/bridge.py`, `native_inference.py`, `about_you.py`, `plugin/` | Admission, authenticated native routes, capability checks, safe errors, data boundaries. |
| Browser authority and transport | `runtime/hermes/browser_control.py`, `native_control.py`; `runtime/selkies/control.py`, `platform.py`, `web/` | Identity/generation fencing, Private/Observe, handback, replay safety and viewer/input separation. |
| Saved-login integration | `runtime/hermes/vault_bridge.py` and corresponding web routes | Exact-origin use and secret handling; upstream vault internals remain upstream. |
| Human terminal | `runtime/hermes/owner_terminal.py`, `src/radhouse/chat/owner_terminal.py` and UI | Human authority, shell lifetime, input uncertainty and explicit context sharing. These are owned code, even though the shell/PTY libraries are upstream. |
| Runtime installation and recovery | `bootstrap.py`, `base_overlay.py`, `overlay.py`, `rollback_compat.py`, source locks and patch deltas | Exact source compatibility, bounded changes, state preservation and recoverable upgrades. |
| Browser build and containment | Selkies `prepare.py`, `sandbox.py`, `public_proxy.py`, `resources.py`, `qualification.py`, `verify_native_variant.py`, Dockerfiles; Hermes `native-view-only/verify_source.py` | Pinned inputs, network/sandbox policy, resource and qualification evidence. |
| Web application and shared platform | `src/`, `scripts/`, `web/`, `site/`, `deploy/` | Existing source scope stays in place; distinguish the active native chat lane from retained earlier platform code. |

There are 22 tracked Python files under `runtime/` at this revision: 21 owned
production/build/qualification modules and one synthetic fixture server. There
are four owned runtime JavaScript adapters. This count is a scope check, not a
measure of risk or a promise that every format has a SonarQube analyzer.

## Upstream code, fixtures and patches

| Material | Treatment |
| --- | --- |
| `runtime/hermes/fixtures/` | Immutable upstream source snapshots and license used to test compatibility; excluded from the first-party source score. Keep provenance and integrity checks. |
| `runtime/selkies/fixture/` | Radhouse-owned synthetic server/pages; included as test source, not production code or production coverage. |
| `tests/`, `web/test/`, `site/test/` | Continue scanning owned tests as tests. Do not exclude assertion-heavy files to reduce the count. |
| `runtime/**/*.patch` and source transformations | Radhouse owns its changes. Raw patch context and Python string literals do not establish analysis of the resulting upstream code. Review the delta and qualify exact application to pinned source, plus behavioral negative tests. |
| Downloaded Hermes/Selkies/browser packages and base images | Inventory versions, licenses, provenance and relevant advisories separately. No blanket upstream refactoring; upgrade, contain, disable or replace affected capabilities as necessary. |
| Dependency/generated trees and existing vendored site code | Retain established exclusions. Their exclusion from owned source scoring is not a dependency-security exemption. |

The two similarly named fixture directories have different ownership. Do not
replace these rules with a blanket `runtime/**` or `**/fixture*/**` exclusion.
Future first-party files in `runtime/` enter the source scope automatically.

## Measurement limits

`sonar-project.properties` adds `runtime` to sources and the Selkies synthetic
fixture to tests. Test inclusion patterns also exclude those same files from
production analysis, as described in the
[SonarQube scope documentation](https://docs.sonarsource.com/sonarqube-community-build/project-administration/adjusting-analysis/setting-analysis-scope/excluding-files-based-on-patterns).

Python coverage includes `runtime` and discovers unexecuted modules loaded by
path, including directories without `__init__.py`. Only the upstream fixture
tree and synthetic test server are omitted from production coverage. See the
[coverage.py setting](https://coverage.readthedocs.io/en/latest/config.html#report-include-namespace-packages).

The existing LCOV converter admits selected chat, earlier web and script source;
it does not yet import runtime viewer JavaScript coverage. Runtime JavaScript
remains in static analysis and the coverage denominator. Missing measured
execution is a visible gap, not permission to infer coverage from a passing
manual journey. Qualify any future converter extension with source identity,
actual execution and uncovered-file retention tests.

A complete static issue inventory is still not the real-world blast radius.
Combine it with active capability inventory, deployed pins, data access,
dependency review and failure-path evidence. Neither an empty finding list nor
an A rating proves safe handling of untrusted web content or model output.
