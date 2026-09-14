# Chat dialogue and spoken catalog follow-up

Status: deployed to production after explicit approval on 2026-09-14.

## Scope

- Only the existing WhatsApp chat adapter and processor/media packages change.
- `CHAT_DIALOGUE_SAFETY_ENABLED=true` enables the new control layer on the exclusive chat adapter.
- Explicit representative requests produce the existing Connect handoff attributes, preserving collected context. Personal no-agent exceptions remain owned by the unchanged flow, never inferred from names.
- Explicit closure works without requiring a trial identity or legacy contact binding. Unrequested empty/fulfilled closes keep the conversation open.
- Two failed document-identification answers request human assistance instead of repeating indefinitely. New topic resets the counter; this is not a replacement for checking CRM and delivery API identifier compatibility.
- Known technical/instruction-like model output is blocked by a deterministic outbound-response check and replaced with a handoff. This is not a comprehensive content-security guarantee.
- Delivery and product-failure phrases are routed before catalog lookup. Parts and unverified services get clarification/human-assistance options rather than invented stock or invoice requests.
- Explicit product category, brand and size use literal grounded fields without an extra model invocation. Other product phrasing still uses the existing constrained classifier.
- Spoken ordinal selection uses the exact cached catalog list. Short follow-ups preserve previously requested size when the category is unchanged.
- Catalog retrieval alone can use the existing versioned catalog hook for ordinary customers. Other business operations keep their previous hook; the experimental business path is not broadly promoted.
- Catalog audio summarizes how to select an option instead of reading long model codes. The native list retains prices and exact names. Pedro generative and per-turn voice/text policy remain unchanged.
- Meta reaction/system events no longer create customer turns; legacy plain-text media/unsupported markers are withheld from bot processing. This does not claim a general rewrite of all image/document handling.

## Validation

Targeted suite: 151 tests plus 9 subtests passed before final release planning. Includes adapter, processor, chat business dialogue and flow/isolation regressions. An additional read-only local smoke with the live regional classifier passed six cases; no Connect contact, customer message, CRM case or email was created by that smoke.

`scripts/plan_chat_dialogue_release.py` reads exact live templates, preserves parameters and unrelated resources, archives previous packages/templates under content-addressed private S3 keys, runs cfn-lint and focused cfn-guard rules, and creates UPDATE change sets. It never executes them. Source packages include the retained production baseline module.

The chat plan may show unchanged Lex association resources with conditional replacement caused solely by `ChatAlias.Arn` dynamic dependencies. Review that the template definitions remain identical. There must be no direct replacements, deletions, IAM expansion or unrelated resource changes. After execution, verify physical IDs of those dependencies, deployed code hashes and both stack terminal states.

## Activation and proof boundaries

Both reviewed change sets were executed after verifying the original template hashes, candidate packages against committed source, and allowed resource changes. Both stacks finished in `UPDATE_COMPLETE`. All physical resource IDs remained unchanged; downloaded live adapter, processor and media packages match the source. The chat safety flag is enabled. Original flow definitions, permissions and unrelated resources were preserved.

The 151 tests and 9 subtests passed again at deployment time. Five direct invocations of the deployed adapter passed: explicit closure, representative request attributes, silent audio marker, spoken third-option selection and cached option redisplay. These used synthetic inputs without contact binding: they did not create customer contacts, send WhatsApp messages or exercise CRM writes. They do not prove a real queue transfer or end-to-end voice delivery.

Then use only the authorized tester's real WhatsApp session to check:

1. Voice query for a concrete TV brand/size, without generic re-clarification.
2. Spoken option number and typed option both select the same displayed record.
3. Voice returns voice; text returns text; explicit text lock survives subsequent voice input.
4. Delivery and malfunction utterances do not search for new equipment.
5. Representative request reaches the existing handoff branch; the private tester exception remains private.
6. A new reaction does not open a conversation; explicit closure disconnects.

No fresh browser/voice E2E proof exists for this deployed release yet. The invoice leading-zero/API coverage issue, all possible media timing races, generalized routing accuracy and agent-side visibility remain separate validation items. Do not reuse customer records as test fixtures or publish their content.
