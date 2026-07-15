"""Native select, datalist, radio, and checkbox control handlers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from app.services.answer_policy import resolve_runtime_policy, review_reason_for_question
from app.services.control_primitives import (
    ControlEngineOutcome,
    OptionRecord,
    append_review,
    boolean_value,
    element_descriptor,
    element_text,
    is_actionable,
    is_required,
    make_evidence,
    make_review,
    match_answers_to_options,
    options_fingerprint,
    parse_policy_answers,
)


async def select_options(select) -> List[OptionRecord]:
    records = []
    for index, option in enumerate(await select.query_selector_all("option")):
        value = await option.get_attribute("value") or ""
        records.append(OptionRecord(
            key=f"option:{index}:{value}",
            label=await element_text(option),
            value=value,
            disabled=await option.get_attribute("disabled") is not None,
            selected=bool(await option.evaluate("(el) => Boolean(el.selected)")),
        ))
    return records


async def handle_select(
    page, select, policies: Iterable[Dict[str, Any]], outcome: ControlEngineOutcome,
    processed: set[str], pass_number: int,
) -> int:
    if not await is_actionable(select):
        return 0
    control_id = await select.get_attribute("data-jt-control-id") or ""
    descriptor = await element_descriptor(page, select)
    options = await select_options(select)
    multiple = await select.get_attribute("multiple") is not None
    signature = f"{control_id}:select:{options_fingerprint(options)}"
    if signature in processed:
        return 0
    processed.add(signature)

    policy = resolve_runtime_policy(descriptor, policies)
    required = await is_required(select)
    control_type = "select_multiple" if multiple else "select"
    if not policy.get("can_autofill"):
        if required:
            append_review(outcome.review_items, make_review(
                descriptor=descriptor, control_type=control_type,
                policy_result=policy, required=required, options=options,
            ))
        return 0

    match = match_answers_to_options(
        parse_policy_answers(policy.get("answer")), options, allow_multiple=multiple
    )
    if not match.ok:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type=control_type,
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Approved answer does not map unambiguously to this dropdown: {descriptor}",
            details={
                "missing_answers": match.missing_answers,
                "ambiguous_answers": match.ambiguous_answers,
            },
        ))
        return 0

    values = [item.value for item in match.matched]
    await select.select_option(value=values if multiple else values[0])
    observed = await select.evaluate(
        "(el) => Array.from(el.selectedOptions).map((option) => option.value)"
    )
    if set(observed) != set(values):
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type=control_type,
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Dropdown selection could not be verified: {descriptor}",
            details={"expected_values": values, "observed_values": observed},
        ))
        return 0

    outcome.evidence.append(make_evidence(
        control_id=control_id, control_type=control_type, descriptor=descriptor,
        policy_result=policy, options=options, selected=match.matched,
        pass_number=pass_number,
    ))
    return 1


async def handle_datalist(
    page, element, policies: Iterable[Dict[str, Any]], outcome: ControlEngineOutcome,
    processed: set[str], pass_number: int,
) -> int:
    if not await is_actionable(element):
        return 0
    control_id = await element.get_attribute("data-jt-control-id") or ""
    list_id = await element.get_attribute("list") or ""
    datalist = await page.query_selector(f"#{list_id}") if list_id else None
    if not datalist:
        return 0

    options = []
    for index, option in enumerate(await datalist.query_selector_all("option")):
        value = await option.get_attribute("value") or ""
        label = await option.get_attribute("label") or await element_text(option) or value
        options.append(OptionRecord(f"datalist:{index}:{value}", label, value))

    descriptor = await element_descriptor(page, element)
    signature = f"{control_id}:datalist:{options_fingerprint(options)}"
    if signature in processed:
        return 0
    processed.add(signature)

    policy = resolve_runtime_policy(descriptor, policies)
    required = await is_required(element)
    if not policy.get("can_autofill"):
        if required:
            append_review(outcome.review_items, make_review(
                descriptor=descriptor, control_type="datalist",
                policy_result=policy, required=required, options=options,
            ))
        return 0

    match = match_answers_to_options(
        parse_policy_answers(policy.get("answer")), options, allow_multiple=False
    )
    if not match.ok:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type="datalist",
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Approved answer does not map to this datalist: {descriptor}",
            details={
                "missing_answers": match.missing_answers,
                "ambiguous_answers": match.ambiguous_answers,
            },
        ))
        return 0

    await element.fill(match.matched[0].value)
    if await element.input_value() != match.matched[0].value:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type="datalist",
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Datalist selection could not be verified: {descriptor}",
        ))
        return 0

    outcome.evidence.append(make_evidence(
        control_id=control_id, control_type="datalist", descriptor=descriptor,
        policy_result=policy, options=options, selected=match.matched,
        pass_number=pass_number,
    ))
    return 1


async def collect_native_groups(page, input_type: str) -> List[Tuple[str, Any, List[Any]]]:
    groups: Dict[str, Tuple[Any, List[Any]]] = {}
    for handle in await page.query_selector_all(f'input[type="{input_type}"]'):
        if not await is_actionable(handle):
            continue
        metadata = await handle.evaluate(
            """(el) => {
              const group = el.closest('fieldset,[role="radiogroup"],[role="group"]');
              return {
                groupId: group?.dataset.jtControlId || group?.id || '',
                name: el.getAttribute('name') || '',
                ownId: el.dataset.jtControlId || el.id || ''
              };
            }"""
        )
        key = (
            f"group:{metadata['groupId']}" if metadata["groupId"]
            else f"name:{metadata['name']}" if metadata["name"]
            else f"single:{metadata['ownId']}"
        )
        js_handle = await handle.evaluate_handle(
            "(el) => el.closest('fieldset,[role=\"radiogroup\"],[role=\"group\"]')"
        )
        group = js_handle.as_element()
        if key not in groups:
            groups[key] = (group, [])
        groups[key][1].append(handle)
    return [(key, group, choices) for key, (group, choices) in groups.items()]


async def choice_option(page, choice, index: int) -> OptionRecord:
    label = await element_descriptor(page, choice)
    value = (
        await choice.get_attribute("value")
        or await choice.get_attribute("data-value")
        or await choice.get_attribute("aria-label")
        or label
    )
    try:
        selected = await choice.is_checked()
    except Exception:
        selected = (await choice.get_attribute("aria-checked")) == "true"
    return OptionRecord(
        key=await choice.get_attribute("data-jt-control-id") or f"choice:{index}",
        label=label,
        value=value,
        disabled=not await is_actionable(choice),
        selected=selected,
    )


async def set_choice(choice, desired: bool) -> bool:
    role = (await choice.get_attribute("role") or "").lower()
    if role in {"radio", "checkbox"}:
        current = (await choice.get_attribute("aria-checked")) == "true"
        if current != desired:
            await choice.click()
        return ((await choice.get_attribute("aria-checked")) == "true") == desired

    current = await choice.is_checked()
    if current != desired:
        await (choice.check() if desired else choice.uncheck())
    return (await choice.is_checked()) == desired


async def handle_choice_group(
    page, *, group_key: str, group, choices: List[Any], input_type: str,
    policies: Iterable[Dict[str, Any]], outcome: ControlEngineOutcome,
    processed: set[str], pass_number: int,
) -> int:
    if not choices:
        return 0
    options = [await choice_option(page, choice, i) for i, choice in enumerate(choices)]
    descriptor = await element_descriptor(page, group or choices[0])
    if group is None and len(choices) == 1:
        descriptor = options[0].label or descriptor

    signature = f"{group_key}:{input_type}:{options_fingerprint(options)}"
    if signature in processed:
        return 0
    processed.add(signature)

    policy = resolve_runtime_policy(descriptor, policies)
    required = any([await is_required(choice, group) for choice in choices])
    if not policy.get("can_autofill"):
        if required:
            append_review(outcome.review_items, make_review(
                descriptor=descriptor, control_type=input_type,
                policy_result=policy, required=required, options=options,
            ))
        return 0

    answers = parse_policy_answers(policy.get("answer"))
    if input_type == "checkbox_single":
        decision = boolean_value(answers[0] if answers else "")
        if decision is None:
            match = match_answers_to_options(answers, options, allow_multiple=False)
            if not match.ok:
                append_review(outcome.review_items, make_review(
                    descriptor=descriptor, control_type=input_type,
                    policy_result=policy, required=required, options=options,
                    reason_code="unsupported_control",
                    summary=f"Standalone checkbox answer is not a clear yes/no decision: {descriptor}",
                ))
                return 0
            decision = True
        if required and decision is False:
            append_review(outcome.review_items, make_review(
                descriptor=descriptor, control_type=input_type,
                policy_result=policy, required=required, options=options,
                reason_code=review_reason_for_question(policy),
                summary=f"The approved answer does not satisfy this required checkbox: {descriptor}",
            ))
            return 0
        if not await set_choice(choices[0], decision):
            append_review(outcome.review_items, make_review(
                descriptor=descriptor, control_type=input_type,
                policy_result=policy, required=required, options=options,
                reason_code="unsupported_control",
                summary=f"Checkbox state could not be verified: {descriptor}",
            ))
            return 0
        outcome.evidence.append(make_evidence(
            control_id=options[0].key, control_type=input_type, descriptor=descriptor,
            policy_result=policy, options=options,
            selected=[options[0]] if decision else [], pass_number=pass_number,
        ))
        return 1

    multiple = input_type == "checkbox_group"
    match = match_answers_to_options(answers, options, allow_multiple=multiple)
    if not match.ok:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type=input_type,
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Approved answer does not map unambiguously to this choice group: {descriptor}",
            details={
                "missing_answers": match.missing_answers,
                "ambiguous_answers": match.ambiguous_answers,
            },
        ))
        return 0

    selected_keys = {item.key for item in match.matched}
    for option, choice in zip(options, choices):
        desired = option.key in selected_keys
        if input_type == "radio" and not desired:
            continue
        if not await set_choice(choice, desired):
            append_review(outcome.review_items, make_review(
                descriptor=descriptor, control_type=input_type,
                policy_result=policy, required=required, options=options,
                reason_code="unsupported_control",
                summary=f"Choice state could not be verified: {descriptor}",
                details={"failed_option": option.label or option.value},
            ))
            return 0

    outcome.evidence.append(make_evidence(
        control_id=group_key, control_type=input_type, descriptor=descriptor,
        policy_result=policy, options=options, selected=match.matched,
        pass_number=pass_number,
    ))
    return 1
