"""AG-2 Data Quality Triage Agent (C19): calls the deterministic
`get_quarantine_summary` tool, has the LLM reason over the resulting
clusters to form root-cause hypotheses (each must cite the cluster
statistics that support it), and turns each hypothesis into an
`AgentProposal` — it never edits data directly. After approval, reprocesses
the affected quarantine records, carrying `original_quarantine_id` lineage
into the new governed rows. See 02-design-document.md §3.17 and
requirements.md §3.2 (AG-2).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict

from fry14_engine.agent_runtime.models import LlmClient, LlmCompletionRequest, SessionStatus
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.approval_queue.models import (
    AgentProposal,
    ProposalDraft,
    ProposalStatus,
    ProposalType,
)
from fry14_engine.approval_queue.service import ApprovalQueueService
from fry14_engine.common.enums import AgentId, Permission, RemediationStatus, RoleName
from fry14_engine.common.ids import ClockFn, new_pipeline_run_id, new_record_id, utc_now
from fry14_engine.contracts.models import DataContract
from fry14_engine.contracts.validation_engine import ValidationEngine
from fry14_engine.ingestion.models import RawLoanRecord
from fry14_engine.mcp_server.models import ToolContext
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.pii.governed_models import GovernedLoanRecord
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.policy.models import PolicyOutcome
from fry14_engine.quarantine.store import QuarantineStore

_SYSTEM_PROMPT = (
    "You are AG-2, a Data Quality Triage specialist. You are given clustered "
    "quarantine statistics, never raw records. For each cluster worth acting "
    "on, propose exactly one remediation — a REMEDIATION_RULE (a deterministic "
    "field-level fix), a CONTRACT_AMENDMENT (loosen or correct a contract "
    "rule), or a SOURCE_TICKET (an upstream fix, no in-pipeline remediation "
    "possible). Every hypothesis's `citation` must quote the cluster's own "
    "counts/rates — never invent a statistic not present in the input."
)


class ProposalTypeChoice(StrEnum):
    REMEDIATION_RULE = "REMEDIATION_RULE"
    CONTRACT_AMENDMENT = "CONTRACT_AMENDMENT"
    SOURCE_TICKET = "SOURCE_TICKET"


class RemediationAction(StrEnum):
    SET_DEFAULT = "SET_DEFAULT"
    ABS_VALUE = "ABS_VALUE"


class RootCauseHypothesis(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason_code: str
    cluster_key: str
    root_cause: str
    citation: str
    proposal_type: ProposalTypeChoice
    rationale: str
    remediation_field: str | None = None
    remediation_action: RemediationAction | None = None
    remediation_value: Any | None = None


class RootCauseHypothesisList(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypotheses: list[RootCauseHypothesis] = []


class NoDataChangeWithoutApprovalError(Exception):
    """Raised by `reprocess_after_approval` if the proposal isn't an
    APPROVED REMEDIATION_RULE — reprocessing a quarantine record is a data
    change, and no data change happens without a recorded approval decision
    (requirements.md §3.4)."""


class DataQualityTriageAgent:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        mcp_server: McpToolServer,
        agent_runtime: AgentRuntime,
        clock: ClockFn = utc_now,
    ) -> None:
        self._connection = connection
        self._quarantine_store = QuarantineStore(connection)
        self._governed_store = GovernedStore(connection)
        self._approval_queue_service = ApprovalQueueService(connection)
        self._server = mcp_server
        self._runtime = agent_runtime
        self._clock = clock

    def run(
        self, on_behalf_of: str, user_role: RoleName, llm_client: LlmClient
    ) -> list[AgentProposal]:
        session = self._runtime.start_session(
            AgentId.AG2_DATA_QUALITY_TRIAGE,
            on_behalf_of,
            user_role,
            llm_client.model_id,
            llm_client.prompt_template_version,
        )
        ctx = ToolContext(
            AgentId.AG2_DATA_QUALITY_TRIAGE, user_role, session.session_id, on_behalf_of
        )

        summary_result = self._server.get_quarantine_summary(ctx)
        session = self._runtime.record_tool_call(session)
        if summary_result.decision.outcome != PolicyOutcome.ALLOW:
            self._runtime.finish(session, status=SessionStatus.ERROR)
            return []
        summary = summary_result.result
        session = self._runtime.record_step(session, {"clusters_seen": len(summary.clusters)})

        request = LlmCompletionRequest(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=(
                f"total_open_records={summary.total_open_records}\n"
                + "\n".join(
                    f"cluster: reason_code={c.reason_code} "
                    f"source_system={c.source_system_of_record} "
                    f"rejection_date={c.rejection_date} record_count={c.record_count} "
                    f"null_field_rates={c.null_field_rates}"
                    for c in summary.clusters
                )
            ),
        )
        session, hypothesis_list = self._runtime.complete_structured(
            session, llm_client, request, RootCauseHypothesisList
        )

        proposals: list[AgentProposal] = []
        for hypothesis in hypothesis_list.hypotheses:
            draft = self._draft_for(hypothesis)
            tool = (
                self._server.propose_contract_change
                if hypothesis.proposal_type == ProposalTypeChoice.CONTRACT_AMENDMENT
                else self._server.propose_remediation
            )
            propose_result = tool(ctx, draft)
            session = self._runtime.record_tool_call(session)
            if propose_result.decision.proposal_id:
                proposal = self._approval_queue_service.read(propose_result.decision.proposal_id)
                if proposal is not None:
                    proposals.append(proposal)

        self._runtime.finish(session)
        return proposals

    def reprocess_after_approval(
        self, proposal: AgentProposal, contract: DataContract
    ) -> tuple[int, int]:
        """Returns (reprocessed_count, still_quarantined_count). Only ever
        reads/writes once `proposal.status == APPROVED` — enforced here,
        not trusted from the caller, since this is the one place actual
        data changes."""
        if (
            proposal.status != ProposalStatus.APPROVED
            or proposal.proposal_type != ProposalType.REMEDIATION_RULE
        ):
            raise NoDataChangeWithoutApprovalError(
                f"Proposal {proposal.proposal_id!r} is not an approved REMEDIATION_RULE "
                f"(status={proposal.status}, type={proposal.proposal_type})"
            )

        reason_code = proposal.payload["reason_code"]
        field = proposal.payload["field"]
        action = RemediationAction(proposal.payload["action"])
        value = proposal.payload.get("value")

        engine = ValidationEngine(contract)
        reprocessing_run_id = new_pipeline_run_id()
        reprocessed_count = 0
        still_quarantined_count = 0

        for record in self._quarantine_store.read_open_by_reason_code(reason_code):
            corrected = dict(record.original_record)
            if action == RemediationAction.SET_DEFAULT:
                corrected[field] = value
            elif action == RemediationAction.ABS_VALUE and corrected.get(field) is not None:
                # `original_record` was JSON-serialized at quarantine time
                # (`model_dump(mode="json")`), so a Decimal field like
                # outstanding_balance is a numeric *string* here (e.g.
                # "-50000.0"), not a Decimal — `abs()` on it directly
                # raises TypeError. Use Decimal to get a real absolute
                # value regardless of the string's sign, then hand back a
                # string so RawLoanRecord's own Decimal coercion applies.
                corrected[field] = str(abs(Decimal(str(corrected[field]))))

            raw_record = RawLoanRecord.model_validate(corrected)
            outcome = engine.validate(raw_record)
            if not outcome.is_valid:
                still_quarantined_count += 1
                continue

            self._governed_store.write(
                [
                    GovernedLoanRecord(
                        governed_id=new_record_id(),
                        loan_id=raw_record.loan_id,
                        borrower_key_hash=corrected.get("borrower_tax_id"),
                        borrower_name_hash=corrected.get("borrower_legal_name"),
                        borrower_address_hash=corrected.get("borrower_address"),
                        counterparty_id=raw_record.counterparty_id,
                        asset_class=raw_record.asset_class,
                        internal_credit_risk_grade=raw_record.internal_credit_risk_grade,
                        credit_score=raw_record.credit_score,
                        outstanding_balance=raw_record.outstanding_balance,
                        unadvanced_commitment=raw_record.unadvanced_commitment,
                        maturity_date=raw_record.maturity_date,
                        probability_of_default=raw_record.probability_of_default,
                        loss_given_default=raw_record.loss_given_default,
                        portfolio_segment=raw_record.portfolio_segment,
                        pipeline_run_id=reprocessing_run_id,
                        contract_version=contract.version,
                        ingestion_timestamp=self._clock(),
                        original_quarantine_id=record.quarantine_id,
                    )
                ]
            )
            self._quarantine_store.update_remediation_status(
                record.quarantine_id, RemediationStatus.RESOLVED
            )
            reprocessed_count += 1

        return reprocessed_count, still_quarantined_count

    @staticmethod
    def _draft_for(hypothesis: RootCauseHypothesis) -> ProposalDraft:
        if hypothesis.proposal_type == ProposalTypeChoice.CONTRACT_AMENDMENT:
            return ProposalDraft(
                proposal_type=ProposalType.CONTRACT_AMENDMENT,
                payload={
                    "reason_code": hypothesis.reason_code,
                    "field": hypothesis.remediation_field,
                },
                rationale=hypothesis.rationale,
                evidence=[hypothesis.citation],
                required_permission=Permission.APPROVE_CONTRACT_CHANGE,
            )
        if hypothesis.proposal_type == ProposalTypeChoice.SOURCE_TICKET:
            return ProposalDraft(
                proposal_type=ProposalType.SOURCE_TICKET,
                payload={
                    "reason_code": hypothesis.reason_code,
                    "root_cause": hypothesis.root_cause,
                },
                rationale=hypothesis.rationale,
                evidence=[hypothesis.citation],
                required_permission=Permission.APPROVE_REMEDIATION,
            )
        return ProposalDraft(
            proposal_type=ProposalType.REMEDIATION_RULE,
            payload={
                "reason_code": hypothesis.reason_code,
                "field": hypothesis.remediation_field,
                "action": str(hypothesis.remediation_action),
                "value": hypothesis.remediation_value,
            },
            rationale=hypothesis.rationale,
            evidence=[hypothesis.citation],
            required_permission=Permission.APPROVE_REMEDIATION,
        )
