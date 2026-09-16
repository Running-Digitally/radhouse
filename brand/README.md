# Radhouse brand assets

This directory is the single source of truth for the Radhouse mark. Every
other copy in the repository is a byte-identical duplicate kept here for
directories that need their own local reference (a browser `<link>` or `<img>`
cannot reach across the repo to a sibling top-level directory at runtime).

## Files

- `favicon.svg` (64x64) — browser tab icon. Rounded square, cream background,
  house silhouette, three orbiting terracotta agent nodes around a warm center.
- `radhouse-mark.svg` (128x128) — the symbol alone, no text. Used wherever a
  compact square mark is needed (in-app header, social avatar).
- `radhouse-logo.svg` (620x160) — full lockup: the mark plus the wordmark
  "Radhouse" and the strapline "A HOME FOR YOUR AGENTS". Used in the README
  banner and the public site header.

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
| Terracotta | `#d9783f` | Signal accent — the orbiting nodes and connecting lines |
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
source for either the app or the public site — this keeps both surfaces free
of third-party network requests.
