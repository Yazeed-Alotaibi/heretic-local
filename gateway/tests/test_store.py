import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from heretic_gateway import store as storage
from heretic_gateway.store import RevisionConflict, Store, normalize


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path)
    yield instance
    instance.close()


def test_records_revisions_and_canonical_markdown(store):
    record = store.save_record("# Summary\nDetails\n", kind="checkpoint")
    path = store.root / "records" / f"{record['id']}.md"
    assert path.read_text(encoding="utf-8").endswith(record["content"])
    assert store.get_record(record["id"]) == record
    updated = store.save_record("new", kind="checkpoint", record_id=record["id"], expected_revision=1)
    assert updated["revision"] == 2
    assert updated["created_at"] == record["created_at"]
    with pytest.raises(RevisionConflict):
        store.save_record("lost", record_id=record["id"], expected_revision=1)
    with pytest.raises(RevisionConflict):
        store.delete_record(record["id"], expected_revision=1)
    store.reload()
    assert store.get_record(record["id"]) == updated
    store.delete_record(record["id"], expected_revision=2)
    assert not path.exists()
    assert store.search("new") == []


def test_validation_scope_and_arabic(store):
    project = store.create_project("التجربة")
    store.save_record("أَلِف إِبداع آمال ٱختبار ـ café", kind="preference")
    selected = store.save_record("اختبار مشروع", scope=project["id"])
    other = store.create_project("Other")
    store.save_record("اختبار سري", scope=other["id"])
    assert len(store.search("اختبار", project["id"])) == 2
    assert len(store.search("اختبار")) == 1
    assert len(store.profile(project["id"])) == 1
    assert store.list_records(project["id"]) == [selected]
    assert store.search('" OR * (', project["id"]) == []
    assert normalize("ة هى") == "ة هى"
    assert normalize("أإآٱ") == "اااا"
    assert store.search("الف ابداع امال اختبار CAFÉ")
    for content in ("", " ", None):
        with pytest.raises(ValueError):
            store.save_record(content)
    with pytest.raises(ValueError):
        store.save_record("bad", scope="../../secret")
    with pytest.raises(ValueError):
        store.search("test", limit=0)


def test_atomic_reload_keeps_working_index_on_invalid_file(store):
    record = store.save_record("working")
    (store.root / "records" / "invalid.json").write_text('{"schema_version":2}', encoding="utf-8")
    version = store.version
    with pytest.raises(ValueError):
        store.reload()
    assert store.version == version
    assert store.search("working") == [record]
    (store.root / "records" / "invalid.json").unlink()
    path = store.root / "records" / f"{record['id']}.json"
    manual = dict(record, content="manually edited", revision=2)
    path.write_text(json.dumps(manual), encoding="utf-8")
    assert store.search("working")
    assert not store.search("manually")
    store.reload()
    assert store.search("manually") == [manual]


def test_concurrent_stale_revision_has_one_winner(store):
    record = store.save_record("initial")
    second = Store(store.root)
    def update(instance):
        try:
            return instance.save_record("updated", record_id=record["id"], expected_revision=1)
        except RevisionConflict:
            return None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(update, [store, second]))
        assert sum(result is not None for result in results) == 1
        store.reload()
        assert store.get_record(record["id"])["revision"] == 2
    finally:
        second.close()


def test_replace_retry_and_locked_failure_preserve_record(store, monkeypatch):
    record = store.save_record("old")
    original = os.replace
    attempts = []
    def transient(source, destination):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("locked")
        original(source, destination)
    monkeypatch.setattr(storage.os, "replace", transient)
    updated = store.save_record("new", record_id=record["id"], expected_revision=1)
    assert len(attempts) == 3
    assert updated["revision"] == 2
    def locked(*args):
        raise PermissionError("locked")
    monkeypatch.setattr(storage.os, "replace", locked)
    with pytest.raises(PermissionError, match="locked"):
        store.save_record("lost", record_id=record["id"], expected_revision=2)
    assert store.get_record(record["id"]) == updated
    assert not list((store.root / "records").glob("*.tmp"))


def test_replace_retry_rechecks_manual_changes(store, monkeypatch):
    record = store.save_record("original")
    path = store.root / "records" / f"{record['id']}.json"
    def raced(*args):
        path.write_text(json.dumps(dict(record, revision=2, content="outside edit")), encoding="utf-8")
        raise PermissionError("locked")
    monkeypatch.setattr(storage.os, "replace", raced)
    with pytest.raises(RevisionConflict):
        store.save_record("overwrite", record_id=record["id"], expected_revision=1)
    assert json.loads(path.read_text(encoding="utf-8"))["content"] == "outside edit"


def test_receipt_survives_restart_and_later_updates(store):
    original = store.save_record("first", request_id="stable-request")
    updated = store.save_record("second", record_id=original["id"], expected_revision=1)
    reopened = Store(store.root)
    try:
        assert reopened.save_record("first", request_id="stable-request") == original
        assert reopened.get_record(original["id"]) == updated
        with pytest.raises(ValueError, match="different content"):
            reopened.save_record("different", request_id="stable-request")
    finally:
        reopened.close()


