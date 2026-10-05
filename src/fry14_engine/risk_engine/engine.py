"""Risk Metric Engine (C10): computes EAD/EL/RWA for every governed loan
record for a reporting period, using an already-loaded `RegulatoryParameterSet`
(no DB access here — mirrors `ValidationEngine` checking against an
already-loaded `DataContract`). Missing PD/LGD, a missing maturity date, or
an asset class absent from the reference tables routes to a calculation
exception, never a silent default or a crash — preserving the "never
fail-stop" principle at this stage too. See 02-design-document.md §3.5 and
the exception reason code catalog (§6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from fry14_engine.common.ids import new_record_id
from fry14_engine.pii.governed_models import GovernedLoanRecord
from fry14_engine.reference_data.models import ReferenceDataNotFoundError, RegulatoryParameterSet
from fry14_engine.risk_engine.calculator import calculate_ead, calculate_el, calculate_rwa
from fry14_engine.risk_engine.maturity import maturity_bucket
from fry14_engine.risk_engine.models import CalculationException, LoanRiskMetrics

CALC_ENGINE_VERSION = "1.0.0"
DEFAULT_COMMITMENT_TYPE = "STANDARD"
_CENTS = Decimal("0.01")


def _round_to_cents(value: Decimal) -> Decimal:
    """EAD/EL/RWA are currency amounts; round to cents explicitly here so
    the in-memory `LoanRiskMetrics` value matches exactly what
    `metrics.loan_risk_metrics` (a `DECIMAL(18, 2)` column) will actually
    store — otherwise the DB silently truncates precision the Python
    object still thinks it has, and totals computed in Python vs. SQL
    would silently disagree."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass
class RiskCalculationRunResult:
    pipeline_run_id: str
    reporting_period: str
    regulatory_parameter_version: str
    total_count: int
    metrics: list[LoanRiskMetrics] = field(default_factory=list)
    exceptions: list[CalculationException] = field(default_factory=list)


class RiskMetricEngine:
    def __init__(self, parameter_set: RegulatoryParameterSet) -> None:
        self._parameter_set = parameter_set

    def run(
        self,
        governed_records: list[GovernedLoanRecord],
        reporting_period: str,
        pipeline_run_id: str,
    ) -> RiskCalculationRunResult:
        metrics: list[LoanRiskMetrics] = []
        exceptions: list[CalculationException] = []

        for record in governed_records:
            outcome = self._calculate_one(record, reporting_period, pipeline_run_id)
            if isinstance(outcome, CalculationException):
                exceptions.append(outcome)
            else:
                metrics.append(outcome)

        return RiskCalculationRunResult(
            pipeline_run_id=pipeline_run_id,
            reporting_period=reporting_period,
            regulatory_parameter_version=self._parameter_set.version,
            total_count=len(governed_records),
            metrics=metrics,
            exceptions=exceptions,
        )

    def _calculate_one(
        self,
        record: GovernedLoanRecord,
        reporting_period: str,
        pipeline_run_id: str,
    ) -> LoanRiskMetrics | CalculationException:
        if record.probability_of_default is None or record.loss_given_default is None:
            return self._exception(
                record,
                pipeline_run_id,
                "CALC_MISSING_PD_LGD",
                "probability_of_default or loss_given_default is missing",
            )
        if record.maturity_date is None:
            return self._exception(
                record, pipeline_run_id, "CALC_MISSING_MATURITY_DATE", "maturity_date is missing"
            )

        try:
            ccf = self._parameter_set.get_ccf(record.asset_class, DEFAULT_COMMITMENT_TYPE)
            risk_weight = self._parameter_set.get_risk_weight(record.asset_class)
        except ReferenceDataNotFoundError as exc:
            return self._exception(record, pipeline_run_id, "UNKNOWN_ASSET_CLASS", str(exc))

        unadvanced_commitment = record.unadvanced_commitment or Decimal("0")
        # EAD is rounded first, then used as-rounded to derive EL/RWA — so
        # EL/RWA reconcile against the EAD figure actually reported, not an
        # unrounded intermediate no one else ever sees.
        ead = _round_to_cents(calculate_ead(record.outstanding_balance, unadvanced_commitment, ccf))
        el = _round_to_cents(
            calculate_el(record.probability_of_default, record.loss_given_default, ead)
        )
        rwa = _round_to_cents(calculate_rwa(ead, risk_weight))
        bucket = maturity_bucket(reporting_period, record.maturity_date)

        return LoanRiskMetrics(
            loan_id=record.loan_id,
            reporting_period=reporting_period,
            ead=ead,
            el=el,
            rwa=rwa,
            asset_class=record.asset_class,
            portfolio_segment=record.portfolio_segment or "UNSPECIFIED",
            credit_rating_grade=record.internal_credit_risk_grade,
            remaining_maturity_bucket=bucket,
            calc_engine_version=CALC_ENGINE_VERSION,
            regulatory_parameter_version=self._parameter_set.version,
            pipeline_run_id=pipeline_run_id,
        )

    @staticmethod
    def _exception(
        record: GovernedLoanRecord, pipeline_run_id: str, reason_code: str, detail: str
    ) -> CalculationException:
        return CalculationException(
            exception_id=new_record_id(),
            loan_id=record.loan_id,
            pipeline_run_id=pipeline_run_id,
            reason_code=reason_code,
            detail=detail,
        )
