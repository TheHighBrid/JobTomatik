from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs/roadmaps/JOBTOMATIK_AUTONOMY_42_DAY_PLAN.md"
SELF = ROOT / "scripts/apply_day7_roadmap_correction.py"
WORKFLOW = ROOT / ".github/workflows/day7-roadmap-correction.yml"

REPLACEMENTS = {
    "**Current Lever pilot:** #86 and draft PR #152": (
        "**Current Lever pilot:** #86 and Phase 2 evidence queue #161; "
        "PR #152 is merged historical evidence"
    ),
    "- Lever Phase A: 2 qualifying retained dry runs out of 30": (
        "- Lever Phase A: 0 qualifying retained dry runs out of 30 "
        "(2 retained CAPTCHA/manual-boundary rows remain nonqualifying)"
    ),
    "- [ ] Confirm draft PR #152 remains evidence-only and is not represented as promotion-ready.": (
        "- [ ] Confirm merged PR #152 remains historical evidence and is not represented as promotion-ready."
    ),
    "# Phase 2: Complete Lever Phase A, 2/30 to 30/30": (
        "# Phase 2: Complete Lever Phase A, 0/30 to 30/30"
    ),
    "## Day 9, Thursday August 6: Lever dry runs 3 through 7": (
        "## Day 9, Thursday August 6: Lever dry runs 1 through 5"
    ),
    "**Daily target:** readiness 7/30 or higher; `final_submit_clicked=false` for every row.": (
        "**Daily target:** readiness 5/30 or higher; `final_submit_clicked=false` for every row."
    ),
    "## Day 10, Friday August 7: Lever dry runs 8 through 12": (
        "## Day 10, Friday August 7: Lever dry runs 6 through 10"
    ),
    "**Daily target:** readiness 12/30 or higher; zero false submitted records.": (
        "**Daily target:** readiness 10/30 or higher; zero false submitted records."
    ),
    "## Day 11, Saturday August 8: Lever dry runs 13 through 17": (
        "## Day 11, Saturday August 8: Lever dry runs 11 through 15"
    ),
    "**Daily target:** readiness 17/30 or higher; all uploads hash-verified.": (
        "**Daily target:** readiness 15/30 or higher; all uploads hash-verified."
    ),
    "## Day 12, Sunday August 9: Lever dry runs 18 through 22": (
        "## Day 12, Sunday August 9: Lever dry runs 16 through 20"
    ),
    "**Daily target:** readiness 22/30 or higher; no cross-target resume path.": (
        "**Daily target:** readiness 20/30 or higher; no cross-target resume path."
    ),
    "## Day 13, Monday August 10: Lever dry runs 23 through 27": (
        "## Day 13, Monday August 10: Lever dry runs 21 through 25"
    ),
    "**Daily target:** readiness 27/30 or higher; all challenge paths remain `needs_review`.": (
        "**Daily target:** readiness 25/30 or higher; all challenge paths remain `needs_review`."
    ),
    "## Day 14, Tuesday August 11: Lever dry runs 28 through 30 and Phase A certification": (
        "## Day 14, Tuesday August 11: Lever dry runs 26 through 30 and Phase A certification"
    ),
    "- [ ] Execute the final three or more qualifying distinct-site dry runs.": (
        "- [ ] Execute the final five or more qualifying distinct-site dry runs."
    ),
    "- [ ] Update PR #152 with final truthful Phase A evidence.": (
        "- [ ] Update issue #161 with final truthful Phase A evidence."
    ),
}


def main() -> None:
    text = ROADMAP.read_text(encoding="utf-8")
    missing = [old for old in REPLACEMENTS if old not in text]
    if missing:
        raise SystemExit(f"Refusing partial correction; missing expected strings: {missing}")

    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new, 1)

    if "2/30 to 30/30" in text or "draft PR #152" in text:
        raise SystemExit("Stale Phase 2 measurement language remains after correction.")

    ROADMAP.write_text(text, encoding="utf-8")
    SELF.unlink()
    WORKFLOW.unlink()


if __name__ == "__main__":
    main()
