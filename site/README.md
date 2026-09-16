# Radhouse public site

The source for `https://radhouse.runningdigitally.com/` — a simple, honest,
one-page public site for the project. It is separate from `web/`, which is
the operator work-home application served by a running Radhouse deployment.

## What's here

- `public/` — the deployable directory. Everything Cloudflare serves lives
  here: `index.html`, `styles.css`, `404.html`, `_headers`, and the brand SVGs.
- `HOSTING.md` — the release procedure: how to publish, verify, and roll back.

There is no build step. `public/` is committed exactly as it is deployed.

## Local preview

```bash
cd public
python3 -m http.server 8931
# open http://localhost:8931/
```

## Brand assets

The SVGs in `public/` are copies of the canonical files in
[`../brand/`](../brand/README.md). If you change the mark, edit `../brand/`
first, then update this copy, and run:

```bash
uv run pytest tests/test_brand_assets.py
```

## Publishing

See [HOSTING.md](HOSTING.md) for the full contract, verification commands,
and rollback procedure.
