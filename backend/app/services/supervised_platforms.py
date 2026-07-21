"""Registry for ATS platforms allowed to use supervised live submission.

Registration is intentionally separate from ATS maturity. A platform can have a
certified dry-run adapter without being eligible for a live supervised pilot.
Adding a platform here must therefore be a deliberate, reviewed safety change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


GREENHOUSE_PLATFORM_KEY = "greenhouse"


@dataclass(frozen=True)
class SupervisedPlatformPolicy:
    key: str
    display_name: str
    pilot_setting_name: str
    pilot_disabled_blocker: str

    def pilot_enabled(self, settings: Any) -> bool:
        return bool(getattr(settings, self.pilot_setting_name, False))


_POLICIES: Dict[str, SupervisedPlatformPolicy] = {
    GREENHOUSE_PLATFORM_KEY: SupervisedPlatformPolicy(
        key=GREENHOUSE_PLATFORM_KEY,
        display_name="Greenhouse",
        pilot_setting_name="greenhouse_supervised_pilot_enabled",
        pilot_disabled_blocker="greenhouse_supervised_pilot_disabled",
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
    "SupervisedPlatformPolicy",
    "get_supervised_platform_policy",
    "supervised_platform_keys",
]
