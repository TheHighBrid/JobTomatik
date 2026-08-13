from app.auth import hash_password
from app.models.evaluation import OpportunityEvaluation
from app.models.intelligence import AgentRun, CareerMemory, KnowledgeEdge, KnowledgeNode
from app.models.job import Job, JobSource
from app.models.user import User
from app.services.discovery_pipeline import persist_discovery_results


def _official_job():
    return {
        "external_id": "greenhouse:example-bank:101",
        "title": "Bilingual Fraud Investigator",
        "company": "Example Bank",
        "location": "Ottawa, ON",
        "salary_min": 82000,
        "salary_max": 94000,
        "salary_currency": "CAD",
        "job_type": "full_time",
        "description": "Investigate fraud alerts, suspicious transactions, and AML cases.",
        "requirements": "Bilingual English and French banking experience.",
        "url": "https://boards.greenhouse.io/example-bank/jobs/101",
        "source": "greenhouse",
        "raw_data": {
            "official_public_ats": True,
            "ats_provider": "greenhouse",
            "ats_identifier": "example-bank",
            "provider_api_url": "https://boards-api.greenhouse.io/v1/boards/example-bank/jobs",
            "application_method": "external_url",
            "selected_apply_url": "https://boards.greenhouse.io/example-bank/jobs/101",
        },
    }


def test_pipeline_persists_job_evaluation_graph_memory_and_agent_run(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    user.job_preferences = {
        "preferred_titles": ["Fraud Investigator"],
        "skills": ["AML", "banking", "bilingual"],
        "preferred_locations": ["Ottawa"],
        "min_salary": 75000,
    }
    memory = CareerMemory(
        user_id=user.id,
        kind="achievement",
        key="fraud-proof",
        content="Fraud investigation, AML review, and banking case documentation.",
        confidence=0.95,
        source="user",
    )
    db_session.add(memory)
    db_session.commit()

    stats = persist_discovery_results(
        db_session,
        user,
        [_official_job()],
        keywords="fraud investigator AML",
        search_params={
            "keywords": "fraud investigator AML",
            "sources": ["greenhouse"],
            "ats_targets": [
                {
                    "provider": "greenhouse",
                    "identifier": "example-bank",
                    "company": "Example Bank",
                }
            ],
        },
    )
    db_session.commit()

    job = db_session.query(Job).one()
    evaluation = db_session.query(OpportunityEvaluation).one()
    run = db_session.query(AgentRun).one()
    db_session.refresh(memory)

    assert stats["saved"] == 1
    assert stats["job_ids"] == [job.id]
    assert stats["evaluations_created"] == 1
    assert stats["knowledge_nodes_created"] == 2
    assert stats["knowledge_edges_created"] == 1
    assert stats["memories_used"] == 1
    assert job.source == JobSource.greenhouse
    assert job.relevance_score >= 0.7
    assert "discovery_score" not in job.raw_data
    assert evaluation.source_snapshot["scoring"]["memory_matches"] == [memory.id]
    assert evaluation.job_id == job.id
    assert evaluation.user_id == user.id
    assert evaluation.legitimacy_status == "likely_legitimate"
    assert evaluation.analysis_blocks["G"]["official_public_ats"] is True
    assert evaluation.source_snapshot["ats_identifier"] == "example-bank"
    assert db_session.query(KnowledgeNode).count() == 2
    assert db_session.query(KnowledgeEdge).count() == 1
    assert run.status == "completed"
    assert run.result["saved"] == 1
    assert run.result["job_ids"] == [job.id]
    assert all(task.status == "completed" for task in run.tasks)
    assert memory.last_used_at is not None

    duplicate_stats = persist_discovery_results(
        db_session,
        user,
        [_official_job()],
        keywords="fraud investigator AML",
    )
    db_session.commit()

    assert duplicate_stats["saved"] == 0
    assert duplicate_stats["duplicates"] == 1
    assert duplicate_stats["job_ids"] == [job.id]
    assert duplicate_stats["evaluations_created"] == 0
    assert db_session.query(Job).count() == 1
    assert db_session.query(OpportunityEvaluation).count() == 1


def test_global_job_dedupe_still_creates_user_scoped_intelligence(auth_client, db_session):
    first_user = db_session.query(User).filter(User.email == "test@example.com").one()
    first_user.job_preferences = {
        "preferred_titles": ["Fraud Investigator"],
        "preferred_locations": ["Ottawa"],
    }
    second_user = User(
        email="second@example.com",
        hashed_password=hash_password("testpass456"),
        full_name="Second User",
        job_preferences={
            "preferred_titles": ["AML Analyst"],
            "skills": ["AML", "bilingual"],
            "preferred_locations": ["Ottawa"],
        },
    )
    db_session.add(second_user)
    db_session.commit()

    first_stats = persist_discovery_results(
        db_session,
        first_user,
        [_official_job()],
        keywords="fraud investigator",
    )
    db_session.commit()
    second_stats = persist_discovery_results(
        db_session,
        second_user,
        [_official_job()],
        keywords="AML bilingual",
    )
    db_session.commit()

    job = db_session.query(Job).one()
    evaluations = db_session.query(OpportunityEvaluation).order_by(OpportunityEvaluation.user_id).all()

    assert first_stats["saved"] == 1
    assert first_stats["job_ids"] == [job.id]
    assert second_stats["saved"] == 0
    assert second_stats["duplicates"] == 1
    assert second_stats["job_ids"] == [job.id]
    assert second_stats["evaluations_created"] == 1
    assert db_session.query(Job).count() == 1
    assert "discovery_score" not in job.raw_data
    assert {evaluation.user_id for evaluation in evaluations} == {first_user.id, second_user.id}
    assert all(evaluation.job_id == job.id for evaluation in evaluations)
    assert all("scoring" in evaluation.source_snapshot for evaluation in evaluations)
    assert db_session.query(KnowledgeNode).count() == 4
    assert db_session.query(KnowledgeEdge).count() == 2


def test_pipeline_blocks_configured_company_before_persistence(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    user.job_preferences = {"company_blacklist": ["Example Bank"]}
    db_session.commit()

    stats = persist_discovery_results(
        db_session,
        user,
        [_official_job()],
        keywords="fraud",
    )
    db_session.commit()

    assert stats["blocked"] == 1
    assert stats["saved"] == 0
    assert stats["job_ids"] == []
    assert stats["blocked_reasons"] == {"blocked company: example bank": 1}
    assert db_session.query(Job).count() == 0
    assert db_session.query(OpportunityEvaluation).count() == 0
