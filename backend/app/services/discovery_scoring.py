"""Deterministic, explainable scoring for discovered job postings.

The scorer is intentionally independent from an LLM. Every point is attributable to
an explicit preference, search term, memory signal, location, salary, or exclusion.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

DEFAULT_PREFERRED_TERMS: dict[str, int] = {
    "fraud": 18,
    "fraude": 18,
    "anti-money laundering": 18,
    "aml": 18,
    "kyc": 16,
    "compliance": 15,
    "conformité": 15,
    "investigation": 14,
    "investigator": 14,
    "enquête": 14,
    "bilingual": 13,
    "bilingue": 13,
    "banking": 11,
    "financial services": 11,
    "risk": 10,
    "client service": 8,
    "government": 8,
    "ottawa": 6,
    "gatineau": 6,
    "remote": 5,
}
DEFAULT_EXCLUDED_TERMS = [
    "commission only",
    "door to door",
    "unpaid internship",
    "independent contractor commission",
]
_BLOCKLIST_KEYS = ("company_blacklist", "excluded_companies", "blocked_companies")
_TITLE_BLOCKLIST_KEYS = ("title_blacklist", "excluded_titles", "blocked_titles")


def _contains(text: str, term: str) -> bool:
    normalized = term.strip().lower()
    if not normalized:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", text.lower()) is not None


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [str(item) for item in value]
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _search_terms(value: str) -> list[str]:
    phrases = [part.strip().lower() for part in re.split(r"[,;|\n]+", value or "") if part.strip()]
    tokens = [
        token
        for token in re.split(r"[^a-z0-9+#.]+", (value or "").lower())
        if len(token) >= 2 and token not in {"and", "the", "for", "with", "full", "time"}
    ]
    return list(dict.fromkeys([*phrases, *tokens]))


def _memory_content(memories: Iterable[Any]) -> list[tuple[int | None, str, float]]:
    result: list[tuple[int | None, str, float]] = []
    for memory in memories:
        if isinstance(memory, Mapping):
            content = str(memory.get("content") or "")
            memory_id = memory.get("id")
            confidence = float(memory.get("confidence") or 0.0)
        else:
            content = str(getattr(memory, "content", "") or "")
            memory_id = getattr(memory, "id", None)
            confidence = float(getattr(memory, "confidence", 0.0) or 0.0)
        if content:
            result.append((memory_id, content, max(0.0, min(confidence, 1.0))))
    return result


def build_term_weights(
    preferences: Mapping[str, Any] | None,
    *,
    search_keywords: str = "",
    memories: Iterable[Any] = (),
) -> dict[str, int]:
    prefs = preferences or {}
    weights = dict(DEFAULT_PREFERRED_TERMS)

    explicit = prefs.get("preferred_terms")
    if isinstance(explicit, Mapping):
        for term, weight in explicit.items():
            clean = str(term).strip().lower()
            if clean:
                weights[clean] = max(1, min(int(weight), 30))

    for title in _strings(prefs.get("preferred_titles")):
        clean = title.strip().lower()
        if clean:
            weights[clean] = max(weights.get(clean, 0), 20)
            for token in _search_terms(clean):
                weights[token] = max(weights.get(token, 0), 10)

    for skill in _strings(prefs.get("skills")):
        clean = skill.strip().lower()
        if clean:
            weights[clean] = max(weights.get(clean, 0), 13)

    for term in _search_terms(search_keywords):
        weights[term] = max(weights.get(term, 0), 12)

    memory_rows = _memory_content(memories)
    for term in list(weights):
        if any(confidence >= 0.6 and _contains(content, term) for _, content, confidence in memory_rows):
            weights[term] = min(30, weights[term] + 3)

    return weights


def _blocklist(preferences: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for key in keys:
        result.extend(item.strip().lower() for item in _strings(preferences.get(key)) if item.strip())
    return list(dict.fromkeys(result))


def score_discovered_job(
    job: Mapping[str, Any],
    preferences: Mapping[str, Any] | None = None,
    *,
    search_keywords: str = "",
    memories: Iterable[Any] = (),
) -> dict[str, Any]:
    """Return a 0..100 score plus the evidence that produced it."""

    prefs = preferences or {}
    title = str(job.get("title") or "").strip()
    company = str(job.get("company") or "").strip()
    location = str(job.get("location") or "").strip()
    description = str(job.get("description") or "")
    requirements = str(job.get("requirements") or "")
    title_text = title.lower()
    body_text = f"{description} {requirements} {location}".lower()
    combined = f"{title_text} {body_text}"

    hard_blockers: list[str] = []
    for blocked_company in _blocklist(prefs, _BLOCKLIST_KEYS):
        if blocked_company and blocked_company in company.lower():
            hard_blockers.append(f"blocked company: {blocked_company}")
    for blocked_title in _blocklist(prefs, _TITLE_BLOCKLIST_KEYS):
        if blocked_title and blocked_title in title_text:
            hard_blockers.append(f"blocked title: {blocked_title}")

    weights = build_term_weights(
        prefs,
        search_keywords=search_keywords,
        memories=memories,
    )
    matched_terms: list[dict[str, Any]] = []
    raw_term_points = 0
    for term, weight in weights.items():
        if _contains(title_text, term):
            points = int(weight) * 2
            raw_term_points += points
            matched_terms.append({"term": term, "where": "title", "points": points})
        elif _contains(body_text, term):
            points = int(weight)
            raw_term_points += points
            matched_terms.append({"term": term, "where": "body", "points": points})

    excluded_terms = [
        term
        for term in [*DEFAULT_EXCLUDED_TERMS, *_strings(prefs.get("excluded_terms"))]
        if term and _contains(combined, term)
    ]

    location_points = 0
    preferred_locations = [item.lower() for item in _strings(prefs.get("preferred_locations"))]
    if preferred_locations:
        if any(item in location.lower() for item in preferred_locations):
            location_points = 10
        elif "remote" in location.lower():
            location_points = 8
        else:
            location_points = -5
    elif any(item in location.lower() for item in ("ottawa", "gatineau", "remote", "canada")):
        location_points = 5

    salary_points = 0
    minimum_salary = int(prefs.get("min_salary") or 0)
    salary_min = int(job.get("salary_min") or 0)
    if minimum_salary and salary_min:
        if salary_min >= minimum_salary * 1.2:
            salary_points = 10
        elif salary_min >= minimum_salary:
            salary_points = 7
        else:
            salary_points = -8

    memory_matches: list[int] = []
    for memory_id, content, confidence in _memory_content(memories):
        if confidence < 0.6:
            continue
        memory_terms = _search_terms(content)
        if any(len(term) >= 3 and _contains(combined, term) for term in memory_terms[:40]):
            if memory_id is not None:
                memory_matches.append(int(memory_id))
            if len(memory_matches) >= 5:
                break

    base_score = 12
    score = base_score + min(raw_term_points * 0.7, 78) + location_points + salary_points
    score -= 25 * len(set(excluded_terms))
    if hard_blockers:
        score = 0
    score_100 = round(max(0.0, min(float(score), 100.0)), 1)

    matched_terms.sort(key=lambda row: (-int(row["points"]), str(row["term"])))
    return {
        "score_100": score_100,
        "normalized_score": round(score_100 / 100.0, 3),
        "matched_terms": matched_terms[:25],
        "excluded_terms": sorted(set(excluded_terms)),
        "hard_blockers": hard_blockers,
        "location_points": location_points,
        "salary_points": salary_points,
        "memory_matches": memory_matches,
        "term_weight_count": len(weights),
        "scoring_version": "jobtomatik-deterministic-discovery-v1",
    }
