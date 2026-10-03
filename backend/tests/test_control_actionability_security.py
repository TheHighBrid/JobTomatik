import pytest

from app.services.control_primitives import is_actionable


class InspectionFailureControl:
    def __init__(self, failing_inspection):
        self.failing_inspection = failing_inspection

    async def is_visible(self):
        if self.failing_inspection == "visibility":
            raise RuntimeError("Control inspection failed")
        return True

    async def is_enabled(self):
        if self.failing_inspection == "enabled":
            raise RuntimeError("Control inspection failed")
        return True

    async def get_attribute(self, _name):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("inspection", ["visibility", "enabled"])
async def test_failed_control_inspection_is_not_actionable(inspection):
    assert await is_actionable(InspectionFailureControl(inspection)) is False


@pytest.mark.asyncio
async def test_verified_visible_enabled_control_remains_actionable():
    assert await is_actionable(InspectionFailureControl(None)) is True
