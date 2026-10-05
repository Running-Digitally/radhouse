# Radhouse roadmap

## First release: one private web conversation

Acceptance: **I open Radhouse, talk to my assistant, close the browser, and return
later to the same conversation.**

1. Implement the small `radhouse.chat` app: existing password/TOTP sign-in, one
   stable Hermes session, readable history, streamed original attachments without
   application size/count caps, optional bounded readings, pending
   reply recovery and clear errors.
2. Verify the browser journey, auth boundary and retry behavior locally with
   synthetic Hermes and an owned disposable authentication database.
3. Qualify two real turns and restart continuity against the exact existing
   Hermes runtime, beginning with text-only conversation and tools disabled. Then
   prove image understanding, extracted-document answers and the existing STT
   connection with bounded reading examples. Original-file transfer is independent
   of those readings; selective file access needs its own runtime handoff contract.
4. Activate behind the existing private Warp access after the bounded live
   decision, then retire unused infrastructure using verified dependencies and
   explicit data disposition.

The unmerged durable-work PR stack is preserved. It is not on the critical path
for this first release. Buzz integration is removed from the product direction.

## After the first release

Use the assistant and identify one concrete missing capability at a time. Memory
correction, useful tools, routines, delegation and software delivery are possible
later slices. None is required to release the basic conversation, and no standing
fleet or new service is assumed for them.
