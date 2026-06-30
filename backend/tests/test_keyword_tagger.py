import pytest
from app.services.keyword_tagger import (
    extract_skills, detect_seniority, detect_industry,
    compute_relevance, tag_job
)


def test_extract_skills_python():
    skills = extract_skills("We need a senior Python developer with PostgreSQL and AWS experience.")
    assert "Python" in skills
    assert "PostgreSQL" in skills
    assert "AWS" in skills


def test_extract_skills_react():
    skills = extract_skills("React.js frontend with TypeScript and Tailwind CSS.")
    assert "React" in skills
    assert "TypeScript" in skills
    assert "Tailwind" in skills


def test_detect_seniority_senior():
    assert detect_seniority("Senior Software Engineer with 5+ years") == "Senior"


def test_detect_seniority_junior():
    assert detect_seniority("Junior developer entry-level position") == "Junior"


def test_detect_seniority_staff():
    assert detect_seniority("Staff Engineer at a growing startup") == "Staff"


def test_detect_industry_fintech():
    assert detect_industry("We build payments and banking software") == "FinTech"


def test_detect_industry_saas():
    assert detect_industry("Our SaaS platform serves 10,000 customers") == "SaaS"


def test_compute_relevance_good_match():
    job = {"title": "Senior Python Engineer", "skills": ["Python", "AWS", "PostgreSQL"], "location": "Remote", "salary_min": 150000}
    prefs = {"skills": ["Python", "AWS"], "preferred_titles": ["senior engineer"], "preferred_locations": ["Remote"], "min_salary": 130000}
    score = compute_relevance(job, prefs)
    assert score > 0.6


def test_compute_relevance_poor_match():
    job = {"title": "PHP Developer", "skills": ["PHP", "Laravel"], "location": "Onsite", "salary_min": 80000}
    prefs = {"skills": ["Python", "Go"], "preferred_locations": ["Remote"], "min_salary": 150000}
    score = compute_relevance(job, prefs)
    assert score < 0.5


def test_tag_job_complete():
    raw = {
        "title": "Senior Python Backend Engineer",
        "company": "Acme Inc",
        "description": "We need a senior Python developer with Django, PostgreSQL, AWS, Docker, and Kubernetes experience. Join our SaaS platform team.",
    }
    result = tag_job(raw, {"skills": ["Python", "AWS"]})
    assert "Python" in result["skills"]
    assert result["seniority"] == "Senior"
    assert result["industry"] == "SaaS"
    assert result["relevance_score"] > 0.5
    assert isinstance(result["tags"], list)


def test_tag_job_no_prefs():
    raw = {"title": "Software Engineer", "company": "Co", "description": "Build React apps"}
    result = tag_job(raw)
    assert "relevance_score" in result
    assert isinstance(result["skills"], list)
