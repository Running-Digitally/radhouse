# Radhouse work home

This directory contains the first operator interface. It deliberately uses the
browser platform and TypeScript without a UI framework so the permission and
task flow remains small enough to inspect during the usability pilot.

Build and test it with a current Node.js release:

```sh
npm ci
npm test
```

The build writes ignored JavaScript files to `dist/`. A Radhouse composition
root can pass this `web/` directory as `web_root` to `create_app()`, which mounts
it at `/app/`. Open the signed-in work-home URL with the current conversation
binding values:

```text
/app/?conversation_id=<bound-conversation>&binding_revision=<current-revision>
```

The query identifies the current interaction context; it does not authenticate
the person. Every data request uses same-origin credentials and crosses the
server's injected authentication adapter, current binding, role, project, bot,
assurance, revision, digest, and audience checks. Do not expose a deployment
until that composition root supplies a qualified authentication adapter and TLS.
