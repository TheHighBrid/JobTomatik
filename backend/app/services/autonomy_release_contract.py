"""Executable, fail-closed contract for certified autonomous ATS promotion."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Dict, Mapping


AUTONOMY_RELEASE_SCHEMA_VERSION = "autonomy_release_v1"
AUTONOMY_RELEASE_CONTRACT_VERSION = "day27_v1"
AUTONOMY_SIGNATURE_METHOD = "hmac-sha256"
MIN_SIGNING_KEY_BYTES = 32
# The roadmap's supervised gate is ten distinct confirmed submissions. Sustained
# autonomy evidence starts from that established sample and must additionally pass
# the 4h, 8h, and 24h unattended shadow gates below.
MIN_RELIABILITY_ATTEMPTS = 10
MIN_DISTINCT_CONFIRMED_SUBMISSIONS = 10
MIN_SUCCESS_RATE = 0.98
MAX_AUTOMATIC_RETRIES_PER_ATTEMPT = 1
REQUIRED_RECOVERY_DRILLS = (
    "process_crash",
    "worker_restart",
    "redis_interruption",
    "database_lock",
    "browser_death",
)
REQUIRED_POLICY_CONTROLS = (
    "daily_weekly_caps",
    "quiet_hours",
    "employer_exclusions",
    "platform_limits",
    "kill_switch",
)
REQUIRED_SHADOW_CHECKS = (
    "final_submit_disabled",
    "four_hour_unattended_passed",
    "eight_hour_unattended_passed",
    "twenty_four_hour_unattended_passed",
    "no_leaked_sessions",
    "source_outage_breaker_verified",
    "browser_crash_recovery_verified",
    "stale_posting_rejected",
    "ambiguous_question_held",
    "quiet_hour_transition_verified",
    "daily_cap_reset_verified",
    "zero_policy_escapes",
    "zero_unexplained_records",
    "zero_duplicate_tasks",
    "zero_false_status_records",
    "no_runaway_retries",
)

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HMAC_SHA256_RE = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _canonical_manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    """Canonicalize the manifest while excluding self-referential outputs."""
    value = json.loads(json.dumps(dict(manifest), sort_keys=True, default=str))
    integrity = value.get("integrity")
    if isinstance(integrity, dict):
        integrity.pop("manifest_digest", None)
    attestation = value.get("attestation")
    if isinstance(attestation, dict):
        attestation.pop("signature", None)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_autonomy_manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Return the content digest that binds every certification field."""
    return "sha256:" + hashlib.sha256(_canonical_manifest_bytes(manifest)).hexdigest()


def _signing_key_bytes(signing_key: str | bytes | None) -> bytes:
    if isinstance(signing_key, bytes):
        return signing_key
    if isinstance(signing_key, str):
        return signing_key.encode("utf-8")
    return b""


