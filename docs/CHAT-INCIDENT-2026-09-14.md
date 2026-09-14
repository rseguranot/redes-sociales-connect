# Chat incident and scoped voice trial — 2026-09-14

## Scope

Chat only. No voice-channel or unrelated tenant changes. The voice single-turn
trial uses private CloudFormation parameters containing explicit phone numbers
and provider-stable user IDs. Names/usernames never establish trial membership.
Do not put parameter values, customer transcripts, tokens or operational URLs in Git.
This is a scoped production trial, not a separate development environment.
With `VOICE_BASELINE_MODULE=production_baseline`, both release packages must retain
the exact prior executable as `production_baseline.py`, including on reruns.

## Findings

An aggregate audit from 08:00 Santo Domingo to the initial audit cutoff examined
74 WhatsApp contacts and 490 stored history entries. Indicators included five
invalid-invoice replies in one contact, an invented invoice-format example,
out-of-domain replies in two contacts, and audio placeholder entries in seven.
These are diagnostic indicators, not a comprehensive customer-satisfaction score.

Interactive-menu JSON in Connect history is the transport representation; it
does not establish that Meta delivered raw JSON. Processor logs showed native
list/button sends, and the real tester's WhatsApp displayed a native menu.

## Changes

- Receipt OCR: preserve a unique candidate barcode number and request confirmation;
  distinguish invoice number from fiscal/identity identifiers. Never infer ownership.
- Retain a claim request while awaiting receipt-number confirmation.
- Explain where to find the invoice instead of inventing an example format.
- Reset stale business and Lex state for explicit topic changes, including a new
  request after an adapter-authored reply without an active business topic.
- Trial identities: original audio is not a textual bot turn; send completed
  transcription once. Preserve original media for agent access. Other identities
  execute the captured production baseline, including mixed-webhook batches.
- Agent application exposes the most recent audio link; runtime configuration unchanged.

## Release and validation

Both stacks were updated through reviewed change sets. Immutable pre-change
Lambda versions were retained. Code packages contain the exact captured baseline.
The release guard rejects unrelated changes and definite replacements. It permits
only unchanged Lex association resources with dynamic dependencies on the unchanged
alias, then verifies their physical identifiers did not change.
Templates are SDK-preserved JSON with ASCII escapes; Windows CLI output roundtrips
previously introduced Unicode differences in unrelated resources.

Unit suites: processor 56 tests plus 9 subtests; adapter 41 tests; frontend 24 tests.
Frontend production build and SAM validation passed. Live Lambda/Lex checks passed
for invoice guidance, synthetic OCR confirmation, and status-to-location routing.
Real WhatsApp confirmed the native menu and the barcode-number explanation.

## Remaining proof boundaries

New real audio must still be verified end-to-end, including one bot input and an
agent opening the original audio. Native OGG attachment support is not configured;
the agent application link is the fallback. Audio replies are not enabled: source
and response-preference metadata are foundations, not completed TTS functionality.
This release does not certify every business API outcome or every customer utterance.
