from app.config import Settings
from app.services.supervised_platforms import (
    GREENHOUSE_PLATFORM_KEY,
    get_supervised_platform_policy,
    supervised_platform_keys,
)
from app.services.supervised_submission import SUPPORTED_PLATFORM


def test_supervised_platform_registry_preserves_greenhouse_contract():
    policy = get_supervised_platform_policy("greenhouse")

    assert policy is not None
    assert policy.key == GREENHOUSE_PLATFORM_KEY
    assert policy.display_name == "Greenhouse"
    assert policy.pilot_setting_name == "greenhouse_supervised_pilot_enabled"
    assert policy.pilot_disabled_blocker == "greenhouse_supervised_pilot_disabled"
    assert SUPPORTED_PLATFORM == GREENHOUSE_PLATFORM_KEY


def test_registry_is_fail_closed_and_does_not_enable_lever_yet():
    assert supervised_platform_keys() == ("greenhouse",)
    assert get_supervised_platform_policy("lever") is None
    assert get_supervised_platform_policy("ashby") is None
    assert get_supervised_platform_policy("smartrecruiters") is None
    assert get_supervised_platform_policy("workday") is None
    assert get_supervised_platform_policy("generic") is None


def test_greenhouse_pilot_setting_remains_disabled_by_default():
    settings = Settings(_env_file=None)
    policy = get_supervised_platform_policy("greenhouse")

    assert policy is not None
    assert policy.pilot_enabled(settings) is False
