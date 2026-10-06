"""Orchestrator (C16): sequences a complete pipeline run — ingest one or
more channels, validate + hash PII + route to governed/quarantine,
calculate risk metrics, aggregate, and update the catalog — all under a
single `pipeline_run_id`, so the whole run can be reconstructed end-to-end
from the audit log alone. Retries transient failures at each stage. See
02-design-document.md §3.11.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import duckdb

from fry14_engine.aggregation.gateway import AggregationGateway
from fry14_engine.audit.logger import AuditLogger
from fry14_engine.catalog.gateway import DEFAULT_OWNER, CatalogGateway
from fry14_engine.common.enums import AuditEventType
from fry14_engine.common.ids import new_pipeline_run_id
from fry14_engine.common.metadata import MetadataStamper
from fry14_engine.contracts.models import DataContract
from fry14_engine.contracts.validation_gateway import ValidationGateway
from fry14_engine.ingestion.gateway import IngestionGateway
from fry14_engine.orchestrator.models import ChannelSource, PipelineRunReport
from fry14_engine.orchestrator.retry import retry_on_transient_error
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.risk_engine.gateway import RiskCalculationGateway


class Orchestrator:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        contract: DataContract,
        pii_hashing_service: PIIHashingService,
        data_product_id: str,
        max_retries: int = 3,
        owner: str = DEFAULT_OWNER,
    ) -> None:
        self._contract = contract
        self._data_product_id = data_product_id
        self._max_retries = max_retries
        self._owner = owner

        self._audit_logger = AuditLogger(connection)
        self._ingestion_gateway = IngestionGateway(connection)
        self._validation_gateway = ValidationGateway(connection, pii_hashing_service)
        self._governed_store = GovernedStore(connection)
        self._risk_calculation_gateway = RiskCalculationGateway(connection)
        self._aggregation_gateway = AggregationGateway(connection)
        self._catalog_gateway = CatalogGateway(connection)

    def run(self, channels: list[ChannelSource], reporting_period: str) -> PipelineRunReport:
        pipeline_run_id = new_pipeline_run_id()
        report = PipelineRunReport(
            pipeline_run_id=pipeline_run_id, data_product_id=self._data_product_id
        )

        for channel in channels:
            stamper = MetadataStamper(
                pipeline_run_id=pipeline_run_id,
                source_entity_code=channel.source_entity_code,
                source_system_of_record=channel.source_system_of_record,
                ingestion_channel=channel.adapter.channel,
            )
            result = self._retry(
                lambda a=channel.adapter, s=stamper: self._ingestion_gateway.run(a, s)
            )
            report.ingestion_results.append(result)
            self._audit_logger.log(
                AuditEventType.INGESTION,
                pipeline_run_id=pipeline_run_id,
                detail={
                    "source_system_of_record": channel.source_system_of_record,
                    "ingestion_channel": str(channel.adapter.channel),
                    "records_landed": result.records_landed,
                    "parse_errors": len(result.parse_errors),
                },
            )

        all_stamped = [
            record
            for ingestion_result in report.ingestion_results
            for record in ingestion_result.stamped_records
        ]

        validation = self._retry(
            lambda: self._validation_gateway.run(all_stamped, self._contract, pipeline_run_id)
        )
        report.validation = validation
        self._audit_logger.log(
            AuditEventType.VALIDATION,
            pipeline_run_id=pipeline_run_id,
            detail={
                "contract_id": self._contract.contract_id,
                "contract_version": self._contract.version,
                "total_count": validation.total_count,
                "governed_count": validation.governed_count,
                "quarantined_count": validation.quarantined_count,
                "reason_code_counts": validation.reason_code_counts,
            },
        )
        self._audit_logger.log(
            AuditEventType.PII_HASH,
            pipeline_run_id=pipeline_run_id,
            detail={"records_hashed": validation.total_count},
        )

        governed_records = self._governed_store.read_by_pipeline_run_id(pipeline_run_id)
        risk_calculation = self._retry(
            lambda: self._risk_calculation_gateway.run(
                governed_records, reporting_period, pipeline_run_id
            )
        )
        report.risk_calculation = risk_calculation
        self._audit_logger.log(
            AuditEventType.CALCULATION,
            pipeline_run_id=pipeline_run_id,
            detail={
                "reporting_period": reporting_period,
                "metrics_computed": len(risk_calculation.metrics),
                "calculation_exceptions": len(risk_calculation.exceptions),
                "regulatory_parameter_version": risk_calculation.regulatory_parameter_version,
            },
        )

        aggregation = self._retry(lambda: self._aggregation_gateway.run(pipeline_run_id))
        report.aggregation = aggregation
        self._audit_logger.log(
            AuditEventType.AGGREGATION,
            pipeline_run_id=pipeline_run_id,
            detail={
                "input_metric_count": aggregation.input_metric_count,
                "aggregate_rows": len(aggregation.aggregates),
                "schema_version": aggregation.schema_version,
            },
        )

        catalog = self._retry(
            lambda: self._catalog_gateway.update_after_run(
                data_product_id=self._data_product_id,
                pipeline_run_id=pipeline_run_id,
                dq_pass_percentage=validation.dq_pass_rate * 100,
                run_completed_at=datetime.now(UTC),
                output_schema_version=aggregation.schema_version,
                output_schema_effective_date=date.today(),
                owner=self._owner,
            )
        )
        report.catalog = catalog
        self._audit_logger.log(
            AuditEventType.CATALOG_UPDATE,
            pipeline_run_id=pipeline_run_id,
            detail={
                "data_product_id": self._data_product_id,
                "health_score": str(catalog.entry.health_score),
                "sla_status": str(catalog.entry.sla_status),
            },
        )

        self._audit_logger.log(
            AuditEventType.ORCHESTRATION,
            pipeline_run_id=pipeline_run_id,
            detail={"status": "COMPLETED", "channel_count": len(channels)},
        )

        return report

    def _retry(self, fn):
        return retry_on_transient_error(
            fn, max_attempts=self._max_retries, retryable_exceptions=(duckdb.Error,)
        )
