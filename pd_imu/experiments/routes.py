"""External architecture route contracts.

These contracts keep access-gated model architecture work explicit: a route can
be request-ready without being schema-ready, preregistration-ready, or compute-
ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


BLOCKED_BEFORE_ACCESS = (
    "probe script against protected data",
    "download script",
    "cache extraction",
    "pre-registration using new labels",
    "remote job",
    "model run",
    "canonical T1/T3 claim update",
)

ROUTE_ALLOWED_ACTIONS = (
    "access_request_only",
    "schema_probe_only",
    "monitor_or_document_only",
)


@dataclass(frozen=True)
class ExternalArchitectureRoute:
    """Readiness state for one external model-architecture route."""

    route_id: str
    name: str
    priority: int
    current_allowed_action: str
    access_blocker: str
    request_packet_path: str | None = None
    runbook_path: str | None = None
    min_subjects: int | None = 20
    approved_access: bool = False
    row_level_schema_inspected: bool = False
    valid_subject_count: int | None = None

    def can_probe_schema(self) -> bool:
        return self.approved_access is True

    def can_preregister(self) -> bool:
        if self.approved_access is not True or self.row_level_schema_inspected is not True:
            return False
        if self.min_subjects is not None and isinstance(self.min_subjects, int) and not isinstance(self.min_subjects, bool):
            return self.valid_subject_count is not None and self.valid_subject_count >= self.min_subjects
        if self.min_subjects is not None:
            return False
        return True

    def compute_ready(self) -> bool:
        return self.can_preregister()

    def blocked_actions_now(self) -> tuple[str, ...]:
        if self.can_preregister():
            return ()
        if not self.approved_access:
            return BLOCKED_BEFORE_ACCESS
        if not self.row_level_schema_inspected:
            return (
                "cache extraction",
                "pre-registration using new labels",
                "remote job",
                "model run",
                "canonical T1/T3 claim update",
            )
        return (
            "pre-registration using new labels",
            "remote job",
            "model run",
            "canonical T1/T3 claim update",
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.route_id, str) or not self.route_id:
            errors.append("route_id is required")
        if not isinstance(self.name, str) or not self.name:
            errors.append("name is required")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            errors.append("priority must be an integer")
        elif self.priority <= 0:
            errors.append("priority must be positive")
        if not isinstance(self.current_allowed_action, str) or self.current_allowed_action not in ROUTE_ALLOWED_ACTIONS:
            errors.append(f"current_allowed_action must be one of: {', '.join(ROUTE_ALLOWED_ACTIONS)}")
        if not isinstance(self.access_blocker, str) or not self.access_blocker:
            errors.append("access_blocker is required")
        if self.current_allowed_action == "access_request_only":
            if not isinstance(self.request_packet_path, str) or not self.request_packet_path:
                errors.append("access_request_only routes require a request packet path")
            if not isinstance(self.runbook_path, str) or not self.runbook_path:
                errors.append("access_request_only routes require a runbook path")
        if self.request_packet_path is not None and not isinstance(self.request_packet_path, str):
            errors.append("request_packet_path must be a string when set")
        if self.runbook_path is not None and not isinstance(self.runbook_path, str):
            errors.append("runbook_path must be a string when set")
        if self.min_subjects is not None and (
            not isinstance(self.min_subjects, int) or isinstance(self.min_subjects, bool)
        ):
            errors.append("min_subjects must be an integer when set")
        elif self.min_subjects is not None and self.min_subjects <= 0:
            errors.append("min_subjects must be positive when set")
        if not isinstance(self.approved_access, bool):
            errors.append("approved_access must be a boolean")
        if not isinstance(self.row_level_schema_inspected, bool):
            errors.append("row_level_schema_inspected must be a boolean")
        if self.valid_subject_count is not None and (
            not isinstance(self.valid_subject_count, int) or isinstance(self.valid_subject_count, bool)
        ):
            errors.append("valid_subject_count must be an integer when set")
        elif self.valid_subject_count is not None and self.valid_subject_count < 0:
            errors.append("valid_subject_count cannot be negative")
        if self.compute_ready() and self.current_allowed_action == "access_request_only":
            errors.append("access_request_only routes cannot be compute-ready")
        return errors


@dataclass(frozen=True)
class ExternalArchitecturePlan:
    """Ordered route plan for model-side architecture work."""

    routes: tuple[ExternalArchitectureRoute, ...]

    def top_priority(self) -> ExternalArchitectureRoute | None:
        routes = _route_values(self.routes)
        if not routes:
            return None
        return sorted(routes, key=lambda route: route.priority)[0]

    def compute_ready_routes(self) -> tuple[ExternalArchitectureRoute, ...]:
        return tuple(route for route in _route_values(self.routes) if route.compute_ready())

    def access_request_routes(self) -> tuple[ExternalArchitectureRoute, ...]:
        return tuple(route for route in _route_values(self.routes) if route.current_allowed_action == "access_request_only")

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.routes, tuple | list):
            return ["routes must be a tuple or list"]
        for route in self.routes:
            if not isinstance(route, ExternalArchitectureRoute):
                errors.append("routes entries must be ExternalArchitectureRoute")
        routes = _route_values(self.routes)
        priorities = [route.priority for route in routes]
        if len(priorities) != len(set(priorities)):
            errors.append("route priorities must be unique")
        route_ids = [route.route_id for route in routes]
        for route_id in sorted({route_id for route_id in route_ids if route_id and route_ids.count(route_id) > 1}):
            errors.append(f"route ids must be unique: {route_id}")
        for route in routes:
            errors.extend(f"{route.route_id}: {error}" for error in route.validation_errors())
        return errors


def _route_values(values: Any) -> tuple[ExternalArchitectureRoute, ...]:
    if not isinstance(values, tuple | list):
        return ()
    return tuple(route for route in values if isinstance(route, ExternalArchitectureRoute))