def test_crash_between_canonical_write_and_receipt_recovers(store, monkeypatch):
    def fail(item):
        raise RuntimeError("simulated receipt failure")
    monkeypatch.setattr(store, "_receipt", fail)
    with pytest.raises(RuntimeError, match="receipt failure"):
        store.save_record("recover", request_id="interrupted")
    reopened = Store(store.root)
    try:
        recovered = reopened.save_record("recover", request_id="interrupted")
        assert reopened.list_records() == [recovered]
        assert recovered["revision"] == 1
    finally:
        reopened.close()


def test_receipt_expires_after_24_hours(store):
    original = store.save_record("first", request_id="expiring")
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    path = store.root / "records" / f"{original['id']}.json"
    original["request_created_at"] = old
    path.write_text(json.dumps(original), encoding="utf-8")
    with store._operational:
        store._operational.execute("UPDATE receipts SET created_at=?", (old,))
    store.reload()
    new = store.save_record("first", request_id="expiring")
    assert new["id"] != original["id"]


def test_archive_bindings_privacy_and_restart(store):
    project = store.create_project("Project")
    record = store.save_record("existing", scope=project["id"])
    store.bind_conversation("chat", project["id"])
    store.archive_project(project["id"])
    assert store.list_projects() == []
    assert store.list_records(project["id"]) == [record]
    assert store.bind_conversation("chat", project["id"], False)["memory_enabled"] is False
    assert store.bind_conversation("chat", project["id"], True)["memory_enabled"] is True
    with pytest.raises(ValueError):
        store.bind_conversation("new", project["id"])
    with pytest.raises(ValueError):
        store.bind_conversation("chat", "global")
    with pytest.raises(ValueError):
        store.save_record("new", scope=project["id"])
    revised = store.save_record("edited existing", scope=project["id"], record_id=record["id"], expected_revision=1)
    assert revised["revision"] == 2
    store.mark_private("chat")
    assert store.bind_conversation("chat", project["id"], True)["private_context"]
    assert store.conversation("chat")["memory_enabled"]
    assert store.bind_conversation("legacy", has_history=True)["private_context"]
    assert store.conversation("legacy")["memory_enabled"]
    reopened = Store(store.root)
    try:
        assert reopened.conversation("chat")["private_context"]
        assert reopened.conversation("chat")["project"] == project["id"]
        reopened.delete_conversation("chat")
        assert reopened.conversation("chat") is None
    finally:
        reopened.close()


def test_export_allowlist(store):
    record = store.save_record("approved", request_id="not-exported")
    checkpoint = store.save_record("# Checkpoint", kind="checkpoint")
    store.create_project("Approved")
    (store.root / "token.txt").write_text("secret", encoding="utf-8")
    directory = store.root / "knowledge"
    approved = directory / "approved"
    approved.mkdir(parents=True)
    (approved / "document.json").write_text(json.dumps({"scope": "global"}), encoding="utf-8")
    (approved / "original.md").write_text("document", encoding="utf-8")
    (approved / "token.txt").write_text("secret", encoding="utf-8")
    private = directory / "private"
    private.mkdir()
    (private / "document.json").write_text(json.dumps({"scope": "session:private"}), encoding="utf-8")
    (private / "original.txt").write_text("private text", encoding="utf-8")
    store.bind_conversation("private chat", memory_enabled=False)
    with zipfile.ZipFile(store.export()) as archive:
        names = archive.namelist()
        assert "knowledge/approved/original.md" in names
        assert "knowledge/approved/token.txt" not in names
        assert not any(name.startswith("knowledge/private/") for name in names)
        assert f"records/{checkpoint['id']}.md" in names
        assert all(name.startswith(("records/", "projects/", "knowledge/")) for name in names)
        exported = json.loads(archive.read(f"records/{record['id']}.json"))
        assert "request_id" not in exported
        assert "operational.sqlite" not in names


def test_natural_question_recall_and_forget_derived_receipts(store):
    original = store.save_record("Favourite beverage is coffee", request_id="source")
    note = store.save_record("Derived coffee summary", kind="note", derived_from=[original["id"]], request_id="derived")
    checkpoint = store.save_record("Checkpoint summary", kind="checkpoint", derived_from=[note["id"]])
    with pytest.raises(ValueError, match="Cyclic"):
        store.save_record("cyclic", record_id=original["id"], derived_from=[checkpoint["id"]])
    assert original in store.search("What is my favourite beverage?")
    assert original in store.search("Tell me about coffee preferences")
    with pytest.raises(ValueError, match="unknown source"):
        store.save_record("bad", derived_from=["00000000-0000-0000-0000-000000000000"])
    store.delete_record(original["id"])
    assert store.list_records() == []
    assert not store._record_path(note["id"], "note").exists()
    assert not store._record_path(checkpoint["id"], "checkpoint").exists()
    assert store._operational.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0
    new = store.save_record("Favourite beverage is coffee", request_id="source")
    assert new["id"] != original["id"]


def test_prepared_reload_does_not_change_live_index(store):
    record = store.save_record("before")
    path = store.root / "records" / f"{record['id']}.json"
    path.write_text(json.dumps(dict(record, content="after")), encoding="utf-8")
    snapshot = store.prepare_reload()
    assert store.search("before")
    assert not store.search("after")
    store.install_reload(snapshot)
    assert not store.search("before")
    assert store.search("after")