def compute_autonomy_manifest_signature(
    manifest: Mapping[str, Any],
    signing_key: str | bytes,
) -> str:
    """Sign the canonical manifest digest with the trusted runtime signing key."""
    key = _signing_key_bytes(signing_key)
    if len(key) < MIN_SIGNING_KEY_BYTES:
        raise ValueError(
            f"Autonomy certification signing key must be at least {MIN_SIGNING_KEY_BYTES} bytes."
        )
    digest = compute_autonomy_manifest_digest(manifest)
    signature = hmac.new(key, digest.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{AUTONOMY_SIGNATURE_METHOD}:{signature}"


def autonomy_release_contract_requirements() -> Dict[str, Any]:
    """Return the machine-readable Day 27 autonomous promotion requirements."""
    return {
        "contract_version": AUTONOMY_RELEASE_CONTRACT_VERSION,
        "schema_version": AUTONOMY_RELEASE_SCHEMA_VERSION,
        "target_maturity": "certified_autonomous",
        "reliability_evidence_type": "supervised_real_submission",
        "minimum_reliability_attempts": MIN_RELIABILITY_ATTEMPTS,
        "minimum_distinct_confirmed_submissions": MIN_DISTINCT_CONFIRMED_SUBMISSIONS,
        "all_confirmed_successes_require_independent_review": True,
        "minimum_success_rate": MIN_SUCCESS_RATE,
        "maximum_automatic_retries_per_attempt": MAX_AUTOMATIC_RETRIES_PER_ATTEMPT,
        "zero_tolerance": [
            "false_positive_submitted_records",
            "duplicate_submissions",
            "uncertain_outcomes_credited_as_submitted",
        ],
        "required_recovery_drills": list(REQUIRED_RECOVERY_DRILLS),
        "required_policy_controls": list(REQUIRED_POLICY_CONTROLS),
        "required_shadow_checks": list(REQUIRED_SHADOW_CHECKS),
        "required_source_bindings": [
            "adapter_name",
            "adapter_version",
            "release_commit",
            "fixture_digest",
            "evidence_digest",
            "policy_digest",
            "manifest_digest",
        ],
        "signature_method": AUTONOMY_SIGNATURE_METHOD,
        "minimum_signing_key_bytes": MIN_SIGNING_KEY_BYTES,
        "trusted_runtime_signing_key_required": True,
        "approval_must_bind_exact_release_commit": True,
        "day39_promotion_blocked_until_shadow_checks_pass": True,
        "runtime_eligibility_requires_certified_autonomous": True,
    }


def _record_check(checks: Dict[str, bool], errors: list[str], name: str, passed: bool) -> None:
    checks[name] = bool(passed)
    if not passed:
        errors.append(name)


def validate_autonomy_release_manifest(
    manifest: Any,
    *,
    adapter_name: str,
    adapter_version: str,
    trusted_signing_key: str | bytes | None = None,
) -> Dict[str, Any]:
    """Validate one candidate autonomous certification manifest.

    Passing release booleans or prose labels cannot promote an adapter unless the
    immutable certification record satisfies the full contract, is bound to the exact
    adapter version and release commit, includes the roadmap supervised/shadow evidence,
    and carries a valid attestation under the separately configured runtime signing key.
    """
    checks: Dict[str, bool] = {}
    missing: list[str] = []

    if not isinstance(manifest, Mapping):
        return {
            "passed": False,
            "checks": {"manifest_present": False},
            "missing": ["manifest_present"],
            "requirements": autonomy_release_contract_requirements(),
        }

    _record_check(
        checks,
        missing,
        "schema_version",
        manifest.get("schema_version") == AUTONOMY_RELEASE_SCHEMA_VERSION,
    )

    adapter = manifest.get("adapter")
    if not isinstance(adapter, Mapping):
        adapter = {}
    _record_check(
        checks,
        missing,
        "adapter_name",
        str(adapter.get("name") or "").strip().lower()
        == str(adapter_name or "").strip().lower(),
    )
    _record_check(
        checks,
        missing,
        "adapter_version",
        str(adapter.get("version") or "").strip() == str(adapter_version or "").strip(),
    )

    source = manifest.get("source")
    if not isinstance(source, Mapping):
        source = {}
    release_commit = str(source.get("release_commit") or "").strip().lower()
    _record_check(checks, missing, "release_commit", bool(_COMMIT_RE.fullmatch(release_commit)))
    for name in ("fixture_digest", "evidence_digest", "policy_digest"):
        value = str(source.get(name) or "").strip().lower()
        _record_check(checks, missing, name, bool(_SHA256_RE.fullmatch(value)))

    reliability = manifest.get("reliability_window")
    if not isinstance(reliability, Mapping):
        reliability = {}
    evidence_type = str(reliability.get("evidence_type") or "").strip().lower()
    attempts = reliability.get("attempts")
    successes = reliability.get("confirmed_successes")
    distinct_successes = reliability.get("distinct_confirmed_submissions")
    independently_reviewed = reliability.get("independently_reviewed_successes")
    reported_rate = reliability.get("success_rate")
    _record_check(
        checks,
        missing,
        "supervised_reliability_evidence",
        evidence_type == "supervised_real_submission",
    )
    attempts_valid = (
        isinstance(attempts, int)
        and not isinstance(attempts, bool)
        and attempts >= MIN_RELIABILITY_ATTEMPTS
    )
    successes_valid = (
        isinstance(successes, int)
        and not isinstance(successes, bool)
        and isinstance(attempts, int)
        and 0 <= successes <= attempts
    )
    distinct_successes_valid = (
        isinstance(distinct_successes, int)
        and not isinstance(distinct_successes, bool)
        and isinstance(successes, int)
        and MIN_DISTINCT_CONFIRMED_SUBMISSIONS <= distinct_successes <= successes
    )
    independent_review_valid = (
        isinstance(independently_reviewed, int)
        and not isinstance(independently_reviewed, bool)
        and isinstance(successes, int)
        and independently_reviewed == successes
    )
    _record_check(checks, missing, "minimum_reliability_attempts", attempts_valid)
    _record_check(checks, missing, "confirmed_success_count_valid", successes_valid)
    _record_check(
        checks,
        missing,
        "minimum_distinct_confirmed_submissions",
        distinct_successes_valid,
    )
    _record_check(
        checks,
        missing,
        "all_successes_independently_reviewed",
        independent_review_valid,
    )
    computed_rate = (
        float(successes) / float(attempts)
        if successes_valid and isinstance(attempts, int) and attempts > 0
        else None
    )
    rate_numeric = isinstance(reported_rate, (int, float)) and not isinstance(reported_rate, bool)
    rate_consistent = bool(
        rate_numeric
        and computed_rate is not None
        and abs(float(reported_rate) - computed_rate) <= 1e-9
    )
    _record_check(checks, missing, "success_rate_consistent", rate_consistent)
    _record_check(
        checks,
        missing,
        "minimum_success_rate",
        bool(rate_consistent and float(reported_rate) >= MIN_SUCCESS_RATE),
    )
    for name in (
        "false_positive_submitted_records",
        "duplicate_submissions",
        "uncertain_outcomes_credited_as_submitted",
    ):
        _record_check(checks, missing, f"zero_{name}", reliability.get(name) == 0)

    retry = manifest.get("retry_policy")
    if not isinstance(retry, Mapping):
        retry = {}
    max_retries = retry.get("max_automatic_retries_per_attempt")
    _record_check(checks, missing, "retry_policy_bounded", retry.get("bounded") is True)
    _record_check(
        checks,
        missing,
        "retry_limit",
        isinstance(max_retries, int)
        and not isinstance(max_retries, bool)
        and 0 <= max_retries <= MAX_AUTOMATIC_RETRIES_PER_ATTEMPT,
    )
    _record_check(
        checks,
        missing,
        "no_retry_after_uncertain_submit",
        retry.get("no_retry_after_submit_click_without_confirmation") is True,
    )

    breaker = manifest.get("circuit_breaker")
    if not isinstance(breaker, Mapping):
        breaker = {}
    threshold = breaker.get("failure_threshold")
    _record_check(checks, missing, "circuit_breaker_verified", breaker.get("verified") is True)
    _record_check(
        checks,
        missing,
        "circuit_breaker_threshold",
        isinstance(threshold, int) and not isinstance(threshold, bool) and threshold >= 1,
    )
    _record_check(
        checks,
        missing,
        "circuit_breaker_halts_new_submissions",
        breaker.get("halts_new_submissions") is True,
    )

    recovery = manifest.get("recovery_drills")
    if not isinstance(recovery, Mapping):
        recovery = {}
    for drill in REQUIRED_RECOVERY_DRILLS:
        _record_check(checks, missing, f"recovery_{drill}", recovery.get(drill) is True)

    policy = manifest.get("policy_readiness")
    if not isinstance(policy, Mapping):
        policy = {}
    _record_check(checks, missing, "policy_ready", policy.get("ready") is True)
    for control in REQUIRED_POLICY_CONTROLS:
        _record_check(checks, missing, f"policy_{control}", policy.get(control) is True)

    shadow = manifest.get("shadow_runs")
    if not isinstance(shadow, Mapping):
        shadow = {}
    for shadow_check in REQUIRED_SHADOW_CHECKS:
        _record_check(
            checks,
            missing,
            f"shadow_{shadow_check}",
            shadow.get(shadow_check) is True,
        )

    approval = manifest.get("approval")
    if not isinstance(approval, Mapping):
        approval = {}
    approval_reference = str(approval.get("approval_reference") or "").strip()
    _record_check(checks, missing, "approval_granted", approval.get("approved") is True)
    _record_check(checks, missing, "approval_reference", bool(approval_reference))
    _record_check(
        checks,
        missing,
        "approval_exact_release_commit",
        bool(release_commit)
        and str(approval.get("approved_for_commit") or "").strip().lower() == release_commit,
    )

    integrity = manifest.get("integrity")
    if not isinstance(integrity, Mapping):
        integrity = {}
    digest = str(integrity.get("manifest_digest") or "").strip().lower()
    _record_check(checks, missing, "integrity_algorithm", integrity.get("algorithm") == "sha256")
    _record_check(checks, missing, "manifest_digest_format", bool(_SHA256_RE.fullmatch(digest)))
    expected_digest = compute_autonomy_manifest_digest(manifest)
    digest_matches = bool(_SHA256_RE.fullmatch(digest)) and digest == expected_digest
    _record_check(checks, missing, "manifest_digest_matches", digest_matches)

    attestation = manifest.get("attestation")
    if not isinstance(attestation, Mapping):
        attestation = {}
    method = str(attestation.get("method") or "").strip().lower()
    key_id = str(attestation.get("key_id") or "").strip()
    signature = str(attestation.get("signature") or "").strip().lower()
    key = _signing_key_bytes(trusted_signing_key)
    key_valid = len(key) >= MIN_SIGNING_KEY_BYTES
    _record_check(checks, missing, "attestation_method", method == AUTONOMY_SIGNATURE_METHOD)
    _record_check(checks, missing, "attestation_key_id", bool(key_id))
    _record_check(checks, missing, "attestation_signature_format", bool(_HMAC_SHA256_RE.fullmatch(signature)))
    _record_check(checks, missing, "trusted_signing_key", key_valid)

    signature_matches = False
    if key_valid and digest_matches and _HMAC_SHA256_RE.fullmatch(signature):
        expected_signature = compute_autonomy_manifest_signature(manifest, key)
        signature_matches = hmac.compare_digest(signature, expected_signature)
    _record_check(checks, missing, "attestation_signature_matches", signature_matches)

    return {
        "passed": not missing,
        "checks": checks,
        "missing": missing,
        "release_commit": release_commit or None,
        "manifest_digest": digest or None,
        "computed_manifest_digest": expected_digest,
        "attestation_key_id": key_id or None,
        "requirements": autonomy_release_contract_requirements(),
    }
