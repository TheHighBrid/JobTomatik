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


async def _visible_listboxes(page) -> List[Any]:
    visible = []
    for candidate in await page.query_selector_all('[role="listbox"]'):
        try:
            if await candidate.is_visible():
                visible.append(candidate)
        except Exception:
            continue
    return visible


async def _close_visible_listboxes(page, combobox) -> bool:
    """Close custom dropdown overlays without forcing pointer events through them."""
    if not await _visible_listboxes(page):
        return True
    for key in ("Escape", "Tab"):
        try:
            await combobox.evaluate("(el) => el.focus()")
            await combobox.press(key)
            await page.wait_for_timeout(120)
        except Exception:
            pass
        if not await _visible_listboxes(page):
            return True
    return False


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
    return listbox, handles, options


async def _is_searchable_combobox(combobox) -> bool:
    try:
        metadata = await combobox.evaluate(
            """(el) => ({
              tag: el.tagName.toLowerCase(),
              editable: el.isContentEditable,
              autocomplete: el.getAttribute('aria-autocomplete') || ''
            })"""
        )
        return bool(
            metadata.get("tag") in {"input", "textarea"}
            or metadata.get("editable")
            or metadata.get("autocomplete") in {"list", "both", "inline"}
        )
    except Exception:
        return False


async def _type_search_answer(page, combobox, answer: str) -> bool:
    if not answer or not await _is_searchable_combobox(combobox):
        return False
    try:
        tag = await combobox.evaluate("(el) => el.tagName.toLowerCase()")
        if tag in {"input", "textarea"}:
            await combobox.fill(answer)
        else:
            await combobox.evaluate("(el) => el.focus()")
            await combobox.press("Control+A")
            await combobox.type(answer, delay=15)
        await page.wait_for_timeout(500)
        return True
    except Exception:
        return False


async def _activate_combobox_option(
    page, combobox, option, option_index: int,
) -> tuple[bool, str, str]:
    """Use normal pointer activation first, then the ARIA keyboard pattern."""
    pointer_error = ""
    keyboard_error = ""
    try:
        await option.scroll_into_view_if_needed(timeout=1500)
        await option.click(timeout=3000)
        return True, pointer_error, keyboard_error
    except Exception as exc:
        pointer_error = str(exc)[:500]

    try:
        await combobox.evaluate("(el) => el.focus()")
        for _ in range(option_index + 1):
            await combobox.press("ArrowDown")
            await page.wait_for_timeout(40)
        await combobox.press("Enter")
        await page.wait_for_timeout(120)
        return True, pointer_error, keyboard_error
    except Exception as exc:
        keyboard_error = str(exc)[:500]
        return False, pointer_error, keyboard_error


async def _combobox_display_state(combobox) -> str:
    """Read React-style selected labels from the control and its nearest field shell."""
    try:
        state = await combobox.evaluate(
            """(el) => {
              const root = el.closest(
                '[data-field],.field-wrapper,.select__container,.select-container,' +
                '[class*="select__control"],[class*="select-container"],' +
                '[class*="field-wrapper"],[class*="application-field"]'
              ) || el.parentElement;
              const hiddenValues = Array.from(
                root?.querySelectorAll('input[type="hidden"]') || []
              ).map((input) => input.value || '').filter(Boolean).join(' ');
              return {
                input: ('value' in el ? el.value : '') || '',
                ownText: el.innerText || el.textContent || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                contextText: root?.innerText || root?.textContent || '',
                hiddenValues
              };
            }"""
        )
        return " ".join(str(value or "") for value in state.values())
    except Exception:
        try:
            return await element_text(combobox)
        except Exception:
            return ""


def _display_contains_answer(displayed: str, answer: str) -> bool:
    normalized_displayed = normalize_text(displayed)
    normalized_answer = normalize_text(answer)
    if not normalized_displayed or not normalized_answer:
        return False
    return f" {normalized_answer} " in f" {normalized_displayed} "


