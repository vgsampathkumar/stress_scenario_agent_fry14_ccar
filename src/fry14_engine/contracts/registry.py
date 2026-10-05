"""Contract Registry (C4): loads versioned `DataContract` documents from
declarative YAML config, and — if given a DB connection — mirrors them into
`contracts.data_contract` / `contracts.active_contract` for durable,
queryable lineage. The YAML files under `config/contracts/<contract_id>/`
are the authored source of truth; the DB tables are a published mirror, not
a second place to hand-edit contracts. See 02-design-document.md §3.2.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import yaml

from fry14_engine.contracts.models import DataContract


def _semver_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


class ContractNotFoundError(Exception):
    pass


class ContractRegistry:
    def __init__(
        self,
        contracts_dir: Path | str,
        connection: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        self._contracts_dir = Path(contracts_dir)
        self._connection = connection

    def list_versions(self, contract_id: str) -> list[str]:
        contract_dir = self._contracts_dir / contract_id
        if not contract_dir.is_dir():
            return []
        versions = [path.stem for path in contract_dir.glob("*.yaml")]
        return sorted(versions, key=_semver_key)

    def load(self, contract_id: str, version: str) -> DataContract:
        path = self._contracts_dir / contract_id / f"{version}.yaml"
        if not path.is_file():
            raise ContractNotFoundError(f"No contract file at {path}")
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        contract = DataContract.model_validate(document)
        if self._connection is not None:
            self._publish(contract)
        return contract

    def get_active(self, contract_id: str) -> DataContract:
        versions = self.list_versions(contract_id)
        if not versions:
            raise ContractNotFoundError(f"No contract versions found for '{contract_id}'")
        return self.load(contract_id, versions[-1])

    def _publish(self, contract: DataContract) -> None:
        definition_json = json.dumps(contract.model_dump(mode="json"))
        self._connection.execute(
            """
            INSERT INTO contracts.data_contract
                (contract_id, version, effective_date, definition)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (contract_id, version) DO UPDATE SET
                effective_date = excluded.effective_date,
                definition = excluded.definition
            """,
            [contract.contract_id, contract.version, contract.effective_date, definition_json],
        )
        self._connection.execute(
            """
            INSERT INTO contracts.active_contract (contract_id, active_version)
            VALUES (?, ?)
            ON CONFLICT (contract_id) DO UPDATE SET
                active_version = excluded.active_version,
                activated_at = now()
            """,
            [contract.contract_id, contract.version],
        )
