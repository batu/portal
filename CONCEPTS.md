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

## Agent steering

### Agent Session Identity
The authoritative pair of provider and stable session ID supplied by Agency Fleet for one live, top-level agent. Labels, pane positions, TTYs, processes, and paths may help display or resolve it, but are not the identity.

### Targeted Agent Message
An operator-authored message bound immutably to one Agent Session Identity. It is excluded from the generic pull queue and retained with its delivery state and append-only Delivery Attempts.

### Terminal Submission Receipt
Durable evidence that literal message text plus Enter were sent to the revalidated target terminal. It is not evidence that the agent read, understood, acknowledged, or acted on the message. While the owning Stream is open, a failed attempt is retryable and an unknown attempt requires terminal inspection and explicit confirmation; archived Streams remain read-only.

### Delivery Attempt
One append-only attempt to submit a Targeted Agent Message, recording when it occurred, its outcome, and a sanitized detail. Only `submitted_to_terminal` consumes the message.

### View Capability
A request-scoped credential granted to active producer HTML for only its owning Request's declared media and Verdict endpoint. The view remains an opaque origin; the capability cannot authenticate unrelated Portal surfaces such as Agents.

## Game releases

### Release Approval Manifest
The redacted, immutable description of one proposed game-release run: resolved game identity, provider mutations, credential actions, build target, physical device, and required verification. Approval applies only to that exact content and becomes invalid when any governed field changes.

### Provider Receipt
Evidence for the strongest boundary a provider exposes, recorded separately as local configuration, SDK handoff, provider acceptance, or dashboard-visible ingestion. An unsupported stronger boundary never inherits a pass from a weaker one.

### Verified Release Candidate
A native artifact bound to its source revision, build configuration, digest, installed application identity, physical device, gameplay evidence, and required Provider Receipts. Diagnostic harness success alone does not confer this status.
