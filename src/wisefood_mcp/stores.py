"""Proposals: the unit of human approval.

A proposal is one candidate source and everything the assistant has worked
out about it — what it is, where it lives, which licence the evidence
suggests, how it ranks, and what integrating it would involve. It moves
through a small state machine, and the only transition into ``approved`` is
made by a person in the console. The write tools check that state and refuse
otherwise; that check is the wall this whole design leans on, so it lives
here, in one function, and nowhere else.

The store is a protocol rather than a class so the two hosts can back it
differently: FoodScholar keeps proposals in its Postgres; the standalone
``wisefood-mcp`` process talks to FoodScholar over the gateway; tests use the
in-memory one below.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from wisefood_mcp.registry import ApprovalRequired, ToolError

#: The states, in the order a healthy proposal visits them. ``rejected`` and
#: ``failed`` are terminal; ``imported`` is the good ending.
STATUSES = ("researching", "proposed", "approved", "running", "imported", "rejected", "failed")

#: What the catalog can take. Recipe collections are named so the assistant
#: can *propose* one; integrating it is Phase 5.
KINDS = ("guide", "article", "textbook", "fctable", "rcollection")

#: Exactly the catalog's ``LicenseId`` enum values that matter for ingestion.
#: Anything the evidence tool proposes must be one of these or ``None``.
LICENCES = (
    "CC-BY-4.0", "CC-BY-SA-4.0", "CCBY", "CCBYSA", "CCBYNC", "CCBYNCSA", "CCBYNCND",
    "CC0", "public-domain", "MIT", "Apache-2.0", "GPL-3.0",
    "Proprietary", "unspecified-oa", "other-oa", "publisher-specific-oa",
)

#: Licences under which the *content* may be ingested. Everything else may be
#: registered as a pointer (title, URL, publisher) but not copied in.
CONTENT_PERMITTED = frozenset({
    "CC-BY-4.0", "CC-BY-SA-4.0", "CCBY", "CCBYSA", "CCBYNC", "CCBYNCSA",
    "CC0", "public-domain", "MIT", "Apache-2.0", "GPL-3.0",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Proposal:
    id: str
    kind: str
    title: str
    source_url: Optional[str] = None
    status: str = "researching"
    country: Optional[str] = None
    language: Optional[str] = None
    population_group: Optional[str] = None
    licence: Optional[str] = None
    licence_confidence: Optional[float] = None
    licence_evidence: List[Dict[str, Any]] = field(default_factory=list)
    licence_override_reason: Optional[str] = None
    proposed_rank: Optional[float] = None
    expert_rank: Optional[int] = None
    rationale: Optional[str] = None
    plan: List[str] = field(default_factory=list)
    """The integration steps the assistant intends, in order, as text."""
    metadata: Dict[str, Any] = field(default_factory=dict)
    backlog_id: Optional[str] = None
    session_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    result: Dict[str, Any] = field(default_factory=dict)
    """What integrating it produced: urns, artifact ids, job ids."""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ProposalStore(Protocol):
    def create(self, proposal: Proposal) -> Proposal: ...
    def get(self, proposal_id: str) -> Optional[Proposal]: ...
    def update(self, proposal_id: str, **changes: Any) -> Proposal: ...
    def list(self, *, session_id: Optional[str] = None, status: Optional[str] = None,
             limit: int = 100) -> List[Proposal]: ...


class InMemoryProposalStore:
    """For tests and for a standalone run with nothing behind it."""

    def __init__(self) -> None:
        self._rows: Dict[str, Proposal] = {}

    def create(self, proposal: Proposal) -> Proposal:
        self._rows[proposal.id] = proposal
        return proposal

    def get(self, proposal_id: str) -> Optional[Proposal]:
        return self._rows.get(proposal_id)

    def update(self, proposal_id: str, **changes: Any) -> Proposal:
        row = self._rows[proposal_id]
        for key, value in changes.items():
            setattr(row, key, value)
        row.updated_at = _now()
        return row

    def list(self, *, session_id: Optional[str] = None, status: Optional[str] = None,
             limit: int = 100) -> List[Proposal]:
        rows = [
            r for r in self._rows.values()
            if (session_id is None or r.session_id == session_id)
            and (status is None or r.status == status)
        ]
        rows.sort(key=lambda r: (r.expert_rank if r.expert_rank is not None else 10**6,
                                 -(r.proposed_rank or 0), r.created_at))
        return rows[:limit]


def new_proposal_id() -> str:
    return uuid.uuid4().hex[:12]


def require_approved(store: ProposalStore, proposal_id: str) -> Proposal:
    """The wall. Every write tool calls this first.

    Raises unless the proposal exists and a person has approved it. Also
    refuses an approved proposal whose licence does not permit content
    ingestion and has no recorded override — approval of a pointer-only
    registration is still approval, so the tool that runs next has to check
    ``content_permitted`` before copying anything in.
    """
    if not store:
        raise ToolError("no proposal store is configured; writes are impossible")
    row = store.get(proposal_id)
    if row is None:
        raise ApprovalRequired(f"no proposal {proposal_id!r}")
    if row.status != "approved":
        raise ApprovalRequired(
            f"proposal {proposal_id!r} is {row.status!r}, not approved",
            status=row.status,
        )
    return row


def content_permitted(proposal: Proposal) -> bool:
    """Whether the licence — or a recorded override — allows copying content."""
    if proposal.licence_override_reason:
        return True
    return proposal.licence in CONTENT_PERMITTED


#: Statuses a curator can approve from. ``failed`` is here so a run that did
#: not finish can be tried again: the proposal's status follows its last run,
#: so a failure left it neither ``approved`` (integrate refused it) nor
#: approvable (this refused it), with no way out of either. Re-approving
#: rather than letting `integrate` accept ``failed`` directly keeps the human
#: gate on the retry and records who asked for it, and when.
APPROVABLE_FROM = ("proposed", "researching", "failed")


def approve(store: ProposalStore, proposal_id: str, *, actor: str,
            override_reason: Optional[str] = None) -> Proposal:
    """A person approves. Not a tool: the model cannot reach this.

    A proposal with no determinable licence cannot be approved without a
    reason — that rule is enforced here, on the console's path, so the
    assistant's confidence in a guess never becomes a fact by default.

    Approving a ``failed`` proposal is a retry, and is recorded as a fresh
    approval: ``approved_by`` and ``approved_at`` become whoever asked for the
    retry, because that is who is answerable for the second attempt.
    """
    row = store.get(proposal_id)
    if row is None:
        raise ToolError(f"no proposal {proposal_id!r}")
    if row.status not in APPROVABLE_FROM:
        raise ToolError(f"cannot approve a proposal that is {row.status!r}", status=row.status)
    if not row.licence and not override_reason:
        raise ToolError(
            "this proposal has no determinable licence; approving it needs a "
            "written reason, which is recorded with the approval",
            code="licence_unknown",
        )
    changes: Dict[str, Any] = {
        "status": "approved", "approved_by": actor, "approved_at": _now(),
    }
    if override_reason:
        changes["licence_override_reason"] = override_reason
    return store.update(proposal_id, **changes)
