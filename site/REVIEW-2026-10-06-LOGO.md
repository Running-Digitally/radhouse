# Radhouse logo refinement

6 October 2026. Local preview at http://127.0.0.1:8931/?analytics=preview.

The owner requested a more balanced logo. The house now uses mirrored geometry
around x=64, with one concentric terracotta ring and a cream hearth. The same
geometry supplies the standalone mark, wordmark lockup and favicon. Forest
green, terracotta, cream and the serif wordmark remain the identity.

The full lockup uses a 500×128 viewBox, removing excess right padding and the
tiny tagline. The wordmark is larger within its existing header footprint.
Image dimensions and alt text are updated in both public HTML pages.

Canonical assets in `brand/` were copied byte-for-byte to `site/public/` and
`web/assets/`, as required by the existing brand consistency checks. No app
behavior or styles were changed for this refinement.

Browser checks covered 320, 390, 800 and 1440px widths: no horizontal overflow
or overlap between the logo and navigation. A comparison sheet checks the
favicon at 16, 24 and 32px. All three existing brand tests pass. SVG parsing,
shared geometry, whitespace and preservation of the 23 unrelated files were
also checked. Browser records, before/after assets and screenshots are in
ignored `outputs/review-20261006-logo/`.

This remains a local review candidate. No deployment, commit, push or branch
switch was performed.
