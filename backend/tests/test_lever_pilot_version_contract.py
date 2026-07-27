from app.services.ats_lever import LEVER_ADAPTER_VERSION, LeverAdapter
from app.services.supervised_platforms import (
    LEVER_PLATFORM_KEY,
    get_supervised_platform_policy,
)


def test_lever_runtime_version_matches_supervised_registry():
    policy = get_supervised_platform_policy(LEVER_PLATFORM_KEY)

    assert policy is not None
    assert LEVER_ADAPTER_VERSION == "1.1.0"
    assert LeverAdapter.version == LEVER_ADAPTER_VERSION
    assert policy.adapter_version == LEVER_ADAPTER_VERSION
