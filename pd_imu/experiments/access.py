"""Access-packet contracts for gated external model architecture routes."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from pd_imu.experiments.routes import BLOCKED_BEFORE_ACCESS


REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS = BLOCKED_BEFORE_ACCESS
SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS = (
    "download script",
    "cache extraction",
    "pre-registration using new labels",
    "remote job",
    "model run",
    "canonical T1/T3 claim update",
)
SUBMIT_READY_STATUS = "ready_to_submit_after_user_fill_and_governance"
NULLISH_EVIDENCE_VALUES = {"", "none", "unknown", "todo", "tbd", "n/a"}
UNFILLED_PLACEHOLDER_RE = re.compile(r"(<[A-Za-z0-9_][A-Za-z0-9_ -]*>|\[[A-Z0-9_][A-Z0-9_ -]*\])")
LOCAL_PATH_RE = re.compile(r"(^|\s)(~/|/(?:home|tmp|var|root|Users)/|[A-Za-z]:[\\/])")
COMPLETED_FILE_REF_RE = re.compile(r"\.(?:docx|pdf|eml|xlsx|csv|json|zip)\b", re.IGNORECASE)
TOKEN_LIKE_RE = re.compile(
    r"(password\s*=|secret[_-]?key|api[_-]?key|private[_-]?key|synapse[_-]?auth[_-]?token|"
    r"access[_-]?token|auth[_-]?token|bearer\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
ACCESS_ROUTE_LIFECYCLE_STATES = (
    "invalid",
    "packet_ready",
    "submitted_pending_approval",
    "approved_for_schema_probe",
)
ACCESS_NEXT_ACTIONS = (
    "fix_access_evidence",
    "submit_access_request",
    "wait_for_access_approval",
    "run_read_only_schema_probe",
)


@dataclass(frozen=True)
class AccessApprovalEvidence:
    """Non-protected proof that a gated route is approved for schema probing.

    This object deliberately stores approval metadata only. It must not contain
    protected rows, credentials, tokens, or signed agreement text.
    """

    route_id: str
    source: str
    approved_at_utc: str
    approved_access: bool
    data_use_terms_accepted: bool
    storage_plan_documented: bool
    protected_row_dump_included: bool = False
    credentials_or_tokens_included: bool = False
    notes: str = ""

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if _is_nullish_text(self.route_id):
            errors.append("route_id is required")
        errors.extend(_unfilled_placeholder_errors("route_id", self.route_id))
        if _is_nullish_text(self.source):
            errors.append("approval source is required")
        errors.extend(_unfilled_placeholder_errors("approval source", self.source))
        errors.extend(_unsafe_metadata_text_errors("approval source", self.source))
        if _is_nullish_text(self.approved_at_utc):
            errors.append("approved_at_utc is required")
        errors.extend(_unfilled_placeholder_errors("approved_at_utc", self.approved_at_utc))
        if not isinstance(self.approved_access, bool):
            errors.append("approved_access must be a boolean")
        elif not self.approved_access:
            errors.append("approved_access must be true")
        if not isinstance(self.data_use_terms_accepted, bool):
            errors.append("data_use_terms_accepted must be a boolean")
        elif not self.data_use_terms_accepted:
            errors.append("data use terms must be accepted")
        if not isinstance(self.storage_plan_documented, bool):
            errors.append("storage_plan_documented must be a boolean")
        elif not self.storage_plan_documented:
            errors.append("protected data storage plan must be documented")
        if not isinstance(self.protected_row_dump_included, bool):
            errors.append("protected_row_dump_included must be a boolean")
        elif self.protected_row_dump_included:
            errors.append("approval evidence must not include protected row data")
        if not isinstance(self.credentials_or_tokens_included, bool):
            errors.append("credentials_or_tokens_included must be a boolean")
        elif self.credentials_or_tokens_included:
            errors.append("approval evidence must not include credentials or tokens")
        if not isinstance(self.notes, str):
            errors.append("notes must be a string")
        else:
            errors.extend(_unfilled_placeholder_errors("notes", self.notes))
            errors.extend(_unsafe_metadata_text_errors("notes", self.notes))
        return errors

    def validation_errors_for_route(self, route_id: str) -> list[str]:
        errors = self.validation_errors()
        if self.route_id != route_id:
            errors.append("approval evidence route_id does not match route")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccessSubmissionEvidence:
    """Non-protected evidence that an access request was submitted.

    Submission is not approval. This object records only safe metadata and must
    not unlock schema probes, protected-data downloads, preregistration, or
    model execution.
    """

    route_id: str
    submitted_at_utc: str
    submission_channel: str
    submitted_by: str
    confirmation_reference: str | None = None
    completed_packet_committed: bool = False
    credentials_or_tokens_included: bool = False
    protected_row_dump_included: bool = False
    approval_claimed: bool = False
    pre_submission_preflight_passed: bool = False
    notes: str = ""

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if _is_nullish_text(self.route_id):
            errors.append("route_id is required")
        errors.extend(_unfilled_placeholder_errors("route_id", self.route_id))
        if _is_nullish_text(self.submitted_at_utc):
            errors.append("submitted_at_utc is required")
        errors.extend(_unfilled_placeholder_errors("submitted_at_utc", self.submitted_at_utc))
        if _is_nullish_text(self.submission_channel):
            errors.append("submission_channel is required")
        errors.extend(_unfilled_placeholder_errors("submission_channel", self.submission_channel))
        errors.extend(_unsafe_metadata_text_errors("submission_channel", self.submission_channel))
        if _is_nullish_text(self.submitted_by):
            errors.append("submitted_by is required")
        errors.extend(_unfilled_placeholder_errors("submitted_by", self.submitted_by))
        errors.extend(_unsafe_metadata_text_errors("submitted_by", self.submitted_by))
        if self.confirmation_reference is not None and _is_nullish_text(self.confirmation_reference):
            errors.append("confirmation_reference cannot be nullish when provided")
        if self.confirmation_reference is not None:
            errors.extend(_unfilled_placeholder_errors("confirmation_reference", self.confirmation_reference))
            errors.extend(_unsafe_metadata_text_errors("confirmation_reference", self.confirmation_reference))
        if not isinstance(self.completed_packet_committed, bool):
            errors.append("completed_packet_committed must be a boolean")
        elif self.completed_packet_committed:
            errors.append("submission evidence must not include completed packets or signatures")
        if not isinstance(self.credentials_or_tokens_included, bool):
            errors.append("credentials_or_tokens_included must be a boolean")
        elif self.credentials_or_tokens_included:
            errors.append("submission evidence must not include credentials or tokens")
        if not isinstance(self.protected_row_dump_included, bool):
            errors.append("protected_row_dump_included must be a boolean")
        elif self.protected_row_dump_included:
            errors.append("submission evidence must not include protected row data")
        if not isinstance(self.approval_claimed, bool):
            errors.append("approval_claimed must be a boolean")
        elif self.approval_claimed:
            errors.append("submission evidence cannot claim approved access")
        if not isinstance(self.pre_submission_preflight_passed, bool):
            errors.append("pre_submission_preflight_passed must be a boolean")
        elif not self.pre_submission_preflight_passed:
            errors.append("pre-submission completed-packet/package preflight must have passed")
        if not isinstance(self.notes, str):
            errors.append("notes must be a string")
        else:
            errors.extend(_unfilled_placeholder_errors("notes", self.notes))
            errors.extend(_unsafe_metadata_text_errors("notes", self.notes))
        return errors

    def validation_errors_for_packet(self, packet: "AccessPacketSpec") -> list[str]:
        errors = self.validation_errors()
        if self.route_id != packet.route_id:
            errors.append("submission evidence route_id does not match packet")
        if not packet.submit_ready():
            errors.append("submission evidence requires a submit-ready access packet")
        return errors

    def allows_schema_probe(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccessPacketSpec:
    """Readiness contract for one external data-access packet."""

    route_id: str
    name: str
    priority: int
    packet_path: str
    runbook_path: str
    packet_audit_path: str | None
    packet_ready: bool
    runbook_ready: bool
    placeholder_count: int
    submission_status: str
    blocked_actions_now: tuple[str, ...]
    remote_job_allowed_now: bool = False
    scaffold_allowed_now: bool = False
    min_placeholders: int = 5

    @classmethod
    def from_tracker_row(cls, row: dict[str, Any]) -> "AccessPacketSpec":
        packet = row.get("packet", {})
        runbook = row.get("runbook", {})
        priority = row.get("priority", 0)
        placeholder_count = row.get("packet_placeholder_count", 0)
        return cls(
            route_id=str(row.get("id", "")),
            name=str(row.get("name", "")),
            priority=priority if isinstance(priority, int) and not isinstance(priority, bool) else 0,
            packet_path=str(packet.get("path") or ""),
            runbook_path=str(runbook.get("path") or ""),
            packet_audit_path=packet.get("audit"),
            packet_ready=bool(packet.get("exists")) and bool(packet.get("passed")),
            runbook_ready=bool(runbook.get("exists")) and bool(runbook.get("passed")),
            placeholder_count=placeholder_count
            if isinstance(placeholder_count, int) and not isinstance(placeholder_count, bool)
            else 0,
            submission_status=str(row.get("submission_status", "")),
            blocked_actions_now=tuple(str(action) for action in row.get("blocked_actions_now", ())),
            remote_job_allowed_now=bool(row.get("remote_job_allowed_now")),
            scaffold_allowed_now=bool(row.get("scaffold_allowed_now")),
        )

    def compute_ready(self) -> bool:
        return self.remote_job_allowed_now is True or self.scaffold_allowed_now is True

    def submit_ready(self) -> bool:
        return (
            self.submission_status == SUBMIT_READY_STATUS
            and self.packet_ready
            and self.runbook_ready
            and self.placeholder_count >= self.min_placeholders
            and not self.compute_ready()
            and not self.missing_blocked_actions()
        )

    def missing_blocked_actions(self) -> tuple[str, ...]:
        present = set(_string_values(self.blocked_actions_now))
        return tuple(action for action in REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS if action not in present)

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
        if not isinstance(self.packet_path, str) or not self.packet_path:
            errors.append("packet_path is required")
        if not isinstance(self.runbook_path, str) or not self.runbook_path:
            errors.append("runbook_path is required")
        if self.packet_audit_path is not None and not isinstance(self.packet_audit_path, str):
            errors.append("packet_audit_path must be a string when set")
        if not isinstance(self.packet_ready, bool):
            errors.append("packet_ready must be a boolean")
        elif not self.packet_ready:
            errors.append("packet is not ready")
        if not isinstance(self.runbook_ready, bool):
            errors.append("runbook_ready must be a boolean")
        elif not self.runbook_ready:
            errors.append("runbook is not ready")
        if not isinstance(self.placeholder_count, int) or isinstance(self.placeholder_count, bool):
            errors.append("placeholder_count must be an integer")
        elif not isinstance(self.min_placeholders, int) or isinstance(self.min_placeholders, bool):
            errors.append("min_placeholders must be an integer")
        elif self.placeholder_count < self.min_placeholders:
            errors.append(f"packet has fewer than {self.min_placeholders} user-fill placeholders")
        if not isinstance(self.submission_status, str) or self.submission_status != SUBMIT_READY_STATUS:
            errors.append(f"submission_status must be {SUBMIT_READY_STATUS}")
        if not isinstance(self.remote_job_allowed_now, bool):
            errors.append("remote_job_allowed_now must be a boolean")
        if not isinstance(self.scaffold_allowed_now, bool):
            errors.append("scaffold_allowed_now must be a boolean")
        if self.compute_ready():
            errors.append("pre-access compute or scaffold is marked allowed")
        if not isinstance(self.blocked_actions_now, tuple | list | set):
            errors.append("blocked_actions_now must be a tuple or list")
            blocked_actions = []
        else:
            blocked_actions = list(self.blocked_actions_now)
        for action in sorted({action for action in blocked_actions if action and blocked_actions.count(action) > 1}):
            errors.append(f"duplicate blocked pre-access action: {action}")
        for action in blocked_actions:
            if not isinstance(action, str) or not action:
                errors.append("blocked pre-access action is required")
            elif action not in REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS:
                errors.append(f"unknown blocked pre-access action: {action}")
        for action in self.missing_blocked_actions():
            errors.append(f"missing blocked pre-access action: {action}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccessPacketQueue:
    """Ordered access-packet queue for gated external data routes."""

    packets: tuple[AccessPacketSpec, ...]

    @classmethod
    def from_tracker_rows(cls, rows: list[dict[str, Any]]) -> "AccessPacketQueue":
        packets = tuple(AccessPacketSpec.from_tracker_row(row) for row in rows)
        return cls(packets=tuple(sorted(packets, key=lambda packet: packet.priority)))

    def submit_ready_packets(self) -> tuple[AccessPacketSpec, ...]:
        return tuple(packet for packet in self.packets if packet.submit_ready())

    def compute_ready_packets(self) -> tuple[AccessPacketSpec, ...]:
        return tuple(packet for packet in self.packets if packet.compute_ready())

    def validation_errors(self, expected_route_ids: tuple[str, ...] | None = None) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.packets, tuple | list):
            return ["packets must be a tuple or list"]
        for packet in self.packets:
            if not isinstance(packet, AccessPacketSpec):
                errors.append("packets entries must be AccessPacketSpec")
        typed_packets = tuple(packet for packet in self.packets if isinstance(packet, AccessPacketSpec))
        priorities = [packet.priority for packet in typed_packets]
        if len(priorities) != len(set(priorities)):
            errors.append("packet priorities must be unique")
        route_ids = [packet.route_id for packet in typed_packets]
        for route_id in sorted({route_id for route_id in route_ids if route_id and route_ids.count(route_id) > 1}):
            errors.append(f"packet route ids must be unique: {route_id}")
        if expected_route_ids is not None:
            if not isinstance(expected_route_ids, tuple | list):
                errors.append("expected_route_ids must be a tuple or list when set")
                expected_route_ids = ()
            elif any(not isinstance(route_id, str) or not route_id for route_id in expected_route_ids):
                errors.append("expected_route_ids entries must be non-empty strings")
            actual = tuple(packet.route_id for packet in typed_packets[: len(expected_route_ids)])
            if actual != expected_route_ids:
                errors.append(f"route order mismatch: expected {expected_route_ids}, got {actual}")
        for packet in typed_packets:
            errors.extend(f"{packet.route_id}: {error}" for error in packet.validation_errors())
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {"packets": [packet.to_dict() for packet in self.packets]}


@dataclass(frozen=True)
class AccessRouteLifecycle:
    """Fail-closed lifecycle for one gated external-data route."""

    packet: AccessPacketSpec
    submission_evidence: AccessSubmissionEvidence | None = None
    approval_evidence: AccessApprovalEvidence | None = None

    def validation_errors(self) -> list[str]:
        if not isinstance(self.packet, AccessPacketSpec):
            return ["packet must be an AccessPacketSpec"]
        errors = [f"packet: {error}" for error in self.packet.validation_errors()]
        if self.submission_evidence is not None:
            if not isinstance(self.submission_evidence, AccessSubmissionEvidence):
                errors.append("submission_evidence must be an AccessSubmissionEvidence when set")
            else:
                errors.extend(
                    f"submission: {error}"
                    for error in self.submission_evidence.validation_errors_for_packet(self.packet)
                )
        if self.approval_evidence is not None:
            if not isinstance(self.approval_evidence, AccessApprovalEvidence):
                errors.append("approval_evidence must be an AccessApprovalEvidence when set")
            else:
                errors.extend(
                    f"approval: {error}"
                    for error in self.approval_evidence.validation_errors_for_route(self.packet.route_id)
                )
        return errors

    def state(self) -> str:
        if self.validation_errors():
            return "invalid"
        if self.approval_evidence is not None:
            return "approved_for_schema_probe"
        if self.submission_evidence is not None:
            return "submitted_pending_approval"
        return "packet_ready"

    def can_record_submission(self) -> bool:
        return not self.validation_errors() and self.submission_evidence is None

    def can_probe_schema(self) -> bool:
        return self.state() == "approved_for_schema_probe"

    def blocked_actions_now(self) -> tuple[str, ...]:
        if self.can_probe_schema():
            return SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
        return REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS

    def next_action(self) -> "AccessNextAction":
        return AccessNextAction.from_lifecycle(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet": self.packet.to_dict(),
            "submission_evidence": self.submission_evidence.to_dict()
            if self.submission_evidence is not None
            else None,
            "approval_evidence": self.approval_evidence.to_dict() if self.approval_evidence is not None else None,
            "state": self.state(),
            "can_probe_schema": self.can_probe_schema(),
            "blocked_actions_now": list(self.blocked_actions_now()),
        }


@dataclass(frozen=True)
class AccessNextAction:
    """Safe next action derived from one external access lifecycle."""

    route_id: str
    lifecycle_state: str
    action: str
    allowed_now: tuple[str, ...]
    blocked_actions_now: tuple[str, ...]
    safe_to_execute_code: bool = False
    requires_user_action: bool = False

    @classmethod
    def from_lifecycle(cls, lifecycle: AccessRouteLifecycle) -> "AccessNextAction":
        state = lifecycle.state()
        if state == "packet_ready":
            return cls(
                route_id=lifecycle.packet.route_id,
                lifecycle_state=state,
                action="submit_access_request",
                allowed_now=("submit access request",),
                blocked_actions_now=lifecycle.blocked_actions_now(),
                requires_user_action=True,
            )
        if state == "submitted_pending_approval":
            return cls(
                route_id=lifecycle.packet.route_id,
                lifecycle_state=state,
                action="wait_for_access_approval",
                allowed_now=("wait for access approval",),
                blocked_actions_now=lifecycle.blocked_actions_now(),
                requires_user_action=True,
            )
        if state == "approved_for_schema_probe":
            return cls(
                route_id=lifecycle.packet.route_id,
                lifecycle_state=state,
                action="run_read_only_schema_probe",
                allowed_now=("read-only schema probe",),
                blocked_actions_now=lifecycle.blocked_actions_now(),
                safe_to_execute_code=True,
            )
        return cls(
            route_id=lifecycle.packet.route_id,
            lifecycle_state=state,
            action="fix_access_evidence",
            allowed_now=("fix access evidence",),
            blocked_actions_now=lifecycle.blocked_actions_now(),
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.route_id, str) or not self.route_id:
            errors.append("route_id is required")
        if not isinstance(self.lifecycle_state, str) or self.lifecycle_state not in ACCESS_ROUTE_LIFECYCLE_STATES:
            errors.append(f"lifecycle_state must be one of: {', '.join(ACCESS_ROUTE_LIFECYCLE_STATES)}")
        if not isinstance(self.action, str) or self.action not in ACCESS_NEXT_ACTIONS:
            errors.append(f"action must be one of: {', '.join(ACCESS_NEXT_ACTIONS)}")
        if not isinstance(self.allowed_now, tuple | list | set) or not self.allowed_now:
            errors.append("allowed_now must be non-empty")
            allowed_now = ()
        else:
            allowed_now = tuple(self.allowed_now)
            for action in allowed_now:
                if not isinstance(action, str) or not action:
                    errors.append("allowed_now entries must be non-empty strings")
                    break
        if not isinstance(self.blocked_actions_now, tuple | list | set):
            errors.append("blocked_actions_now must be a tuple or list")
            blocked_actions_now = ()
        else:
            blocked_actions_now = tuple(self.blocked_actions_now)
            for action in blocked_actions_now:
                if not isinstance(action, str) or not action:
                    errors.append("blocked_actions_now entries must be non-empty strings")
                    break
        if not isinstance(self.safe_to_execute_code, bool):
            errors.append("safe_to_execute_code must be a boolean")
        if not isinstance(self.requires_user_action, bool):
            errors.append("requires_user_action must be a boolean")
        if self.lifecycle_state != "approved_for_schema_probe" and self.safe_to_execute_code is True:
            errors.append("only approved_for_schema_probe may mark code execution safe")
        if self.action == "run_read_only_schema_probe":
            if self.lifecycle_state != "approved_for_schema_probe":
                errors.append("read-only schema probe action requires approved_for_schema_probe state")
            if allowed_now != ("read-only schema probe",):
                errors.append("schema-probe action may only allow read-only schema probe")
            if blocked_actions_now != SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS:
                errors.append("schema-probe action must keep post-approval modeling actions blocked")
        if self.action == "submit_access_request":
            if self.lifecycle_state != "packet_ready":
                errors.append("submit action requires packet_ready state")
            if self.requires_user_action is not True:
                errors.append("submit action requires user action")
            if self.safe_to_execute_code is True:
                errors.append("submit action must not mark code execution safe")
            if blocked_actions_now != REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS:
                errors.append("submit action must keep all pre-access compute actions blocked")
        if self.action == "wait_for_access_approval":
            if self.lifecycle_state != "submitted_pending_approval":
                errors.append("wait action requires submitted_pending_approval state")
            if self.safe_to_execute_code is True:
                errors.append("wait action must not mark code execution safe")
            if blocked_actions_now != REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS:
                errors.append("wait action must keep all pre-access compute actions blocked")
        if self.action == "fix_access_evidence":
            if self.lifecycle_state != "invalid":
                errors.append("fix action requires invalid lifecycle state")
            if self.safe_to_execute_code is True:
                errors.append("fix action must not mark code execution safe")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_nullish_text(value: Any) -> bool:
    return not isinstance(value, str) or value.strip().lower() in NULLISH_EVIDENCE_VALUES


def _unfilled_placeholder_errors(field: str, value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    if UNFILLED_PLACEHOLDER_RE.search(value):
        return [f"{field} contains an unfilled placeholder"]
    return []


def _unsafe_metadata_text_errors(field: str, value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    errors: list[str] = []
    if LOCAL_PATH_RE.search(value) or COMPLETED_FILE_REF_RE.search(value):
        errors.append(f"{field} must not contain local paths or completed-file references")
    if TOKEN_LIKE_RE.search(value):
        errors.append(f"{field} must not contain credentials or token-like strings")
    return errors


def _string_values(values: Any) -> tuple[str, ...]:
    if not isinstance(values, tuple | list | set):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)
