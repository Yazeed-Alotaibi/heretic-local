"""Canonical local memory files and a disposable SQLite search index."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


class RevisionConflict(ValueError):
    """A canonical record changed since the caller last read it."""


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_ARABIC_MARKS = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
_STOPWORDS = frozenset("a an and are as at be by can do does for from how i in is it me my of on or tell that the this to what when where which who why with you your عن على في من الى إلى ما ماذا كيف هل هو هي انا أنا و يا لي او أو".split())


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return _ARABIC_MARKS.sub("", text).translate(str.maketrans("أإآٱ", "اااا"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("ID must be a UUID")
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError("ID must be a UUID") from error
    if parsed != value:
        raise ValueError("ID must be a canonical UUID")
    return value


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed


def _decode(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise ValueError(f"Missing JSON frontmatter: {path.name}")
        metadata, content = text[4:].split("\n---\n", 1)
        item = json.loads(metadata)
        if not isinstance(item, dict):
            raise ValueError("Markdown metadata must be an object")
        item["content"] = content
        return item
    return json.loads(text)


def _encode(item: dict, markdown: bool = False) -> str:
    if markdown:
        metadata = {key: value for key, value in item.items() if key != "content"}
        return "---\n" + json.dumps(metadata, ensure_ascii=False, indent=2) + "\n---\n" + item["content"]
    return json.dumps(item, ensure_ascii=False, indent=2) + "\n"


def _derived_order(records: dict) -> list[str]:
    remaining = {identifier: set(item.get("derived_from", [])) for identifier, item in records.items()}
    if any(source_id not in remaining for sources in remaining.values() for source_id in sources):
        raise ValueError("Record references unknown source memory")
    order = []
    while remaining:
        ready = sorted(identifier for identifier, sources in remaining.items() if not sources)
        if not ready:
            raise ValueError("Cyclic derived record references")
        order.extend(ready)
        for identifier in ready:
            del remaining[identifier]
        for sources in remaining.values():
            sources.difference_update(ready)
    return order


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("records", "projects", "exports"):
            (self.root / name).mkdir(exist_ok=True)
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(str(self.root), threading.RLock())
        self._index = sqlite3.connect(":memory:", check_same_thread=False)
        self._index.execute("CREATE VIRTUAL TABLE memory USING fts5(id UNINDEXED, scope UNINDEXED, content)")
        self._operational = sqlite3.connect(self.root / "operational.sqlite", timeout=1, check_same_thread=False)
        self._operational.row_factory = sqlite3.Row
        self._operational.executescript(
            "CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, project TEXT NOT NULL, "
            "memory_enabled INTEGER NOT NULL, has_history INTEGER NOT NULL, private_context INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
            "result TEXT NOT NULL, created_at TEXT NOT NULL);"
        )
        self._records: dict[str, dict] = {}
        self._projects: dict[str, dict] = {}
        self.version = 0
        try:
            self.reload()
        except Exception:
            self.close()
            raise

    @contextmanager
    def _serialized(self):
        with self._lock:
            # OS locks also serialize writers using separate Store instances/processes.
            with (self.root / ".write.lock").open("a+b") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                deadline = time.monotonic() + 1
                while True:
                    try:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.025)
                try:
                    yield
                finally:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _validate(self, item: dict, project: bool = False) -> None:
        if not isinstance(item, dict) or type(item.get("schema_version")) is not int or item["schema_version"] != 1:
            raise ValueError("Unsupported canonical schema")
        _identifier(item.get("id"))
        for key in ("created_at", "updated_at"):
            _timestamp(item.get(key))
        if type(item.get("revision")) is not int or item["revision"] < 1:
            raise ValueError("Revision must be a positive integer")
        if project:
            if not isinstance(item.get("name"), str) or not item["name"].strip():
                raise ValueError("Project name cannot be empty")
            if type(item.get("archived")) is not bool:
                raise ValueError("Project archived must be boolean")
        else:
            for key in ("scope", "content", "kind", "source"):
                if not isinstance(item.get(key), str) or not item[key].strip():
                    raise ValueError(f"Record {key} cannot be empty")
            if item["scope"] != "global":
                _identifier(item["scope"])
            if "request_id" in item:
                if not isinstance(item["request_id"], str) or not item["request_id"]:
                    raise ValueError("Invalid request ID")
                if not isinstance(item.get("request_fingerprint"), str):
                    raise ValueError("Missing request fingerprint")
                _timestamp(item.get("request_created_at"))
            if "derived_from" in item:
                if not isinstance(item["derived_from"], list) or len(item["derived_from"]) > 100:
                    raise ValueError("Invalid derived record references")
                for identifier in item["derived_from"]:
                    _identifier(identifier)
                    if identifier == item["id"]:
                        raise ValueError("Record cannot derive from itself")

    def _read_all(self) -> tuple[dict[str, dict], dict[str, dict]]:
        collections = []
        for folder in ("projects", "records"):
            collection = {}
            for path in sorted((self.root / folder).iterdir()):
                if path.suffix not in ((".json", ".md") if folder == "records" else (".json",)):
                    continue
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Canonical files must be regular local files")
                item = _decode(path)
                self._validate(item, folder == "projects")
                if path.stem != item["id"]:
                    raise ValueError(f"Canonical filename does not match ID: {path.name}")
                if item["id"] in collection:
                    raise ValueError("Duplicate canonical record ID")
                collection[item["id"]] = item
            collections.append(collection)
        projects, records = collections
        for item in records.values():
            if item["scope"] != "global" and item["scope"] not in projects:
                raise ValueError("Record references an unknown project")
        _derived_order(records)
        return records, projects

    def _swap(self, records: dict, projects: dict) -> None:
        with self._index:
            self._index.execute("DELETE FROM memory")
            self._index.executemany("INSERT INTO memory(id,scope,content) VALUES (?,?,?)", (
                (item["id"], item["scope"], normalize(item["content"])) for item in records.values()
            ))
        self._records, self._projects = records, projects
        self.version += 1

    def reload(self) -> None:
        with self._serialized():
            self.install_reload(self.prepare_reload())

    def prepare_reload(self) -> tuple[dict, dict]:
        with self._lock:
            return self._read_all()

    def install_reload(self, snapshot: tuple[dict, dict]) -> None:
        with self._lock:
            records, projects = snapshot
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            with self._operational:
                self._operational.execute("DELETE FROM receipts WHERE julianday(created_at) < julianday(?)",
                                          (cutoff.isoformat(),))
                for item in records.values():
                    if item.get("request_id") and _timestamp(item["request_created_at"]) >= cutoff:
                        self._operational.execute("INSERT OR IGNORE INTO receipts VALUES (?,?,?,?)", (
                            item["request_id"], item["request_fingerprint"], json.dumps(item), item["request_created_at"]
                        ))
            self._swap(records, projects)

    def _scope(self, scope: str, active: bool = False) -> None:
        if scope == "global":
            return
        _identifier(scope)
        if scope not in self._projects:
            raise ValueError("Unknown project")
        if active and self._projects[scope]["archived"]:
            raise ValueError("Project is archived")

    def _atomic(self, path: Path, item: dict, previous: dict | None) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4()}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(_encode(item, path.suffix == ".md"))
                handle.flush()
                os.fsync(handle.fileno())
            deadline = time.monotonic() + 1
            while True:
                current = _decode(path) if path.exists() else None
                if current != previous:
                    raise RevisionConflict("Canonical file changed before replacement")
                try:
                    os.replace(temporary, path)
                    return
                except PermissionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.025)
        finally:
            temporary.unlink(missing_ok=True)

    def list_records(self, scope: str = "global") -> list[dict]:
        with self._lock:
            self._scope(scope)
            return [dict(item) for item in sorted(self._records.values(), key=lambda row: (row["created_at"], row["id"]))
                    if item["scope"] == scope]

    def get_record(self, record_id: str) -> dict:
        with self._lock:
            return dict(self._records[_identifier(record_id)])

    def _record_path(self, identifier: str, kind: str = "fact") -> Path:
        markdown = self.root / "records" / f"{identifier}.md"
        regular = self.root / "records" / f"{identifier}.json"
        if markdown.exists():
            return markdown
        if regular.exists():
            return regular
        return markdown if kind in ("note", "checkpoint") else regular

    def save_record(self, content: str, scope: str = "global", kind: str = "fact", source: str = "user",
                    record_id: str | None = None, expected_revision: int | None = None,
                    request_id: str | None = None, derived_from: list[str] | None = None) -> dict:
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("Expected revision must be a positive integer")
        if request_id is not None and (not isinstance(request_id, str) or not request_id or len(request_id) > 256):
            raise ValueError("Request ID must contain 1 to 256 characters")
        fingerprint = hashlib.sha256(json.dumps([content, scope, kind, source, record_id, expected_revision, derived_from],
                                               ensure_ascii=False).encode()).hexdigest()
        with self._serialized():
            records, projects = self._read_all()
            # Recover a canonical write whose operational receipt was interrupted.
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            if request_id:
                receipt = self._operational.execute("SELECT * FROM receipts WHERE id=?", (request_id,)).fetchone()
                if receipt and _timestamp(receipt["created_at"]) >= cutoff:
                    if receipt["fingerprint"] != fingerprint:
                        raise ValueError("Request ID was already used with different content")
                    return json.loads(receipt["result"])
                for saved in records.values():
                    if saved.get("request_id") == request_id and _timestamp(saved["request_created_at"]) >= cutoff:
                        if saved["request_fingerprint"] != fingerprint:
                            raise ValueError("Request ID was already used with different content")
                        self._receipt(saved)
                        self._swap(records, projects)
                        return dict(saved)
            identifier = _identifier(record_id) if record_id else str(uuid.uuid4())
            previous = records.get(identifier)
            if record_id and previous is None:
                raise KeyError(record_id)
            old_projects = self._projects
            self._projects = projects
            try:
                self._scope(scope, active=previous is None or previous["scope"] != scope)
            finally:
                self._projects = old_projects
            if expected_revision is not None and (previous is None or previous["revision"] != expected_revision):
                raise RevisionConflict("Record revision does not match")
            now = _now()
            item = {"schema_version": 1, "id": identifier, "scope": scope, "content": content,
                    "kind": kind, "source": source, "revision": previous["revision"] + 1 if previous else 1,
                    "created_at": previous["created_at"] if previous else now, "updated_at": now}
            if derived_from is not None:
                item["derived_from"] = list(derived_from) if isinstance(derived_from, list) else derived_from
            elif previous and "derived_from" in previous:
                item["derived_from"] = previous["derived_from"]
            if request_id:
                item.update(request_id=request_id, request_fingerprint=fingerprint, request_created_at=now)
            self._validate(item)
            _derived_order(dict(records, **{identifier: item}))
            self._atomic(self._record_path(identifier, kind), item, previous)
            records[identifier] = item
            self._swap(records, projects)
            if request_id:
                self._receipt(item)
            return dict(item)

    def _receipt(self, item: dict) -> None:
        with self._operational:
            self._operational.execute("INSERT OR REPLACE INTO receipts VALUES (?,?,?,?)", (
                item["request_id"], item["request_fingerprint"], json.dumps(item), item["request_created_at"]
            ))

    def delete_record(self, record_id: str, expected_revision: int | None = None) -> None:
        identifier = _identifier(record_id)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("Expected revision must be a positive integer")
        with self._serialized():
            records, projects = self._read_all()
            item = records[identifier]
            if expected_revision is not None and item["revision"] != expected_revision:
                raise RevisionConflict("Record revision does not match")
            removed = {identifier}
            while True:
                dependents = {key for key, value in records.items() if removed.intersection(value.get("derived_from", []))}
                if dependents <= removed:
                    break
                removed.update(dependents)
            # Forget durable replay snapshots before deleting canonical records. A failed
            # unlink still surfaces, while no receipt can resurrect forgotten content.
            with self._operational:
                for receipt in self._operational.execute("SELECT id,result FROM receipts").fetchall():
                    if json.loads(receipt["result"])["id"] in removed:
                        self._operational.execute("DELETE FROM receipts WHERE id=?", (receipt["id"],))
            for removed_id in reversed(_derived_order(records)):
                if removed_id not in removed:
                    continue
                self._record_path(removed_id).unlink()
                del records[removed_id]
            self._swap(records, projects)

    def search(self, query: str, scope: str = "global", limit: int = 8) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Search limit must be between 1 and 100")
        if not isinstance(query, str):
            raise ValueError("Query must be text")
        terms = list(dict.fromkeys(term for term in re.findall(r"\w+", normalize(query[:2000]), re.UNICODE)
                                   if term not in _STOPWORDS))[:32]
        if not terms:
            return []
        expression = " OR ".join('"' + term + '"' for term in terms)
        with self._lock:
            self._scope(scope)
            rows = self._index.execute(
                "SELECT id FROM memory WHERE memory MATCH ? AND scope IN ('global',?) ORDER BY rank, id LIMIT ?",
                (expression, scope, limit),
            ).fetchall()
            return [dict(self._records[row[0]]) for row in rows]

    def profile(self, scope: str = "global") -> list[dict]:
        with self._lock:
            self._scope(scope)
            return [dict(item) for item in sorted(self._records.values(), key=lambda row: (row["created_at"], row["id"]))
                    if item["scope"] in ("global", scope) and item["kind"] == "preference"]

    def create_project(self, name: str) -> dict:
        now = _now()
        item = {"schema_version": 1, "id": str(uuid.uuid4()), "name": name, "archived": False,
                "revision": 1, "created_at": now, "updated_at": now}
        self._validate(item, True)
        with self._serialized():
            records, projects = self._read_all()
            self._atomic(self.root / "projects" / f"{item['id']}.json", item, None)
            projects[item["id"]] = item
            self._swap(records, projects)
        return dict(item)

    def list_projects(self) -> list[dict]:
        with self._lock:
            return [dict(item) for item in sorted(self._projects.values(), key=lambda row: (row["created_at"], row["id"]))
                    if not item["archived"]]

    def archive_project(self, project_id: str) -> dict:
        identifier = _identifier(project_id)
        with self._serialized():
            records, projects = self._read_all()
            previous = projects[identifier]
            item = dict(previous, archived=True, revision=previous["revision"] + 1, updated_at=_now())
            self._atomic(self.root / "projects" / f"{identifier}.json", item, previous)
            projects[identifier] = item
            self._swap(records, projects)
            return dict(item)

    def bind_conversation(self, conversation_id: str, project: str = "global", memory_enabled: bool = True,
                          has_history: bool = False) -> dict:
        if not isinstance(conversation_id, str) or not conversation_id or len(conversation_id) > 256:
            raise ValueError("Invalid conversation ID")
        if type(memory_enabled) is not bool or type(has_history) is not bool:
            raise ValueError("Conversation flags must be boolean")
        with self._serialized():
            _, projects = self._read_all()
            existing = self.conversation(conversation_id)
            if existing and existing["project"] != project:
                raise ValueError("Conversation project cannot change")
            if project != "global" and (project not in projects or (projects[project]["archived"] and
                    (not existing or existing["project"] != project))):
                raise ValueError("Unknown or archived project")
            private_context = existing["private_context"] if existing else has_history
            if existing:
                has_history = has_history or existing["has_history"]
            with self._operational:
                self._operational.execute("INSERT OR REPLACE INTO conversations VALUES (?,?,?,?,?)", (
                    conversation_id, project, int(memory_enabled), int(has_history), int(private_context)
                ))
            self.version += 1
            return self.conversation(conversation_id)

    def conversation(self, conversation_id: str) -> dict | None:
        with self._lock:
            row = self._operational.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if row is None:
                return None
            return {"id": row["id"], "project": row["project"], "memory_enabled": bool(row["memory_enabled"]),
                    "has_history": bool(row["has_history"]), "private_context": bool(row["private_context"])}

    def mark_private(self, conversation_id: str) -> None:
        with self._serialized(), self._operational:
            current = self.conversation(conversation_id)
            if current:
                self._operational.execute("UPDATE conversations SET private_context=1 WHERE id=?",
                                          (conversation_id,))
            else:
                if not isinstance(conversation_id, str) or not conversation_id or len(conversation_id) > 256:
                    raise ValueError("Invalid conversation ID")
                self._operational.execute("INSERT INTO conversations VALUES (?, 'global', 1, 0, 1)",
                                          (conversation_id,))
            self.version += 1

    def delete_conversation(self, conversation_id: str) -> None:
        with self._serialized(), self._operational:
            self._operational.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
            self.version += 1

    def export(self) -> Path:
        with self._serialized():
            records, projects = self._read_all()
            output = self.root / "exports" / f"heretic-{uuid.uuid4()}.zip"
            try:
                with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
                    for folder, items in (("records", records), ("projects", projects)):
                        for identifier, item in sorted(items.items()):
                            approved = {key: value for key, value in item.items() if not key.startswith("request_")}
                            markdown = folder == "records" and self._record_path(identifier).suffix == ".md"
                            extension = ".md" if markdown else ".json"
                            archive.writestr(f"{folder}/{identifier}{extension}", _encode(approved, markdown))
                    directory = self.root / "knowledge"
                    if directory.exists() and not directory.is_symlink():
                        for document in sorted(directory.iterdir()):
                            if document.is_symlink() or not document.is_dir() or document.name.startswith("."):
                                continue
                            metadata = document / "document.json"
                            if not metadata.is_file() or metadata.is_symlink():
                                continue
                            item = json.loads(metadata.read_text(encoding="utf-8"))
                            if item.get("scope") != "global" and item.get("scope") not in projects:
                                continue
                            for path in sorted(document.iterdir()):
                                if path.is_file() and not path.is_symlink() and (
                                    path.name == "document.json" or path.name in
                                    ("original.md", "original.txt", "original.pdf", "original.docx")
                                ):
                                    archive.write(path, path.relative_to(self.root).as_posix())
                return output
            except Exception:
                output.unlink(missing_ok=True)
                raise

    def close(self) -> None:
        with self._lock:
            self._index.close()
            self._operational.close()
