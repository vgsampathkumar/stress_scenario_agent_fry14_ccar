"""Reference Data Store (C9): loads versioned regulatory parameter sets
from the database into an in-memory `RegulatoryParameterSet`, mirroring
`ContractRegistry`'s list_versions/load/get_active pattern. See
02-design-document.md §3.4.
"""

from __future__ import annotations

import duckdb

from fry14_engine.reference_data.models import ReferenceDataNotFoundError, RegulatoryParameterSet


def _semver_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


class ReferenceDataStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def list_versions(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT version FROM reference.regulatory_parameter_set"
        ).fetchall()
        return sorted((row[0] for row in rows), key=_semver_key)

    def load(self, version: str) -> RegulatoryParameterSet:
        effective_date_row = self._connection.execute(
            "SELECT effective_date FROM reference.regulatory_parameter_set WHERE version = ?",
            [version],
        ).fetchone()
        if effective_date_row is None:
            raise ReferenceDataNotFoundError(f"No regulatory parameter set version {version!r}")

        ccf_rows = self._connection.execute(
            "SELECT asset_class, commitment_type, ccf FROM reference.credit_conversion_factor "
            "WHERE parameter_version = ?",
            [version],
        ).fetchall()
        risk_weight_rows = self._connection.execute(
            "SELECT asset_class, risk_weight FROM reference.risk_weight "
            "WHERE parameter_version = ?",
            [version],
        ).fetchall()

        return RegulatoryParameterSet(
            version=version,
            effective_date=effective_date_row[0],
            ccf_by_key={(row[0], row[1]): row[2] for row in ccf_rows},
            risk_weight_by_asset_class={row[0]: row[1] for row in risk_weight_rows},
        )

    def get_active(self) -> RegulatoryParameterSet:
        versions = self.list_versions()
        if not versions:
            raise ReferenceDataNotFoundError("No regulatory parameter sets found")
        return self.load(versions[-1])
