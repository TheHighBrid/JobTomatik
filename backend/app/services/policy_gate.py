"""Fail-closed policy gate for unattended job-application actions.

Every scheduled action must receive an explicit ALLOW before it may create
or submit an application. The gate is storage-agnostic: callers inject the
current job facts, operation counters, platform switches, and the adapter's
live maturity value.

The adapter maturity must be read from the runtime registry at evaluation
time. A PR description, cached report, or historical certification artifact
is not an authorization source.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Callable


class PolicyDecision(str, enum.Enum):
    ALLOW = "allow"
    BLOCK = "block"


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason_code: str
    detail: str

    @property
    def allowed(self) -> bool:
        return self.decision is PolicyDecision.ALLOW


@dataclass(frozen=True)
class JobContext:
    """Minimum verified job facts required by the unattended gate."""

    adapter_platform: str
    employer_id: str
    employer_name: str
    job_id: str
    location: str | None = None
    salary_min: int | None = None
    seniority: str | None = None
    language: str | None = None
    requires_sponsorship: bool | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class OperationCounters:
    submissions_today_global: int = 0
    submissions_this_week_global: int = 0
    submissions_today_for_employer: dict[str, int] = field(default_factory=dict)
    consecutive_failures_by_source: dict[str, int] = field(default_factory=dict)
    circuit_open_until_by_adapter: dict[str, datetime] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyConfig:
    global_autonomy_enabled: bool = False
    platform_enabled: dict[str, bool] = field(default_factory=dict)
    platform_maturity: dict[str, str] = field(default_factory=dict)
    required_platform_maturity: str = "certified_autonomous"

    daily_cap_global: int = 0
    weekly_cap_global: int = 0
    daily_cap_per_employer: int = 1

    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None

    employer_allow_list: set[str] | None = None
    employer_exclude_list: set[str] = field(default_factory=set)

    allowed_locations: set[str] | None = None
    min_salary: int | None = None
    allowed_seniority: set[str] | None = None
    allowed_languages: set[str] | None = None
    require_sponsorship_match: bool = True
    require_known_job_attributes: bool = True

    circuit_breaker_failure_threshold: int = 5


class PolicyGate:
    """Return the first blocking decision, never a weighted risk score."""

    def __init__(
        self,
        config: PolicyConfig,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    ) -> None:
        self.config = config
        self._now = now_fn

    def evaluate(self, ctx: JobContext, counters: OperationCounters) -> PolicyResult:
        checks = (
            self._check_global_kill_switch,
            self._check_platform_kill_switch,
            self._check_platform_certified,
            self._check_circuit_breaker,
            self._check_quiet_hours,
            self._check_employer_lists,
            self._check_caps,
            self._check_job_constraints,
        )
        for check in checks:
            result = check(ctx, counters)
            if not result.allowed:
                return result
        return PolicyResult(
            PolicyDecision.ALLOW,
            "all_checks_passed",
            "Every unattended-operation policy check passed. Adapter field, "
            "answer-policy, and submission-evidence gates still apply.",
        )

    def _check_global_kill_switch(
        self, ctx: JobContext, counters: OperationCounters
    ) -> PolicyResult:
        if not self.config.global_autonomy_enabled:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "global_kill_switch_off",
                "Global unattended automation is disabled.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok", "")

    def _check_platform_kill_switch(
        self, ctx: JobContext, counters: OperationCounters
    ) -> PolicyResult:
        if not self.config.platform_enabled.get(ctx.adapter_platform, False):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "platform_kill_switch_off",
                f"Unattended automation is disabled for '{ctx.adapter_platform}'.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok", "")

    def _check_platform_certified(
        self, ctx: JobContext, counters: OperationCounters
    ) -> PolicyResult:
        maturity = self.config.platform_maturity.get(ctx.adapter_platform)
        required = self.config.required_platform_maturity
        if maturity != required:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "platform_not_certified",
                f"'{ctx.adapter_platform}' runtime maturity is {maturity!r}, not "
                f"{required!r}.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok", "")

    def _check_circuit_breaker(
        self, ctx: JobContext, counters: OperationCounters
    ) -> PolicyResult:
        now = self._now()
        open_until = counters.circuit_open_until_by_adapter.get(ctx.adapter_platform)
        if open_until and now < open_until:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "circuit_open",
                f"Circuit for '{ctx.adapter_platform}' is open until "
                f"{open_until.isoformat()}.",
            )
        failures = counters.consecutive_failures_by_source.get(ctx.source, 0)
        if failures >= self.config.circuit_breaker_failure_threshold:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "circuit_threshold_reached",
                f"Source '{ctx.source}' has {failures} consecutive failures.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok", "")

    def _check_quiet_hours(
        self, ctx: JobContext, counters: OperationCounters
    ) -> PolicyResult:
        start = self.config.quiet_hours_start
        end = self.config.quiet_hours_end
        if start is None or end is None or start == end:
            return PolicyResult(PolicyDecision.ALLOW, "ok", "")
        current = self._now().time()
        in_quiet = (
            start <= current < end
            if start < end
            else current >= start or current < end
        )
        if in_quiet:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "quiet_hours",
                f"Current UTC time {current.isoformat()} is inside {start}-{end}.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok", "")

    def _check_employer_lists(
        self, ctx: JobContext, counters: OperationCounters
    ) -> PolicyResult:
        employer_id = ctx.employer_id.strip().lower()
        allow_list = self.config.employer_allow_list
        if allow_list is not None and employer_id not in allow_list:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "employer_not_in_allow_list",
                f"'{ctx.employer_name}' is not in the unattended allow list.",
            )
        if employer_id in self.config.employer_exclude_list:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "employer_excluded",
                f"'{ctx.employer_name}' is in the unattended exclude list.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok", "")

    def _check_caps(
        self, ctx: JobContext, counters: OperationCounters
    ) -> PolicyResult:
        cfg = self.config
        if cfg.daily_cap_global and counters.submissions_today_global >= cfg.daily_cap_global:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "daily_cap_reached",
                f"Daily count {counters.submissions_today_global} reached cap "
                f"{cfg.daily_cap_global}.",
            )
        if cfg.weekly_cap_global and (
            counters.submissions_this_week_global >= cfg.weekly_cap_global
        ):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "weekly_cap_reached",
                f"Weekly count {counters.submissions_this_week_global} reached cap "
                f"{cfg.weekly_cap_global}.",
            )
        employer_count = counters.submissions_today_for_employer.get(
            ctx.employer_id.strip().lower(), 0
        )
        if cfg.daily_cap_per_employer and employer_count >= cfg.daily_cap_per_employer:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "employer_daily_cap_reached",
                f"Daily employer count {employer_count} reached cap "
                f"{cfg.daily_cap_per_employer}.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok", "")

    def _check_job_constraints(
        self, ctx: JobContext, counters: OperationCounters
    ) -> PolicyResult:
        cfg = self.config
        if not ctx.employer_id or not ctx.job_id:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "job_identity_unknown",
                "Unattended submission requires a verified employer and job identifier.",
            )
        if cfg.require_known_job_attributes:
            missing = [
                name
                for name, value in (
                    ("location", ctx.location),
                    ("salary_min", ctx.salary_min),
                    ("seniority", ctx.seniority),
                    ("language", ctx.language),
                    ("requires_sponsorship", ctx.requires_sponsorship),
                )
                if value is None
            ]
            if missing:
                return PolicyResult(
                    PolicyDecision.BLOCK,
                    "job_attributes_unknown",
                    "Unattended submission requires known job attributes: "
                    + ", ".join(missing),
                )

        if cfg.allowed_locations is not None and ctx.location not in cfg.allowed_locations:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "location_not_allowed",
                f"Location {ctx.location!r} is not allowed.",
            )
        if cfg.min_salary is not None and (
            ctx.salary_min is None or ctx.salary_min < cfg.min_salary
        ):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "below_min_salary",
                f"Salary floor {ctx.salary_min!r} is below {cfg.min_salary}.",
            )
        if cfg.allowed_seniority is not None and ctx.seniority not in cfg.allowed_seniority:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "seniority_not_allowed",
                f"Seniority {ctx.seniority!r} is not allowed.",
            )
        if cfg.allowed_languages is not None and ctx.language not in cfg.allowed_languages:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "language_not_allowed",
                f"Language {ctx.language!r} is not allowed.",
            )
        if cfg.require_sponsorship_match and ctx.requires_sponsorship is None:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "sponsorship_requirement_unknown",
                "The job's sponsorship requirement is unknown.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ok", "")
