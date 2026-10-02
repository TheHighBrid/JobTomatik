# Greenhouse native Chrome certification

## Current baseline

The existing Greenhouse adapter is already mature enough for live certification work. It supports Greenhouse host detection, embedded forms, multi-step navigation, uploads, validation extraction, schema inspection, manual challenge handoff, and strong post-submit confirmation detection. Its current declared certification boundary is still pre-submit: `public_inspection_and_synthetic_full_form_dry_run`, with `final_submit_clicked: false`.

Do not change `GREENHOUSE_ADAPTER_VERSION` or the frozen adapter source merely to rename certification state. The repository has digest/regate protections around certified adapter artifacts.

## Native certification gate

Greenhouse is certified only when the current Android/native-Chrome runtime proves one real application end-to-end:

1. resolve a real Greenhouse posting and exact application surface;
2. retain/resume the exact native Chrome target;
3. fill supported fields and required uploads;
4. stop fail-closed for unknown, policy-bound, or human-verification fields;
5. accept Answer Vault/operator input and resume the retained application without restarting it;
6. keep final submission operator-authorized;
7. detect strong Greenhouse post-submit confirmation evidence;
8. persist that evidence before application-state reconciliation;
9. transition the application to Applied/confirmed only after sufficient evidence;
10. disable automatic retry and suppress the already-submitted job.

## Existing confirmation evidence accepted for the live run

The adapter already recognizes visible Greenhouse confirmation elements, explicit receipt/submission text, and changed confirmation URLs. The live run must exercise the real employer surface rather than adding synthetic-only selectors to claim certification.

## Failure policy

No confirmation means no `Applied` claim. A CAPTCHA, unknown required answer, ambiguous success page, lost retained target, or missing durable evidence remains pending/manual review and must not be converted into success.

## Completion evidence

Record the real posting URL, adapter version, retained target identity, any handoff/resume event, final confirmation URL/text/selector evidence, persisted submission evidence, final application state, and proof that retry is suppressed.
