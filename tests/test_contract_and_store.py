import sqlite3
from pathlib import Path
from typing import Any

from openharnx.kernel.contract import validate_contract
from openharnx.store import Store


def _valid() -> dict[str, Any]:
    return {
        "title": "t",
        "mode": "bugfix",
        "change_summary": "s",
        "obligations": [{"id": "a", "kind": "acceptance", "mandatory": True, "command": ["true"]}],
    }


def test_valid_contract_has_no_errors() -> None:
    assert validate_contract(_valid()) == []


def test_each_missing_field_is_named() -> None:
    for field in ("title", "change_summary", "mode"):
        raw = _valid()
        del raw[field]
        assert any(e.startswith(field) for e in validate_contract(raw)), field


def test_bugfix_needs_a_mandatory_acceptance_obligation() -> None:
    raw = _valid()
    raw["obligations"][0]["mandatory"] = False
    assert any("mandatory acceptance" in e for e in validate_contract(raw))


def test_duplicate_ids_and_bad_command_rejected() -> None:
    raw = _valid()
    raw["obligations"].append({"id": "a", "kind": "regression", "mandatory": False, "command": []})
    errors = validate_contract(raw)
    assert any("duplicate" in e for e in errors)
    assert any("command" in e for e in errors)


def test_store_appends_reads_and_is_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path)
    a = store.append("thing", {"x": 1}, now="t0", idempotency_key="k")
    b = store.append("thing", {"x": 2}, now="t1", idempotency_key="k")
    assert a.revision_id == b.revision_id
    store.append("thing", {"x": 3}, now="t2")
    latest = store.latest("thing")
    assert latest is not None and latest.body == {"x": 3}
    assert store.check() == []


def test_store_detects_tampered_record(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.append("thing", {"x": 1}, now="t0")
    store.close()
    db = sqlite3.connect(tmp_path / "store.sqlite")
    db.execute("UPDATE revisions SET body = '{\"x\": 99}'")
    db.commit()
    db.close()
    assert any("digest" in p for p in Store(tmp_path).check())


def test_blobs_are_content_addressed(tmp_path: Path) -> None:
    store = Store(tmp_path)
    d = store.put_blob(b"hello")
    assert store.put_blob(b"hello") == d
    assert store.blob_path(d).read_bytes() == b"hello"
