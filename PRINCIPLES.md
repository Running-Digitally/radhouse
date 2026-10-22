# Radhouse principles

1. **Make one useful action obvious.** Open the private web app and talk to your
   assistant. Keep infrastructure and implementation choices out of the conversation.
2. **Return to where you left off.** Keep the conversation and pending reply across
   browser and app restarts. Show an honest error when continuity cannot be confirmed.
3. **Reuse what already works.** Keep existing sign-in and configured private access. Let Hermes
   own agent context and memory. Add a component only for a demonstrated need.
4. **People retain consequential decisions.** Model text, memory and retrieved
   content do not grant authority. Begin with conversation and tools disabled;
   introduce wider effects through deliberate later slices.
5. **Keep the first slice small.** One assistant and one conversation. Release that
   experience before adding routines, delegation, work management or a fleet.
6. **Make choices clear without instructions.** The best user manual is no user
   manual. Put dependent choices in order, make their effects visible, and keep
   optional details out of the first decision.
7. **Own the boundaries around reused components.** Keep engines replaceable
   through explicit, qualified contracts. Radhouse owns the authority, data
   handling, patches and recovery it adds around them.
8. **Reduce real risk while learning.** Establish safety and quality habits now,
   fix material boundary defects promptly, and reduce remaining debt as the
   product evolves. Keep measurement honest; do not trade away protections for
   a better dashboard count. Public development uses synthetic examples and
   private handling of sensitive evidence.
9. **Develop capabilities openly.** Keep feature design, architecture, security
   research and the engineering roadmap public. Keep monetization and commercial
   strategy private. A feature's possible business value does not make its
   technical design private; split mixed material and preserve source provenance.

These principles are applied through [ADR-0003](docs/decisions/0003-proportionate-security-and-public-development.md)
and [ADR-0004](docs/decisions/0004-replaceable-runtime-adapters.md), with documentation
placement defined by [ADR-0007](docs/decisions/0007-public-engineering-private-commercial-strategy.md).
