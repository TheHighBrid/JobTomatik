from app.services.discovery_scoring import score_discovered_job


def test_title_and_preference_matches_produce_explainable_score():
    result = score_discovered_job(
        {
            "title": "Bilingual Fraud Investigator",
            "company": "Example Bank",
            "location": "Ottawa, ON",
            "description": "Investigate suspicious transactions and AML alerts.",
            "requirements": "French and English banking experience.",
            "salary_min": 82000,
        },
        {
            "preferred_titles": ["Fraud Investigator"],
            "skills": ["AML", "banking"],
            "preferred_locations": ["Ottawa"],
            "min_salary": 75000,
        },
        search_keywords="fraud investigator AML",
        memories=[
            {
                "id": 7,
                "content": "Experienced in fraud investigations, AML, and banking case documentation.",
                "confidence": 0.95,
            }
        ],
    )

    assert result["score_100"] >= 70
    assert result["normalized_score"] >= 0.7
    assert result["matched_terms"][0]["where"] == "title"
    assert 7 in result["memory_matches"]
    assert result["hard_blockers"] == []
    assert result["scoring_version"] == "jobtomatik-deterministic-discovery-v1"


def test_company_and_title_blocklists_fail_closed():
    company_blocked = score_discovered_job(
        {
            "title": "Fraud Analyst",
            "company": "Blocked Corp",
            "location": "Remote",
            "description": "AML and fraud work",
        },
        {"company_blacklist": ["Blocked Corp"]},
        search_keywords="fraud",
    )
    title_blocked = score_discovered_job(
        {
            "title": "Commission Sales Agent",
            "company": "Example",
            "location": "Ottawa",
            "description": "Banking products",
        },
        {"title_blacklist": ["sales agent"]},
        search_keywords="banking",
    )

    assert company_blocked["score_100"] == 0
    assert company_blocked["hard_blockers"] == ["blocked company: blocked corp"]
    assert title_blocked["score_100"] == 0
    assert title_blocked["hard_blockers"] == ["blocked title: sales agent"]


def test_excluded_terms_penalize_without_inventing_a_hard_blocker():
    clean = score_discovered_job(
        {
            "title": "Client Service Analyst",
            "company": "Example",
            "location": "Ottawa",
            "description": "Banking client service and compliance.",
        },
        {},
        search_keywords="client service",
    )
    excluded = score_discovered_job(
        {
            "title": "Client Service Analyst",
            "company": "Example",
            "location": "Ottawa",
            "description": "Commission only door to door banking sales.",
        },
        {},
        search_keywords="client service",
    )

    assert excluded["score_100"] < clean["score_100"]
    assert "commission only" in excluded["excluded_terms"]
    assert excluded["hard_blockers"] == []
