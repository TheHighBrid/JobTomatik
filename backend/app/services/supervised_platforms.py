"""Registry for ATS platforms allowed to use supervised live submission.

Registration is intentionally separate from ATS maturity. A platform can have a
certified dry-run adapter without being eligible for a live supervised pilot.
Each registered platform remains disabled until its own pilot setting is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


GREENHOUSE_PLATFORM_KEY = "greenhouse"
LEVER_PLATFORM_KEY = "lever"


@dataclass(frozen=True)
class SupervisedPlatformPolicy:
    key: str
    display_name: str
    adapter_version: str
    pilot_setting_name: str
    pilot_disabled_blocker: str
    requires_exact_target_identity: bool = False

    def pilot_enabled(self, settings: Any) -> bool:
        return bool(getattr(settings, self.pilot_setting_name, False))


_POLICIES: Dict[str, SupervisedPlatformPolicy] = {
    GREENHOUSE_PLATFORM_KEY: SupervisedPlatformPolicy(
        key=GREENHOUSE_PLATFORM_KEY,
        display_name="Greenhouse",
        adapter_version="1.1.1",
        pilot_setting_name="greenhouse_supervised_pilot_enabled",
        pilot_disabled_blocker="greenhouse_supervised_pilot_disabled",
    ),
    LEVER_PLATFORM_KEY: SupervisedPlatformPolicy(
        key=LEVER_PLATFORM_KEY,
        display_name="Lever",
        adapter_version="1.1.0",
        pilot_setting_name="lever_supervised_pilot_enabled",
        pilot_disabled_blocker="lever_supervised_pilot_disabled",
        requires_exact_target_identity=True,
    ),
}


def get_supervised_platform_policy(
    platform: str | None,
) -> Optional[SupervisedPlatformPolicy]:
    return _POLICIES.get(str(platform or "").strip().lower())


def supervised_platform_keys() -> Tuple[str, ...]:
    return tuple(_POLICIES)


__all__ = [
    "GREENHOUSE_PLATFORM_KEY",
    "LEVER_PLATFORM_KEY",
    "SupervisedPlatformPolicy",
    "get_supervised_platform_policy",
    "supervised_platform_keys",
]