def _display_matches_option(displayed: str, option: OptionRecord) -> bool:
    normalized_displayed = normalize_text(displayed)
    if not normalized_displayed:
        return False
    return bool(
        normalized_displayed in {option.normalized_label, option.normalized_value}
        or f" {option.normalized_label} " in f" {normalized_displayed} "
        or f" {option.normalized_value} " in f" {normalized_displayed} "
    )


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

    answers = parse_policy_answers(policy.get("answer"))
    if len(answers) != 1:
        signature = f"{control_id}:combobox:invalid-answer-count"
        if signature not in processed:
            processed.add(signature)
            append_review(outcome.review_items, make_review(
                descriptor=descriptor, control_type="aria_combobox",
                policy_result=policy, required=required,
                reason_code="unsupported_control",
                summary=f"Custom dropdown requires exactly one approved answer: {descriptor}",
            ))
        return 0

    if not await _close_visible_listboxes(page, combobox):
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type="aria_combobox",
            policy_result=policy, required=required,
            reason_code="unsupported_control",
            summary=f"A previous custom dropdown overlay could not be closed: {descriptor}",
        ))
        return 0

    existing_display = await _combobox_display_state(combobox)
    if _display_contains_answer(existing_display, answers[0]):
        processed.add(
            f"{control_id}:aria-combobox:already-selected:{normalize_text(answers[0])}"
        )
        return 0

    try:
        await combobox.click(timeout=3000)
    except Exception:
        if not await _close_visible_listboxes(page, combobox):
            append_review(outcome.review_items, make_review(
                descriptor=descriptor, control_type="aria_combobox",
                policy_result=policy, required=required,
                reason_code="unsupported_control",
                summary=f"Custom dropdown could not be opened safely: {descriptor}",
            ))
            return 0
        try:
            await combobox.click(timeout=3000)
        except Exception:
            append_review(outcome.review_items, make_review(
                descriptor=descriptor, control_type="aria_combobox",
                policy_result=policy, required=required,
                reason_code="unsupported_control",
                summary=f"Custom dropdown remained blocked by another overlay: {descriptor}",
            ))
            return 0

    await page.wait_for_timeout(120)
    listbox, handles, options = await _combobox_options(page, combobox)
    searched = False
    if not options:
        searched = await _type_search_answer(page, combobox, answers[0])
        if searched:
            listbox, handles, options = await _combobox_options(page, combobox)

    signature = (
        f"{control_id}:aria-combobox:{options_fingerprint(options)}:"
        f"searched={searched}"
    )
    if signature in processed:
        await _close_visible_listboxes(page, combobox)
        return 0
    processed.add(signature)

    match = match_answers_to_options(answers, options, allow_multiple=False)
    if not match.ok:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type="aria_combobox",
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Approved answer does not map unambiguously to this custom dropdown: {descriptor}",
            details={
                "missing_answers": match.missing_answers,
                "ambiguous_answers": match.ambiguous_answers,
                "search_attempted": searched,
                "option_count": len(options),
            },
        ))
        await _close_visible_listboxes(page, combobox)
        return 0

    index = options.index(match.matched[0])
    option = handles[index]
    activated, pointer_error, keyboard_error = await _activate_combobox_option(
        page, combobox, option, index
    )
    if not activated:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type="aria_combobox",
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Matched custom dropdown option could not be selected: {descriptor}",
            details={
                "pointer_error": pointer_error,
                "keyboard_error": keyboard_error,
            },
        ))
        await _close_visible_listboxes(page, combobox)
        return 0

    selected = False
    try:
        selected = normalize_text(await option.get_attribute("aria-selected")) == "true"
    except Exception:
        # React-style widgets frequently replace the option node after selection.
        selected = False

    overlay_closed = await _close_visible_listboxes(page, combobox)
    displayed = await _combobox_display_state(combobox)
    expected = match.matched[0]
    displayed_matches = _display_matches_option(displayed, expected)

    if not selected and not displayed_matches:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type="aria_combobox",
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Custom dropdown selection could not be verified: {descriptor}",
            details={
                "search_attempted": searched,
                "display_state": displayed[:500],
                "pointer_error": pointer_error,
            },
        ))
        return 0

    if not overlay_closed:
        append_review(outcome.review_items, make_review(
            descriptor=descriptor, control_type="aria_combobox",
            policy_result=policy, required=required, options=options,
            reason_code="unsupported_control",
            summary=f"Custom dropdown selection was verified but its overlay stayed open: {descriptor}",
            details={"listbox_detected": bool(listbox)},
        ))
        return 0

    outcome.evidence.append(make_evidence(
        control_id=control_id, control_type="aria_combobox", descriptor=descriptor,
        policy_result=policy, options=options, selected=match.matched,
        pass_number=pass_number,
    ))
    return 1
