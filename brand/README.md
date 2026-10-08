# Radhouse brand assets

The [interface language](INTERFACE.md) defines the original SVG icon family,
interaction states and browser composition. Open the local
[interface specimen](interface-preview.html) to inspect and try it.

The [single-agent identity concept](AGENT-IDENTITY.md) has an interactive
[profile and appearance mockup](agent-settings.html), four raster character
portraits, and the current stateful Radhouse icons. Run
`python3 brand/preview_settings.py` for its local preview.

This directory is the single source of truth for the Radhouse mark. Every
other copy in the repository is a byte-identical duplicate kept here for
directories that need their own local reference (a browser `<link>` or `<img>`
cannot reach across the repo to a sibling top-level directory at runtime).

## Files

- `favicon.svg` (64x64) — browser tab icon. Rounded square, cream background,
  house silhouette, terracotta ring, and a warm center.
- `radhouse-mark.svg` (128x128) — the symbol alone, no text. Used wherever a
  compact square mark is needed (in-app header, social avatar).
- `radhouse-logo.svg` (500x128) — full lockup: the mark plus the wordmark
  "Radhouse". Used in the README banner and the public site header. The tight
  viewBox and single-line wordmark keep the identity legible at header sizes.

The house is mirrored around x=64 in its 128-unit grid. The ring and hearth
share the center (64, 77), with radii of 28 and 10. All three assets use the
same geometry; the favicon scales it by one half within a cream tile.

## Where copies live

| Copy | Purpose | Kept in sync by |
| --- | --- | --- |
| `web/assets/*.svg` | The operator work-home app (`web/index.html`, `web/src/app.ts`) | `tests/test_brand_assets.py` |
| `site/public/*.svg` | The public marketing site (`radhouse.runningdigitally.com`) | `tests/test_brand_assets.py` |

`tests/test_brand_assets.py` fails the build if any copy drifts from this
directory. When you change a mark, edit the file here first, then copy it to
both `web/assets/` and `site/public/` and rerun the tests.

## Palette

| Token | Hex | Use |
| --- | --- | --- |
| Green | `#315d4b` | Primary mark color, ink accents, theme-color |
| Green dark | `#244638` | Hover/pressed states |
| Terracotta | `#d9783f` | Protective ring around the central hearth |
| Amber | `#b86635` | Interactive accent (links, focus rings) |
| Cream paper | `#fffdf7` | Card backgrounds |
| Cream highlight | `#fff8e5` | Mark interior, radial highlight |
| Page | `#f3efe5` | Page background |
| Line | `#d9d3c3` | Borders, dividers |
| Ink | `#20251f` | Body text |
| Muted | `#697065` | Secondary text |

Deliberately the visual inverse of Running Digitally's dark graphite/amber/blue
identity: warm, light, and domestic rather than a dark control-plane aesthetic.

## Typography

- Display: `Georgia, "Times New Roman", serif`
- UI: `Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`

Both are system/OS-provided stacks. No webfont is loaded from any external
source for either the app or the public site. Public-site analytics use the
separately approved Personal PostHog host; typography adds no network requests.
