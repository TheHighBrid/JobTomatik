from app.services.shadow_rehearsal import QUALIFICATION_SECONDS, run_shadow_rehearsal


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += float(seconds)


def test_short_shadow_smoke_is_measured_but_not_release_qualifying():
    clock = FakeClock()
    report = run_shadow_rehearsal(
        duration_seconds=2.0,
        interval_seconds=0.5,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert report["completed"] is True
    assert report["measured_elapsed_time"] is True
    assert report["measured_duration_seconds"] >= 2.0
    assert report["qualification_eligible"] is False
    assert not any(report["qualifications"].values())
    assert report["safety"] == {
        "final_submit_enabled": False,
        "final_submit_clicked": False,
        "browser_opened": False,
        "network_contacted": False,
        "runtime_settings_changed": False,
    }
    assert len(report["report_sha256"]) == 64


def test_shadow_qualification_uses_measured_elapsed_time_not_requested_label():
    clock = FakeClock()
    four_hours = QUALIFICATION_SECONDS["shadow_run_4h"]
    report = run_shadow_rehearsal(
        duration_seconds=four_hours,
        interval_seconds=four_hours,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert report["measured_duration_seconds"] >= four_hours
    assert report["qualifications"]["shadow_run_4h"] is True
    assert report["qualifications"]["shadow_run_8h"] is False
    assert report["qualifications"]["shadow_run_24h"] is False
