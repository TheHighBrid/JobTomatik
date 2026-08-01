from app.services.intelligence_foundation import build_adaptive_plan, selector_health_score


def test_selector_health_rewards_successful_evidence():
    new_strategy = selector_health_score(confidence=0.5, success_count=0, failure_count=0)
    proven_strategy = selector_health_score(confidence=0.5, success_count=8, failure_count=1)
    failing_strategy = selector_health_score(confidence=0.5, success_count=1, failure_count=8)

    assert proven_strategy > new_strategy > failing_strategy


def test_application_plan_is_guarded_and_multi_agent():
    plan = build_adaptive_plan(
        "Find and apply to a strong fraud investigator role, then contact the recruiter",
        autonomy_level="reviewed",
        run_context={"job_id": 17, "application_id": 23},
    )
    agent_types = [task["agent_type"] for task in plan["tasks"]]

    assert "discovery" in agent_types
    assert "evaluation" in agent_types
    assert "company_research" in agent_types
    assert "tailoring" in agent_types
    assert "application" in agent_types
    assert "recruiter_crm" in agent_types
    assert agent_types[-1] == "memory"
    assert plan["risk_level"] == "high"
    assert plan["requires_approval"] is True
    assert plan["guardrails"]["confirmation_evidence_required"] is True


def test_intelligence_api_vertical_slice(auth_client):
    memory_response = auth_client.post(
        "/api/intelligence/memories",
        json={
            "kind": "achievement",
            "key": "fraud-investigation-proof",
            "content": "Resolved a complex account investigation with documented evidence.",
            "confidence": 0.95,
            "source": "user",
        },
    )
    assert memory_response.status_code == 201

    recruiter_response = auth_client.post(
        "/api/intelligence/recruiters",
        json={
            "company": "Example Bank",
            "full_name": "Alex Recruiter",
            "title": "Talent Partner",
            "relationship_score": 35,
        },
    )
    assert recruiter_response.status_code == 201
    recruiter_id = recruiter_response.json()["id"]

    interaction_response = auth_client.post(
        f"/api/intelligence/recruiters/{recruiter_id}/interactions",
        json={
            "direction": "outbound",
            "channel": "linkedin",
            "interaction_type": "connection_request",
            "summary": "Sent a concise role-specific connection request.",
        },
    )
    assert interaction_response.status_code == 201

    company_node = auth_client.post(
        "/api/intelligence/knowledge/nodes",
        json={
            "node_type": "company",
            "external_key": "example-bank",
            "label": "Example Bank",
            "payload": {"industry": "banking"},
        },
    )
    role_node = auth_client.post(
        "/api/intelligence/knowledge/nodes",
        json={
            "node_type": "role",
            "external_key": "fraud-investigator",
            "label": "Fraud Investigator",
        },
    )
    assert company_node.status_code == 201
    assert role_node.status_code == 201

    edge_response = auth_client.post(
        "/api/intelligence/knowledge/edges",
        json={
            "from_node_id": company_node.json()["id"],
            "to_node_id": role_node.json()["id"],
            "relation": "hires_for",
            "weight": 1.0,
        },
    )
    assert edge_response.status_code == 201

    selector_response = auth_client.post(
        "/api/intelligence/selectors/outcomes",
        json={
            "platform": "greenhouse",
            "page_signature": "application-form-v1",
            "intent": "continue",
            "selector": "button[data-qa='continue']",
            "strategy_type": "css",
            "success": True,
        },
    )
    assert selector_response.status_code == 200
    assert selector_response.json()["success_count"] == 1

    run_response = auth_client.post(
        "/api/intelligence/agent-runs",
        json={
            "objective": "Research and apply to this role, then prepare recruiter follow-up",
            "autonomy_level": "reviewed",
            "run_context": {"job_id": 1},
        },
    )
    assert run_response.status_code == 201
    assert run_response.json()["requires_approval"] is True
    assert len(run_response.json()["tasks"]) >= 5

    overview_response = auth_client.get("/api/intelligence/overview")
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["memories"] == 1
    assert overview["recruiter_contacts"] == 1
    assert overview["knowledge_nodes"] == 2
    assert overview["knowledge_edges"] == 1
    assert overview["selector_strategies"] == 1
    assert overview["agent_runs"] == 1


def _register_and_login(client, email):
    register = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "testpass123",
            "full_name": email.split("@")[0],
        },
    )
    assert register.status_code == 201
    login = client.post(
        "/api/auth/login",
        data={"username": email, "password": "testpass123"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_selector_strategies_are_account_scoped(client):
    user_a = _register_and_login(client, "selector-a@example.com")
    user_b = _register_and_login(client, "selector-b@example.com")
    payload = {
        "platform": "lever",
        "page_signature": "application-v2",
        "intent": "continue",
        "selector": "button[data-qa='next']",
        "strategy_type": "css",
        "success": True,
    }

    created = client.post(
        "/api/intelligence/selectors/outcomes",
        json=payload,
        headers=user_a,
    )
    assert created.status_code == 200

    params = {
        "platform": payload["platform"],
        "page_signature": payload["page_signature"],
        "intent": payload["intent"],
    }
    hidden = client.get(
        "/api/intelligence/selectors/recommendation",
        params=params,
        headers=user_b,
    )
    assert hidden.status_code == 404

    user_b_overview = client.get("/api/intelligence/overview", headers=user_b)
    assert user_b_overview.status_code == 200
    assert user_b_overview.json()["selector_strategies"] == 0

    visible = client.get(
        "/api/intelligence/selectors/recommendation",
        params=params,
        headers=user_a,
    )
    assert visible.status_code == 200
    assert visible.json()["selector"] == payload["selector"]
