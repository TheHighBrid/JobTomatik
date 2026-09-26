from types import SimpleNamespace

from app.models.answer_policy import AnswerPolicyScope
from app.services.answer_policy import (
    normalize_application_url,
    policy_scope_matches,
    scope_priority,
)


def _policy(scope: str, scope_value: str):
    return SimpleNamespace(scope=scope, scope_value=scope_value)


def test_application_scope_matches_only_exact_position_url():
    policy = _policy(
        AnswerPolicyScope.application.value,
        "https://jobs.lever.co/acme/role-123/apply?source=jobtomatik#form",
    )

    assert policy_scope_matches(
        policy,
        "https://jobs.lever.co/acme/role-123/apply/",
        "Acme",
    )
    assert not policy_scope_matches(
        policy,
        "https://jobs.lever.co/acme/role-456/apply",
        "Acme",
    )


def test_application_scope_outranks_company_platform_and_global():
    assert scope_priority(AnswerPolicyScope.application.value) > scope_priority(
        AnswerPolicyScope.company.value
    )
    assert scope_priority(AnswerPolicyScope.company.value) > scope_priority(
        AnswerPolicyScope.platform.value
    )
    assert scope_priority(AnswerPolicyScope.platform.value) > scope_priority(
        AnswerPolicyScope.global_scope.value
    )


def test_application_url_normalization_ignores_query_fragment_and_trailing_slash():
    assert normalize_application_url(
        "HTTPS://JOBS.LEVER.CO/acme/role-123/apply/?utm_source=x#form"
    ) == "https://jobs.lever.co/acme/role-123/apply"
