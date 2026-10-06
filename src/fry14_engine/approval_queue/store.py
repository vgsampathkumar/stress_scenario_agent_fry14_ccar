"""Approval Queue Store: persists and reads back `AgentProposal` rows. See
schemas/013_agent_governance.sql.
"""

from __future__ import annotations

import json
from datetime import datetime

import duckdb

from fry14_engine.approval_queue.models import AgentProposal, ProposalStatus, ProposalType

_COLUMNS = [
    "proposal_id",
    "proposing_agent",
    "session_id",
    "requested_by",
    "proposal_type",
    "payload",
    "evidence",
    "rationale",
    "required_permission",
    "requires_four_eyes",
    "status",
    "decided_by",
    "decision_reason",
    "created_at",
    "decided_at",
]

_INSERT_SQL = f"""
    INSERT INTO agent_governance.agent_proposal ({", ".join(_COLUMNS)})
    VALUES ({", ".join("?" for _ in _COLUMNS)})
"""


class ApprovalQueueStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write(self, proposal: AgentProposal) -> None:
        self._connection.execute(
            _INSERT_SQL,
            [
                proposal.proposal_id,
                proposal.proposing_agent,
                proposal.session_id,
                proposal.requested_by,
                str(proposal.proposal_type),
                json.dumps(proposal.payload),
                json.dumps(proposal.evidence),
                proposal.rationale,
                str(proposal.required_permission),
                proposal.requires_four_eyes,
                str(proposal.status),
                proposal.decided_by,
                proposal.decision_reason,
                proposal.created_at,
                proposal.decided_at,
            ],
        )

    def read(self, proposal_id: str) -> AgentProposal | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM agent_governance.agent_proposal "
            "WHERE proposal_id = ?",
            [proposal_id],
        ).fetchone()
        if row is None:
            return None
        return self._to_model(row)

    def read_pending(self) -> list[AgentProposal]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM agent_governance.agent_proposal "
            "WHERE status = 'PENDING' ORDER BY created_at"
        ).fetchall()
        return [self._to_model(row) for row in rows]

    def update_decision(
        self,
        proposal_id: str,
        status: ProposalStatus,
        decided_by: str,
        decision_reason: str | None,
        decided_at: datetime,
    ) -> None:
        self._connection.execute(
            "UPDATE agent_governance.agent_proposal "
            "SET status = ?, decided_by = ?, decision_reason = ?, decided_at = ? "
            "WHERE proposal_id = ?",
            [str(status), decided_by, decision_reason, decided_at, proposal_id],
        )

    def expire_pending_older_than(self, cutoff: datetime) -> int:
        rows = self._connection.execute(
            "UPDATE agent_governance.agent_proposal SET status = 'EXPIRED' "
            "WHERE status = 'PENDING' AND created_at < ? "
            "RETURNING proposal_id",
            [cutoff],
        ).fetchall()
        return len(rows)

    @staticmethod
    def _to_model(row: tuple) -> AgentProposal:
        data = dict(zip(_COLUMNS, row, strict=True))
        data["proposal_type"] = ProposalType(data["proposal_type"])
        data["payload"] = json.loads(data["payload"])
        data["evidence"] = json.loads(data["evidence"]) if data["evidence"] else []
        data["status"] = ProposalStatus(data["status"])
        return AgentProposal(**data)
