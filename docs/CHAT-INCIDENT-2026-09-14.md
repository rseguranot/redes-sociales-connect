# Chat incident and identity-scoped voice trial

The morning audit found repeated invoice rejection after an explicit claim request,
an invented invoice format example, and domain mismatch responses. Internal
`whatsapp_outbound` JSON in Connect history is a transport representation;
processor logs showed conversion to native WhatsApp lists and buttons.

The chat adapter clears stale Lex intent/slots and business context when a clear
new request changes service, confirms a unique 14-digit OCR invoice candidate,
and explains the barcode location rather than generating fictitious identifiers.
Receipt OCR is unverified data. Confirmation does not establish ownership or
authorize access to another customer's records. Existing backend checks remain.

Voice testing uses exact Meta phone or stable user ID allowlists, supplied privately
through CloudFormation parameters. Names and usernames never qualify. When
`VOICE_BASELINE_MODULE=production_baseline`, release packaging must include the
exact prior deployed executable as `production_baseline.py`. Non-test messages,
including mixed webhook batches, retain that executable. Test media and its
Transcribe completion follow the candidate pipeline. This is a scoped production
trial, not a separate development environment.

Create immutable Lambda snapshots before updating code. Use an SDK-preserved
CloudFormation template serialized with JSON ASCII escapes; a Windows CLI output
roundtrip previously introduced Unicode differences in unrelated resources.
Reject change sets containing unrelated resources or any replacements.

Validation requires regression tests plus a new authorized WhatsApp note and
agent-visible attachment verification. Reply preference metadata prepares future
voice responses; synthesis is not enabled by this release.
