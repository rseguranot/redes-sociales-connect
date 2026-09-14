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
After the final fix, real WhatsApp also confirmed that status requests ask for
the invoice without closing, and a following location query returns the branch
address rather than insisting on an invoice. The tester-only no-transfer closure
was observed. No real case was created by these smoke tests.

## Remaining proof boundaries

New real audio must still be verified end-to-end, including one bot input and an
agent opening the original audio. Native OGG attachment support is not configured;
the agent application link is the fallback. Audio replies are not enabled: source
and response-preference metadata are foundations, not completed TTS functionality.
This release does not certify every business API outcome or every customer utterance.

## Identity-scoped semantic and typing trial

The follow-up release uses `scripts/deploy_semantic_trial.py` with the exact live
templates. It reads private selectors from existing runtime configuration and
passes them as NoEcho parameters; no customer identity belongs in source control.
Keep these live-template additions when regenerating infrastructure: the generic
production builder is not a replacement for this trial deployment script.

- Processor/media candidate sends Meta read + text typing status only for the
  existing trial identities. Receipt failure does not retry the customer turn.
- Adapter verifies identity through Connect contact attributes, not a username or
  a caller-supplied trial flag. Preserve the contact binding across hook replies.
- A constrained Bedrock classifier interprets product queries and topic changes.
  Product fields must be quoted from the current input or grounded prior fields.
- Concrete categories can search without a brand. Vague product requests ask for
  the product. A brand by itself does not imply a category.
- A separate `SemanticBusinessTrial` Lambda, pinned by version, exposes catalog
  records to the adapter. The original business Lambda/version stays unchanged.
- Native DSL lists show up to four catalog records; detail buttons reuse those
  records. Prices and branch stock are explicitly unconfirmed. Long lists are
  bounded below the WhatsApp body limit.
- Trial-only downstream error/timeout handling reports an unconfirmed outcome;
  it does not automatically repeat a case-creation request.

Change-set protection rejected an attempted SAM business alias/version rotation;
that change set was not executed. The separate trial function avoids that change.
Pre-change immutable adapter versions are retained. Definite/unrelated replacements
remain prohibited; unchanged dynamic Lex dependencies are checked after updates.

Validation: 107 unit tests plus 9 subtests passed; cfn-lint returned no findings
for the deployed chat template. Real WhatsApp confirmed a fresh-session vague
product clarification, native category list, a four-record LG catalog list,
selection of its first product, and a subsequent Santiago location question
returning a branch rather than a TV-purchase question. A category alone also
returned catalog options after the classifier refinement. Read status was visible;
An explicit singular-TV query with `43 in.` returned a matching 43-inch LG record
and a native detail button after the final catalog-query normalization.
Meta accepted eight read/typing requests in the sampled test window. The transient
typing animation itself was not visually captured.

The initial real test exposed missing contact binding in an older session; it
fell back to the baseline and reproduced the unwanted product. A new test session
and binding preservation resolved the tested path. Existing sessions already
missing that binding are not silently identified by display name.

The earlier unanswered message remains unproven at root cause: the sampled
16:54–17:02 UTC adapter/business logs showed invocations but no matching timeout,
error or throttle signatures. Do not claim the new fallback proves that incident
fixed. Fresh voice-message E2E, transient typing UI, range constraints (such as
greater-than screen sizes), and exhaustive business flows remain additional QA.
At that stage, no TTS response, voice-channel migration, or Agentic CX Designer
migration had been enabled. The later scoped TTS release is documented below.

## Explicit close regression (follow-up)

An explicit `finalizar` was being interpreted using the retained product context.
The adapter now handles unambiguous session-close commands before receipt or
semantic processing, only after validating the existing trial identity. It emits
Lex `Close` with fulfilled intent `Cerrar`, clears product state and disables
handoff. Negations, purchase completion, and case closure are not session-close
commands. Nontrial identities retain their previous handling.

The code-only release uses `scripts/deploy_chat_adapter_patch.py`: retained rollback
version, unchanged environment/IAM/business functions, cfn-lint, and reviewed change
set with unchanged dependent physical identifiers. Stack `UPDATE_COMPLETE`;
110 unit tests plus 9 subtests passed. Real WhatsApp `finalizar` produced one
farewell without a menu; Connect `DescribeContact` confirmed a disconnect timestamp
and no connected agent. The tester session was left closed for the user's next test.

## Pedro voice replies and branch presentation (follow-up)

The existing private identity trial now supports bot voice replies with Amazon
Polly `Pedro`, `es-US`, neural, `ogg_opus` at 48 kHz. The processor uploads the
audio to Meta and sends it as a voice note. Only SYSTEM messages and the existing
trusted trial identities qualify; agents and nontrial customers retain the baseline.
No voice-telephony flow, shared business hook, or Delta resources were changed.

The adapter refreshes trusted input-source attributes before interpreting a turn.
Voice input selects audio, ordinary text selects text, and explicit requests for
text/audio persist as an override for the session. Interactive replies retain their
native buttons/list alongside the audio; ordinary spoken replies replace the text
delivery. Readable bot text remains in history for agents. Formatting marks and
technical links are removed from speech, not from the recorded answer.

Generation failures and overlong speech fall back to text; delivery errors remain
retryable. A seven-day delivery record reuses uploaded media across retries and
skips already-confirmed sends. This is not an exactly-once guarantee across an
ambiguous Meta acceptance or a post-send state-write failure.

Branch address/hours presentation fixes the observed missing accents, adds headings,
line breaks, and separate weekday/Sunday bullets. The narrow formatter preserves
source facts and catalog names; it is not an unrestricted model-based copy editor.

Deployment: `scripts/deploy_bot_voice_trial.py` plus the code-only adapter helper,
retained immutable backups, reviewed CloudFormation change sets, no resource
replacements, and both stacks `UPDATE_COMPLETE`. The main template retains five
pre-existing cfn-lint warnings and no errors; the adapter template has no findings.
The MediaFunction package intentionally remains unchanged. Disable the feature
with `WHATSAPP_BOT_VOICE_ENABLED=false` through the same managed deployment workflow.

Validation: 116 tests plus 9 subtests; a real forwarded tester voice note received
a playable bot voice note in WhatsApp. A new session displayed the corrected branch
format. Explicit audio returned voice plus native controls, and explicit text was
honored both for a subsequent text query and a forwarded voice note. The older
session had already lost its trusted contact binding and did not honor the new
adapter behavior; it was closed before the fresh-session checks. Do not identify
such legacy sessions by display name or claim all older sessions were repaired.
