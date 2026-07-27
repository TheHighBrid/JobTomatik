import ast
from pathlib import Path

import pytest

from app.schemas.application import (
    ApplicationEventOut,
    ApplicationOut,
    FollowUpOut,
    ManualReviewTaskOut,
    SubmissionEvidenceOut,
)
from app.schemas.handoff import HandoffSessionEventOut, HandoffSessionOut
from app.schemas.job import JobOut
from app.schemas.notification import NotificationOut
from app.schemas.user import UserOut, UserProfile


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "backend" / "app" / "schemas"
ORM_OUTPUT_MODELS = (
    NotificationOut,
    JobOut,
    UserOut,
    UserProfile,
    HandoffSessionOut,
    HandoffSessionEventOut,
    FollowUpOut,
    ManualReviewTaskOut,
    SubmissionEvidenceOut,
    ApplicationEventOut,
    ApplicationOut,
)


def test_schema_models_do_not_use_deprecated_class_based_config():
    offenders = []

    for path in sorted(SCHEMA_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for model in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            for member in model.body:
                if isinstance(member, ast.ClassDef) and member.name == "Config":
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{member.lineno}")

    assert offenders == []


@pytest.mark.parametrize("model", ORM_OUTPUT_MODELS)
def test_orm_output_models_use_from_attributes(model):
    assert model.model_config.get("from_attributes") is True
