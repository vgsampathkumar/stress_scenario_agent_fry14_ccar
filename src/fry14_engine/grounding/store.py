"""Grounded Narrative Store: persists and reads back `GroundedNarrative`
rows. See schemas/013_agent_governance.sql.
"""

from __future__ import annotations

import duckdb

from fry14_engine.grounding.models import (
    GroundedNarrative,
    GroundingStatus,
    NarrativeApprovalStatus,
)

_COLUMNS = [
    "narrative_id",
    "session_id",
    "pipeline_run_id",
    "scenario_run_id",
    "template_text",
    "rendered_text",
    "grounding_status",
    "approval_status",
    "released_by",
    "released_at",
]

_INSERT_SQL = f"""
    INSERT INTO agent_governance.grounded_narrative ({", ".join(_COLUMNS)})
    VALUES ({", ".join("?" for _ in _COLUMNS)})
"""


class GroundedNarrativeStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write(self, narrative: GroundedNarrative) -> None:
        self._connection.execute(
            _INSERT_SQL,
            [
                narrative.narrative_id,
                narrative.session_id,
                narrative.pipeline_run_id,
                narrative.scenario_run_id,
                narrative.template_text,
                narrative.rendered_text,
                str(narrative.grounding_status),
                str(narrative.approval_status),
                narrative.released_by,
                narrative.released_at,
            ],
        )

    def update_approval(
        self, narrative_id: str, approval_status: NarrativeApprovalStatus, released_by: str | None
    ) -> None:
        self._connection.execute(
            "UPDATE agent_governance.grounded_narrative "
            "SET approval_status = ?, released_by = ?, "
            "released_at = CASE WHEN ? = 'APPROVED' THEN CURRENT_TIMESTAMP ELSE released_at END "
            "WHERE narrative_id = ?",
            [str(approval_status), released_by, str(approval_status), narrative_id],
        )

    def read(self, narrative_id: str) -> GroundedNarrative | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM agent_governance.grounded_narrative "
            "WHERE narrative_id = ?",
            [narrative_id],
        ).fetchone()
        if row is None:
            return None
        data = dict(zip(_COLUMNS, row, strict=True))
        data["grounding_status"] = GroundingStatus(data["grounding_status"])
        data["approval_status"] = NarrativeApprovalStatus(data["approval_status"])
        return GroundedNarrative(**data)
