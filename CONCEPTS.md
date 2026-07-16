# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Requests and decisions

### Request
A single decision put to a human: a titled set of Variants plus an ask (pick-one, pick-many, rank, approve, comment, before-after, or view). Requests are open until decided, closed, or superseded; terminal states are immutable except for Feedback annotation.

### Variant
One candidate within a Request — a media file with an index, optional caption, and metadata. Display order is the posting order.

### Verdict
The human's recorded decision on a Request: selected variant indices, optional comment, or opaque payload for view-kind requests. A Request with a Verdict is decided; the portal never fabricates one.

### Chain
The sequence of Requests linked by supersession, representing one iteration loop. Any member resolves the whole Chain; the newest live member is the Chain's head. The chain view shows one tab per version and opens at the head.

### Supersession
Retiring a Request in favor of a live successor. Superseding is terminal for the old Request and links it forward; it is how a Chain grows. The successor must itself be live.

### Feedback
The human critique that caused a Request's retirement, recorded on the retired version so the Chain reads as a story. Feedback is an annotation, not a lifecycle mutation — it may be added or edited even on terminal Requests.

### Author
Who or what produced a Request's content (typically an agent model id). Recorded at posting time and displayed with the Request.

## Streams

### Stream
A named, slugged container that owns Requests and posts for one working session or project area. Closing a Stream makes its Requests read-only (archived).
