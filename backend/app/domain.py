"""Domain enums and transition rules for the Mulyankan workflow.

The database still stores most workflow values as strings for compatibility
with existing deployments, but every API boundary and state mutation should
use these enums and the transition policy below.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Python 3.10-compatible string enum base."""


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    REVISION_REQUIRED = "revision_required"
    SUBMITTED = "submitted"
    EVALUATING = "evaluating"
    HUMAN_REVIEW = "human_review"
    ADJUDICATION = "adjudication"
    COMMITTEE_REVIEW = "committee_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ERROR = "error"


class AssignmentRole(StrEnum):
    TECHNICAL = "technical"
    FINANCIAL = "financial"


class AssignmentStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    CONFLICT_DECLARED = "conflict_declared"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReviewRecommendation(StrEnum):
    APPROVED = "approved"
    REVISION = "revision"
    REJECTED = "rejected"


class CommitteeDecisionValue(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUIRED = "revision_required"


class ModelRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


PROPOSAL_TRANSITIONS: dict[ProposalStatus, set[ProposalStatus]] = {
    ProposalStatus.DRAFT: {
        ProposalStatus.SUBMITTED,
        ProposalStatus.WITHDRAWN,
    },
    ProposalStatus.REVISION_REQUIRED: {
        ProposalStatus.SUBMITTED,
        ProposalStatus.WITHDRAWN,
    },
    ProposalStatus.SUBMITTED: {
        ProposalStatus.EVALUATING,
        ProposalStatus.ERROR,
        ProposalStatus.WITHDRAWN,
    },
    ProposalStatus.EVALUATING: {
        ProposalStatus.HUMAN_REVIEW,
        ProposalStatus.REVISION_REQUIRED,
        ProposalStatus.REJECTED,
        ProposalStatus.ERROR,
    },
    ProposalStatus.HUMAN_REVIEW: {
        ProposalStatus.ADJUDICATION,
        ProposalStatus.COMMITTEE_REVIEW,
        ProposalStatus.REVISION_REQUIRED,
        ProposalStatus.REJECTED,
    },
    ProposalStatus.ADJUDICATION: {
        ProposalStatus.COMMITTEE_REVIEW,
        ProposalStatus.REVISION_REQUIRED,
        ProposalStatus.REJECTED,
    },
    ProposalStatus.COMMITTEE_REVIEW: {
        ProposalStatus.APPROVED,
        ProposalStatus.REJECTED,
        ProposalStatus.REVISION_REQUIRED,
    },
    ProposalStatus.ERROR: {
        ProposalStatus.SUBMITTED,
        ProposalStatus.EVALUATING,
        ProposalStatus.REVISION_REQUIRED,
    },
    ProposalStatus.APPROVED: set(),
    ProposalStatus.REJECTED: set(),
    ProposalStatus.WITHDRAWN: set(),
}


def parse_proposal_status(value: str | ProposalStatus) -> ProposalStatus:
    if isinstance(value, ProposalStatus):
        return value
    return ProposalStatus(value)


def proposal_transition_allowed(
    current: str | ProposalStatus,
    target: str | ProposalStatus,
    *,
    administrative_override: bool = False,
) -> bool:
    """Return whether a proposal state transition is allowed.

    Administrative overrides may move between any known states, but still
    cannot introduce arbitrary unrecognised values.
    """

    current_status = parse_proposal_status(current)
    target_status = parse_proposal_status(target)
    if current_status == target_status:
        return True
    if administrative_override:
        return True
    return target_status in PROPOSAL_TRANSITIONS[current_status]
