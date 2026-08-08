from app.services.dead_letter_drill import run_dead_letter_recovery_drill


def test_dead_letter_recovery_drill_proves_checkpoint_contract():
    report = run_dead_letter_recovery_drill()

    assert report["passed"] is True
    assert report["assertions"]["dead_letter_created"] is True
    assert report["assertions"]["automatic_retry_disabled"] is True
    assert report["assertions"]["verified_checkpoint_requeue"] is True
    assert report["assertions"]["checkpoint_drift_blocked"] is True
    assert report["assertions"]["attempt_history_preserved"] is True
    assert report["assertions"]["exactly_one_additional_attempt_granted"] is True
    assert report["safety"]["browser_opened"] is False
    assert report["safety"]["network_contacted"] is False
    assert report["safety"]["final_submit_clicked"] is False
    assert report["safety"]["recruiter_outreach_sent"] is False
    assert report["safety"]["submission_authorized"] is False
    assert report["safety"]["outreach_authorized"] is False
    assert len(report["report_sha256"]) == 64
