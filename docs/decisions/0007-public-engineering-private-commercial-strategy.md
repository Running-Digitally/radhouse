# ADR-0007: Public engineering and private commercial strategy

Date: 2026-10-21. Status: accepted owner direction for documentation placement.

## Decision

Develop Radhouse's capabilities and engineering maturity in this public
repository. Keep commercial strategy in the separate private venture repository.
A feature may be useful to a future business without its design becoming private.
The discussion of how that feature will be monetized belongs in the private
commercial record.

| Public engineering | Private commercial strategy |
| --- | --- |
| Feature proposals, user experience and capability roadmap | Pricing, packaging and paid-versus-free decisions |
| Technical research, architecture and alternative implementations | Commercial positioning and defensibility |
| Security landscape, threat models, posture and recovery improvements | Revenue hypotheses, market selection and willingness to pay |
| Resource measurements, performance and operating requirements | Margins, commercial forecasts and hosted-service economics |
| Maintenance, compatibility, tests and sanitized qualification evidence | Acquisition, go-to-market and investment decisions |

Technical design does not need to wait for a monetization decision. Commercial
motivation does not require disclosure of commercial reasoning in a public
engineering task. Explain public work through its user benefit, technical
requirements and acceptance evidence.

## Two connected roadmaps

[ROADMAP.md](../../ROADMAP.md) is the entry point for the public capability and
maturity roadmap. Detailed implementation plans live in `docs/plans/` and
proposals in `docs/design/`. Public tasks must be understandable and executable
without access to private commercial research.

The private roadmap owns commercial assumptions, experiments and investment
decisions. It references public capability identifiers and evidence rather than
maintaining another engineering backlog. Neither a commercial hypothesis nor a
technical proposal is a delivery commitment, accepted implementation or live
deployment authority.

## Mixed material and source handling

Split mixed reports into a self-contained public technical assessment and a
private commercial analysis. Keep dated source exports and private conversations
in their existing restricted archive. An archive copy is historical evidence;
it is not a competing current technical specification. Update its index to point
to the public technical authority. Do not rewrite original exports or infer
missing citations while extracting a public assessment.

Publish original explanation and links to public primary sources. Do not copy
account-only conversation links, raw transcripts, personal screenshots or
commercial attachments into a public packet merely because they informed it.
Rights and source attribution still apply to third-party material.

Security improvements and posture belong in public engineering. Credentials,
customer data, private deployment identity, raw sensitive incident evidence and
unfixed exploit details retain the handling required by
[ADR-0003](0003-proportionate-security-and-public-development.md) and
[SECURITY.md](../../SECURITY.md). The commercial repository is not a credential
store or a substitute for the private operational record.

When a proposed public passage would reveal an ambiguous commercial decision or
sensitive evidence, present the exact boundary and recommended split to the
owner. Continue independently on clearly public material. Do not make every
feature proposal depend on another general publication approval.

## Initial application

The [SPACE and durable-workspace research](../research/space-and-durable-agent-workspaces.md),
[architecture proposal](../design/durable-assistant-workspaces.md) and
[development roadmap](../plans/2026-10-21-durable-workspace-roadmap.md) are public
engineering documents. Browser persistence, Library transfers, optional browser
import, on-demand workers and isolated execution are public capability topics.
Their future packaging, pricing or hosted-service business case remains private.
