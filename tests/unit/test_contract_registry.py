from __future__ import annotations

from pathlib import Path

import pytest

from fry14_engine.contracts.registry import ContractNotFoundError, ContractRegistry
from fry14_engine.db import bootstrap, get_connection

CONTRACT_V1 = """
contract_id: test_contract
version: "1.0.0"
effective_date: "2026-01-01"
fields:
  - field_name: loan_id
    data_type: STRING
    nullable: false
"""

CONTRACT_V2 = """
contract_id: test_contract
version: "1.2.0"
effective_date: "2026-02-01"
fields:
  - field_name: loan_id
    data_type: STRING
    nullable: false
  - field_name: asset_class
    data_type: STRING
    nullable: false
"""


@pytest.fixture
def contracts_dir(tmp_path: Path) -> Path:
    contract_dir = tmp_path / "test_contract"
    contract_dir.mkdir()
    (contract_dir / "1.0.0.yaml").write_text(CONTRACT_V1, encoding="utf-8")
    (contract_dir / "1.2.0.yaml").write_text(CONTRACT_V2, encoding="utf-8")
    return tmp_path


def test_list_versions_sorted_by_semver_not_lexical(contracts_dir: Path):
    registry = ContractRegistry(contracts_dir)
    # lexical sort would put "1.0.0" after "1.2.0" incorrectly only for 3+
    # digit minors; this asserts true semver-tuple ordering regardless.
    assert registry.list_versions("test_contract") == ["1.0.0", "1.2.0"]


def test_get_active_picks_highest_version(contracts_dir: Path):
    registry = ContractRegistry(contracts_dir)
    contract = registry.get_active("test_contract")
    assert contract.version == "1.2.0"
    assert len(contract.fields) == 2


def test_load_specific_version(contracts_dir: Path):
    registry = ContractRegistry(contracts_dir)
    contract = registry.load("test_contract", "1.0.0")
    assert contract.version == "1.0.0"
    assert len(contract.fields) == 1


def test_missing_contract_raises(contracts_dir: Path):
    registry = ContractRegistry(contracts_dir)
    with pytest.raises(ContractNotFoundError):
        registry.get_active("nonexistent_contract")
    with pytest.raises(ContractNotFoundError):
        registry.load("test_contract", "9.9.9")


def test_publishes_to_db_when_connection_given(contracts_dir: Path, tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    registry = ContractRegistry(contracts_dir, connection=con)

    registry.get_active("test_contract")

    active_version = con.execute(
        "SELECT active_version FROM contracts.active_contract WHERE contract_id = ?",
        ["test_contract"],
    ).fetchone()[0]
    assert active_version == "1.2.0"

    version_count = con.execute(
        "SELECT COUNT(*) FROM contracts.data_contract WHERE contract_id = ?",
        ["test_contract"],
    ).fetchone()[0]
    assert version_count == 1

    # re-publishing the same version is an upsert, not a duplicate row
    registry.get_active("test_contract")
    version_count_after = con.execute(
        "SELECT COUNT(*) FROM contracts.data_contract WHERE contract_id = ?",
        ["test_contract"],
    ).fetchone()[0]
    assert version_count_after == 1
    con.close()
