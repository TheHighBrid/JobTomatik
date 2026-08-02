from app.api import jobs as jobs_api


def test_job_search_forwards_valid_ats_targets(auth_client):
    response = auth_client.post(
        "/api/jobs/search",
        json={
            "keywords": "fraud investigator",
            "location": "Ottawa",
            "sources": ["greenhouse", "lever"],
            "ats_targets": [
                {
                    "provider": "greenhouse",
                    "identifier": "example-bank",
                    "company": "Example Bank",
                },
                {
                    "provider": "lever",
                    "identifier": "example-fintech",
                    "company": "Example Fintech",
                },
            ],
            "limit": 40,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    search_params = jobs_api.run_job_search.delay.call_args.kwargs["search_params"]
    assert search_params["sources"] == ["greenhouse", "lever"]
    assert search_params["ats_targets"][0] == {
        "provider": "greenhouse",
        "identifier": "example-bank",
        "company": "Example Bank",
    }
    assert search_params["limit"] == 40


def test_job_search_rejects_unsafe_ats_identifier(auth_client):
    response = auth_client.post(
        "/api/jobs/search",
        json={
            "keywords": "fraud",
            "sources": ["greenhouse"],
            "ats_targets": [
                {
                    "provider": "greenhouse",
                    "identifier": "../example",
                }
            ],
        },
    )

    assert response.status_code == 422


def test_job_search_rejects_unknown_ats_provider(auth_client):
    response = auth_client.post(
        "/api/jobs/search",
        json={
            "keywords": "fraud",
            "ats_targets": [
                {
                    "provider": "workday",
                    "identifier": "example",
                }
            ],
        },
    )

    assert response.status_code == 422
