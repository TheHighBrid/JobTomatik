"""ARIA combobox, radio, and checkbox control handlers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from app.services.answer_policy import resolve_runtime_policy
from app.services.control_native import handle_choice_group
from app.services.control_primitives import (
    ControlEngineOutcome,
    OptionRecord,
    append_review,
    element_descriptor,
    element_text,
    is_actionable,
    is_required,
    make_evidence,
    make_review,
    match_answers_to_options,
    normalize_text,
    options_fingerprint,
    parse_policy_answers,
)


async def collect_aria_groups(page, role: str) -> List[Tuple[str, Any, List[Any]]]:
    groups: Dict[str, Tuple[Any, List[Any]]] = {}
    for handle in await page.query_selector_all(f'[role="{role}"]'):
        if not await is_actionable(handle):
            continue
        metadata = await handle.evaluate(
            """(el) => {
              const group = el.closest('[role="radiogroup"],[role="group"],fieldset');
              return {
                groupId: group?.dataset.jtControlId || group?.id || '',
                ownId: el.dataset.jtControlId || el.id || ''
              };
            }"""
        )
        key = (
            f"aria-group:{metadata['groupId']}"
            if metadata["groupId"]
            else f"aria-single:{metadata['ownId']}"
        )
        js_handle = await handle.evaluate_handle(
            "(el) => el.closest('[role=\"radiogroup\"],[role=\"group\"],fieldset')"
        )
        group = js_handle.as_element()
        if key not in groups:
            groups[key] = (group, [])
        groups[key][1].append(handle)
    return [(key, group, choices) for key, (group, choices) in groups.items()]


async def _combobox_options(page, combobox):
    controls_id = (
        await combobox.get_attribute("aria-controls")
        or await combobox.get_attribute("aria-owns")
    )
    listbox = await page.query_selector(f"#{controls_id}") if controls_id else None
    if listbox is None:
        for candidate in await page.query_selector_all('[role="listbox"]'):
            if await candidate.is_visible():
                listbox = candidate
                break

    handles = await listbox.query_selector_all('[role="option"]') if listbox else []
    options = []
    for index, option in enumerate(handles):
        label = await element_text(option) or await option.get_attribute("aria-label") or ""
        value = (
            await option.get_attribute("data-value")
            or await option.get_attribute("value")
            or label
        )
        options.append(OptionRecord(
            key=await option.get_attribute("data-jt-control-id") or f"aria-option:{index}:{value}",
            label=label,
            value=value,
            disabled=normalize_text(await option.get_attribute("aria-disabled")) == "true",
            selected=normalize_text(await option.get_attribute("aria-selected")) == "true",
        ))
    return handles, options


async def handle_combobox(
    page, combobox, policies: Iterable[Dict[str, Any]], outcome: ControlEngineOutcome,
    processed: set[str], pass_number: int,
) -> int:
    if not await is_actionable(combobox):
        return 0
    control_id = await combobox.get_attribute("data-jt-control-id") or ""
    descriptor = await element_descriptor(page, combobox)
    required = await is_required(combobox)
    policy = resolve_runtime_policy(descriptor, policies)

    if not policy.get("can_autofill"):
        signature = f"{control_id}:combobox:no-policy"
        if signature not in processed:
            processed.add(signature)
            if required:
                append_review(outcome.review_items, make_review(
                    descriptor=descriptor, control_type="aria_combobox",
                    policy_result=policy, required=required,
                ))
        return 0

    await combobox.click()
    await page.wait_for_timeout(50)
    handles, options = await _combobox_options(page, combobox)
    signature = f"{control_id}:aria-combobox:{options_fingerprint(options)}"
    if signature in processed:
        return 0
    processed.add(signature)

    match = match_answers_to_options(
        parse_policy_answers(policy.get("answer")), options, allow_multiple=False
    )
    if not match.ok:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type="aria_combobox",
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Approved answer does not map unambiguously to this custom dropdown: {descriptor}",
            details={
                "missing_answers": match.missing_answers,
                "ambiguous_answers": match.ambiguous_answers,
            },
        ))
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return 0

    index = options.index(match.matched[0])
    option = handles[index]
    await option.click()
    await page.wait_for_timeout(50)
    selected = normalize_text(await option.get_attribute("aria-selected")) == "true"
    try:
        displayed = await combobox.input_value()
    except Exception:
        displayed = await element_text(combobox)

    expected = match.matched[0]
    normalized_displayed = normalize_text(displayed)
    displayed_matches = (
        normalized_displayed in {expected.normalized_label, expected.normalized_value}
        or expected.normalized_label in normalized_displayed
        or expected.normalized_value in normalized_displayed
    )
    if not selected and not displayed_matches:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type="aria_combobox",
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Custom dropdown selection could not be verified: {descriptor}",
        ))
        return 0

    outcome.evidence.append(make_evidence(
        control_id=control_id, control_type="aria_combobox", descriptor=descriptor,
        policy_result=policy, options=options, selected=match.matched,
        pass_number=pass_number,
    ))
    return 1
