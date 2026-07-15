"""
Standards-oriented application control engine.

It supports native and standards-based ARIA dropdowns, radios, and checkboxes.
Controls are changed only through confirmed answer policies, option matching must
be unambiguous, and every action is verified after interaction.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.services.control_aria import collect_aria_groups, handle_combobox
from app.services.control_native import (
    collect_native_groups,
    handle_choice_group,
    handle_datalist,
    handle_select,
)
from app.services.control_primitives import (
    CONTROL_ENGINE_VERSION,
    ControlEngineOutcome,
    OptionRecord,
    element_descriptor,
    match_answers_to_options,
    normalize_text,
    parse_policy_answers,
)

MAX_DYNAMIC_PASSES = 5
_SETTLE_MS = 175


async def _prepare_ids(page) -> None:
    await page.evaluate(
        """() => {
          let counter = Number(document.documentElement.dataset.jtCounter || 0);
          const selector = [
            'select','input[list]','[role="combobox"]',
            'input[type="radio"]','[role="radio"]',
            'input[type="checkbox"]','[role="checkbox"]',
            'fieldset','[role="radiogroup"]','[role="group"]','[role="listbox"]'
          ].join(',');
          document.querySelectorAll(selector).forEach((el) => {
            if (!el.dataset.jtControlId) {
              counter += 1;
              el.dataset.jtControlId = `jt-${counter}`;
            }
          });
          document.documentElement.dataset.jtCounter = String(counter);
        }"""
    )


async def _control_count(page) -> int:
    return await page.locator(
        'select,input[list],[role="combobox"],input[type="radio"],[role="radio"],'
        'input[type="checkbox"],[role="checkbox"]'
    ).count()


async def fill_policy_controls(
    page,
    policies: Iterable[Dict[str, Any]],
    log: Optional[List[Dict[str, Any]]] = None,
    *,
    max_passes: int = MAX_DYNAMIC_PASSES,
) -> ControlEngineOutcome:
    policies = list(policies)
    outcome = ControlEngineOutcome()
    log = log if log is not None else []
    processed: set[str] = set()
    previous_count = -1

    for pass_number in range(1, max_passes + 1):
        outcome.passes = pass_number
        await _prepare_ids(page)
        before = outcome.filled_count

        for select in await page.query_selector_all("select"):
            outcome.filled_count += await handle_select(
                page, select, policies, outcome, processed, pass_number
            )
        for datalist in await page.query_selector_all("input[list]"):
            outcome.filled_count += await handle_datalist(
                page, datalist, policies, outcome, processed, pass_number
            )
        for key, group, choices in await collect_native_groups(page, "radio"):
            outcome.filled_count += await handle_choice_group(
                page, group_key=key, group=group, choices=choices,
                input_type="radio", policies=policies, outcome=outcome,
                processed=processed, pass_number=pass_number,
            )
        for key, group, choices in await collect_native_groups(page, "checkbox"):
            outcome.filled_count += await handle_choice_group(
                page, group_key=key, group=group, choices=choices,
                input_type="checkbox_single" if len(choices) == 1 else "checkbox_group",
                policies=policies, outcome=outcome, processed=processed,
                pass_number=pass_number,
            )
        for key, group, choices in await collect_aria_groups(page, "radio"):
            outcome.filled_count += await handle_choice_group(
                page, group_key=key, group=group, choices=choices,
                input_type="radio", policies=policies, outcome=outcome,
                processed=processed, pass_number=pass_number,
            )
        for key, group, choices in await collect_aria_groups(page, "checkbox"):
            outcome.filled_count += await handle_choice_group(
                page, group_key=key, group=group, choices=choices,
                input_type="checkbox_single" if len(choices) == 1 else "checkbox_group",
                policies=policies, outcome=outcome, processed=processed,
                pass_number=pass_number,
            )
        for combobox in await page.query_selector_all('[role="combobox"]:not(select)'):
            outcome.filled_count += await handle_combobox(
                page, combobox, policies, outcome, processed, pass_number
            )

        await page.wait_for_timeout(_SETTLE_MS)
        current_count = await _control_count(page)
        if outcome.filled_count == before and current_count == previous_count:
            break
        previous_count = current_count

    log.extend(outcome.evidence)
    log.append({
        "action": "control_engine_complete",
        "control_engine_version": CONTROL_ENGINE_VERSION,
        "filled_count": outcome.filled_count,
        "review_count": len(outcome.review_items),
        "passes": outcome.passes,
    })
    return outcome


def certification_manifest() -> Dict[str, Any]:
    return {
        "control_engine_version": CONTROL_ENGINE_VERSION,
        "certification_level": "standards_fixture_certified",
        "universally_certified": False,
        "surfaces": {
            "native_select_single": True,
            "native_select_multiple": True,
            "native_radio_group": True,
            "native_radio_same_name": True,
            "native_checkbox_single": True,
            "native_checkbox_group": True,
            "native_datalist": True,
            "aria_combobox_listbox": True,
            "aria_radio": True,
            "aria_checkbox": True,
            "dynamic_conditional_controls": True,
        },
        "safety_invariants": {
            "no_fallback_option_selection": True,
            "exact_or_unambiguous_match_required": True,
            "post_action_verification": True,
            "required_unknown_controls_block_submission": True,
            "optional_unknown_controls_untouched": True,
            "ambiguous_matches_block_submission": True,
        },
        "universal_boundary": (
            "No finite test suite can certify every proprietary or future web control. "
            "Each ATS adapter requires supervised certification evidence."
        ),
    }


__all__ = [
    "CONTROL_ENGINE_VERSION",
    "ControlEngineOutcome",
    "OptionRecord",
    "certification_manifest",
    "element_descriptor",
    "fill_policy_controls",
    "match_answers_to_options",
    "normalize_text",
    "parse_policy_answers",
]
