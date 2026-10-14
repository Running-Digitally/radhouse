# ADR-0002: Use Selkies for the Radhouse browser viewer

Status: accepted owner decision; unified desktop/mobile pilot authorized.

Date: 2026-10-14

## Context

The legacy Radhouse browser viewer couples frame polling and individual browser
operations to a custom UI. The Selkies pilot has demonstrated continuous video,
direct desktop and phone interaction, sandboxed public-web access, fenced
human/agent handover and recovery. The owner accepted the experience and asked
to choose Selkies as the replacement instead of prolonging package selection.
Phone touch works through the controlling viewer; the missing keyboard is a UI
integration gap. Selkies already includes mobile text composition, keyboard
assistance, touch detection and hardware-keyboard detection in the pinned source.

## Decision

Use the pinned Selkies package for browser video, pointer/touch and keyboard
input on all devices. Replace the legacy frame/event viewer with this path as
Radhouse's browser architecture. Keep one responsive viewer, one remote Chromium
and the same explicit Take control / Return to agent flow. Device type controls
presentation, never authorization. Viewing-only is an explicit capability.

Reuse Selkies' keyboard-assist input and hardware-keyboard watcher. Show a
Keyboard control on touch clients when they hold the input lease; hide it by
default on ordinary desktops and when a physical keyboard is detected. Keep an
explicit override in the Keys menu because detection is heuristic. A trusted tap
focuses the existing assist field synchronously; ordinary remote taps do not
open the operating-system keyboard. Fixed Tab, Enter, Escape and address-bar
shortcuts use Selkies' own chord helper through the existing input channel.
Composition and text never take a second Radhouse text-injection path.

Keep Radhouse's durable controller, generation-bound leases, input lock, agent
fence, held-input/clipboard drain, sensitive-field checks and fresh handback
observation. Hermes continues using its seven restricted native page tools on
the very same owned Chromium. Selkies replaces presentation and human input;
it does not replace Chromium or the automation boundary. Preserve the qualified
non-root browser sandbox, public-only egress, end-to-end TLS and memory-pressure
reclamation. Downloads remain unrestricted.

## Delivery slices and current scope

1. Replace the split desktop/phone test entry points with one authenticated
   browser launcher and responsive Selkies viewer. Deploy keyboard assistance
   and fixed soft keys to the existing disposable pilot. Retain an explicit
   viewing-only launcher and do not upgrade previously issued viewer tokens.
2. Replace the chat-bound legacy viewer using the same Selkies adapter. Bind
   stream ownership to the authenticated principal, conversation, run and
   browser generation already owned by the runtime. Activate the replacement
   only when the chat and Selkies tools demonstrably address that same browser.
   Do not redirect a live chat's browser panel to an independent test browser.

This task deploys slice 1 for owner testing and establishes the replacement
architecture. Slice 2 is implementation of this accepted decision, not another
choice of streaming package. Until it is installed, the pilot explicitly
identifies its disposable profile and test-driver observations.

## Contracts and implementation

The [browser guide](../selkies-browser.md) owns the component map and operation.
`runtime/selkies/control.py` remains the input authority boundary. The viewer
uses the lease-bound stream; its keyboard adapter reports booleans only and
never forwards text or clipboard payloads into the outer UI. The mobile assist
buffer is cleared on dismissal, handback, authority loss and page exit. A
same-origin synchronous call preserves the user's focus gesture; untrusted
message senders cannot invoke text input.

The deployment launcher requires the existing app login. `/browser` is the
canonical controlling launch for every device. Existing desktop/phone launch
aliases enter that same pilot after authentication. `/view` remains explicitly
viewing-only. Previously minted viewing-only capabilities remain viewing-only.
No new account, service, root broker, timer, privilege, database or profile mount
is needed for the mobile extension.

## Consequences and alternatives

The team maintains a small Radhouse viewer/control integration and pinned
Selkies dependencies instead of two input implementations. Upstream's mobile
composition handling is reused; keyboard opening still needs actual-device
acceptance because desktop emulation does not prove an OS keyboard appeared.
Hardware-keyboard detection needs an override. The virtual keyboard reduces the
visible viewport; the client fits to that viewport without resizing the remote
browser or changing pointer coordinates.

Continuing the custom frame viewer would duplicate streaming, touch and text
handling. Adopting the entire upstream administrative dashboard would expose UI
outside this browser's purpose and authority. A custom mobile text endpoint
would duplicate composition and create another injection boundary. These paths
are not selected. The deployment patches forward; no rollback is requested.

## Focused acceptance and review

Run the existing desktop stream journey, one mobile takeover/keyboard/soft-key/
handback journey and a viewing-only negative control. Check the installed image,
sandbox readiness and existing app health. Reuse prior native/sandbox/egress and
memory qualification when their frozen bytes and settings are unchanged; do not
repeat the package investigation or unrelated full suites for a viewer-only
change. Record real iPhone/Android keyboard acceptance separately from emulation.
Revisit after a demonstrated input, accessibility, ownership or performance gap.

References: [Selkies input](https://docs.selkies.io/latest/reference/web-core/lib/input),
[upstream keyboard controls](https://github.com/selkies-project/selkies/blob/main/addons/selkies-dashboard/src/components/Sidebar.jsx),
[WebKit focus behavior](https://bugs.webkit.org/show_bug.cgi?id=195884).
