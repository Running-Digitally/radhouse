# Address/search and follow-ups

Accepted source scope, 9 October 2026: build from the current
`codex/browser-handover` release, fixing terminal excerpt masking and browser
frame races before adding this slice. Local source and synthetic qualification
are authorized; live deployment retains its separate execution decision.

The browser has one “Search or enter address” field. Explicit HTTP/HTTPS URLs
and bare hostnames/IPs navigate; other text searches through Google or
DuckDuckGo. Non-web schemes and embedded credentials are rejected. Typing is
never replaced by observer refresh. Keyboard/touch history suggestions reuse
owner-local saved destinations. Browser Settings owns the saved search choice
and history clearing, without changing infrastructure or agent network grants.
Search uses a user-selected engine only after Go; suggestions issue no network
or model requests. Google is the initial choice.

Messages sent during a reply are saved as waiting turns with immutable request
IDs, ordered attachments, model choice and explicitly captured context.
The existing web-process observer dispatches the oldest authorized waiting
turn once earlier work ends. There remains at most one active Hermes run.
Queue state, order and cancellation survive restart. Unknown admission blocks
later work; uncertain dispatch is never automatically replayed. A waiting turn
can be cancelled only before dispatch reservation. Frozen browser context is
rechecked by native admission; a stale context fails visibly rather than using
a different page. This adds neither interruption/steering nor an agent shell.

Call paths:

- Browser UI → address resolver → saved owner preference → existing authenticated
  native navigate operation; successful navigation → owner history.
- Settings → owner/origin/CSRF checked preference APIs → private SQLite metadata.
- Send → existing auth/options/upload checks → atomic ordered turn reservation
  → waiting projection → observer → head-only dispatch with the saved key.
- Cancel waiting → authenticated command → atomic never-dispatched cancellation.

Code owners are the existing `chat` store/service/API, browser/static components
and native relay. Tests cover URL/search classification and forbidden schemes,
owner/CSRF isolation, saved preference/history, typing/mobile keyboard behavior,
queued retry/restart/order/cancellation, uncertain admission, frozen options and
attachment scope, plus the two concrete review regressions. No new dependency,
service, credential or scheduler is needed.
