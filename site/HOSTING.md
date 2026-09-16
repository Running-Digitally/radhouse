# Radhouse Public Site Hosting

Status: current as of 2026-09-16

Owner: Satish

## Hosting Contract

| Concern | Current value |
| --- | --- |
| Public URL | `https://radhouse.runningdigitally.com/` |
| Hosting | Cloudflare Workers Static Assets |
| Worker project | `radhouse` |
| Worker URL | recorded at first deployment; see `../../Homelab-Documentation/configuration/cloudflare/radhouse-website-hosting.md` |
| Source root | `site/` |
| Build command | none — `site/public/` is committed as-is |
| Deployable output | `site/public/` |
| Access | Public and unauthenticated |

This is a separate Cloudflare Workers Static Assets project from the main
`runningdigitally` project that serves `https://runningdigitally.com/`.
Keeping them separate lets the two sites deploy and roll back independently.
This site is not hosted on OpenAI Sites, Cloudflare Pages, or a homelab
origin. The custom domain is attached directly to the Cloudflare Worker, and
Cloudflare owns the public TLS and DNS edge path.

The infrastructure-side placement and DNS guidance live in
[`Homelab-Documentation/configuration/cloudflare/radhouse-website-hosting.md`](https://github.com/satishsurath/Homelab-Documentation/blob/main/configuration/cloudflare/radhouse-website-hosting.md).

## Build And Validate

There is no build step. `site/public/` is hand-written HTML and CSS, committed
directly, with no dependencies and no compilation. This means the deployed
artifact is always exactly what is in Git — there is no drift risk between
source and release.

Before a release, confirm the brand assets are still in sync with their
source:

```bash
uv run pytest tests/test_brand_assets.py
```

And serve the directory locally to eyeball it:

```bash
cd site/public
python3 -m http.server 8931
# open http://localhost:8931/
```

## Publish

1. If this is the first deployment: in the Cloudflare dashboard, create a new
   Workers & Pages project using Static Assets. Suggested project name:
   `radhouse`.
2. Direct-upload the contents of `site/public/` as a new deployment.
3. Verify the generated `*.workers.dev` URL returns `200` before touching DNS.
4. Attach `radhouse.runningdigitally.com` as the Worker's custom domain.
   Cloudflare creates the required DNS record; do not hand-create one.
5. For subsequent releases, direct-upload the contents of `site/public/` to
   the existing `radhouse` project. Do not create a second project.

No application secrets, runtime variables, database, or persistent storage are
required. The site has no server-side component and makes no third-party
network requests — see `site/public/_headers` for the enforced Content
Security Policy.

## Verify

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' \
  https://<project>.workers.dev/
curl -fsS -o /dev/null -w '%{http_code}\n' \
  https://radhouse.runningdigitally.com/
```

Both endpoints should return HTTP `200`. Confirm the page title, the status
line, the brand mark, and that the Running Digitally and GitHub links resolve
after a content release.

## Rollback

Use the Cloudflare Worker deployment history to promote the previous
known-good deployment. A routine content rollback does not require changing
the custom domain, DNS, or any homelab route.

## DNS Cache Troubleshooting

After first attaching or changing a custom domain, recursive resolvers may
temporarily cache the earlier no-answer response. Wait for the negative TTL or
flush the recursive resolver cache. Do not create a local DNS override.

The active homelab Pi-hole resolvers can be flushed with `pihole reloaddns` in
their `pihole` containers. If both resolvers return the new public answer but a
Mac still fails, flush the Mac DNS cache and retry.
