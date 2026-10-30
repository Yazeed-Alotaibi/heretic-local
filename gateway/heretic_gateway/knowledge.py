"""Local canonical documents and bounded lexical retrieval."""
import ctypes
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .store import normalize

MAX_BYTES = 25 * 1024 * 1024
MAX_CHARS = 5_000_000
PDF_TIMEOUT = 60
MEMORY_LIMIT = 512 * 1024 * 1024


def _chunks(text):
    """Keep text intact; prefer paragraph, line, then word boundaries near the limit."""
    start = 0
    while start < len(text):
        end = min(start + 2000, len(text))
        if end < len(text):
            for separator in ('\n\n', '\n', ' '):
                boundary = text.rfind(separator, start + 1800, end)
                if boundary >= 0:
                    end = boundary + len(separator)
                    break
        yield text[start:end]
        start = end


def _scope(scope):
    if scope == "global":
        return
    if not isinstance(scope, str):
        raise ValueError("Invalid knowledge scope")
    try:
        if str(uuid.UUID(scope)) != scope:
            raise ValueError("Invalid knowledge scope")
    except (ValueError, AttributeError) as error:
        raise ValueError("Invalid knowledge scope") from error


def _windows_job(process):
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("per_process", ctypes.c_int64), ("per_job", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("minimum", ctypes.c_size_t),
                    ("maximum", ctypes.c_size_t), ("active", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ("read_ops", "write_ops", "other_ops", "read", "write", "other")]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                    ("peak_job", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = Extended()
    limits.basic.flags = 0x2000 | 0x100  # kill on close and hard process memory cap
    limits.process_memory = MEMORY_LIMIT
    try:
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
            raise ctypes.WinError(ctypes.get_last_error())
        resume = ctypes.WinDLL("ntdll").NtResumeProcess
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = ctypes.c_long
        if resume(wintypes.HANDLE(int(process._handle))) != 0:
            raise RuntimeError("Unable to resume isolated PDF worker")
    except BaseException:
        kernel.CloseHandle(job)
        raise
    return lambda: kernel.CloseHandle(job)


def _pdf_pages(path, output):
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
               "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = 0x4 | subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True

        def cap():
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
        options["preexec_fn"] = cap
    process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("pdf_worker.py")),
                                str(path), str(output)], **options)
    close_job = None
    try:
        if os.name == "nt":
            close_job = _windows_job(process)
        try:
            process.wait(timeout=PDF_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("PDF extraction exceeded 60 seconds") from exc
        if process.returncode or not output.exists() or output.stat().st_size > 40 * 1024 * 1024:
            raise ValueError("PDF extraction failed or exceeded resource limits")
        result = json.loads(output.read_text(encoding="utf-8"))
        if "error" in result:
            raise ValueError(result["error"])
        return result["pages"]
    finally:
        if close_job:
            close_job()  # kills all remaining processes in the job
        if process.poll() is None:
            if os.name != "nt":
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        process.wait()


class Knowledge:
    def __init__(self, root: Path):
        self.root = Path(root) / "knowledge"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._documents = {}
        self.reload()

    def reload(self):
        with self._lock:
            self.install_reload(self.prepare_reload())

    def prepare_reload(self):
        with self._lock:
            documents = {}
            for folder in self.root.iterdir():
                if folder.name.startswith("."):
                    continue
                if not re.fullmatch(r"[0-9a-f]{32}", folder.name) or folder.is_symlink() or not folder.is_dir():
                    raise ValueError("Invalid canonical knowledge folder")
                metadata = folder / "document.json"
                if metadata.is_symlink() or not metadata.is_file() or metadata.stat().st_size > 40 * 1024 * 1024:
                    raise ValueError("Invalid canonical document metadata")
                document = json.loads(metadata.read_text(encoding="utf-8"))
                self._validate(document, folder)
                documents[folder.name] = document
            return documents

    def install_reload(self, snapshot):
        with self._lock:
            index = self._build_index(snapshot)
            self._swap(snapshot, index)

    @staticmethod
    def _build_index(documents):
        index = sqlite3.connect(':memory:', check_same_thread=False)
        try:
            index.execute('CREATE VIRTUAL TABLE passages USING fts5(text, document_id UNINDEXED, '
                          'chunk_index UNINDEXED, scope UNINDEXED)')
            index.executemany('INSERT INTO passages VALUES (?, ?, ?, ?)', (
                (normalize(chunk['text']), doc['id'], i, doc['scope'])
                for doc in documents.values() for i, chunk in enumerate(doc['chunks'])))
            index.commit()
            return index
        except BaseException:
            index.close()
            raise

    def _swap(self, snapshot, index):
        # Caller holds the lock; publish documents and their matching index together.
        previous = getattr(self, '_index', None)
        self._index = index
        self._documents = snapshot
        if previous is not None:
            previous.close()

    @staticmethod
    def _validate(document, folder, identifier=None):
        if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1:
            raise ValueError("Unsupported knowledge schema")
        identifier = identifier or folder.name
        if not re.fullmatch(r"[0-9a-f]{32}", identifier) or uuid.UUID(identifier).hex != identifier:
            raise ValueError("Knowledge ID must be a UUID")
        if document.get("id") != identifier or document.get("document_id") != identifier:
            raise ValueError("Knowledge IDs do not match canonical folder")
        _scope(document.get("scope"))
        source = document.get("source")
        if not isinstance(source, str) or not source or source in (".", "..") or any(c in source for c in ("/", "\\", "\0", "\r", "\n")):
            raise ValueError("Invalid document source filename")
        if document.get("filename") != source:
            raise ValueError("Document filename does not match source")
        extension = Path(source).suffix.lower()
        if extension not in (".md", ".txt", ".pdf"):
            raise ValueError("Unsupported original document type")
        original = folder / ("original" + extension)
        if original.is_symlink() or not original.is_file() or not original.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Original document must be a local regular file")
        size = document.get("size")
        if type(size) is not int or not 0 <= size <= MAX_BYTES or original.stat().st_size != size:
            raise ValueError("Invalid original document size")
        try:
            created = datetime.fromisoformat(document.get("created_at"))
        except (ValueError, TypeError) as error:
            raise ValueError("Invalid document creation timestamp") from error
        if created.tzinfo is None:
            raise ValueError("Document timestamp must include timezone")
        chunks = document.get("chunks")
        if not isinstance(chunks, list) or not 1 <= len(chunks) <= 3000:
            raise ValueError("Invalid document chunks")
        characters = 0
        for chunk in chunks:
            if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str) or not 1 <= len(chunk["text"]) <= 2000:
                raise ValueError("Invalid document chunk text")
            if chunk.get("page") is not None and (type(chunk["page"]) is not int or not 1 <= chunk["page"] <= 500):
                raise ValueError("Invalid document page")
            if chunk.get("section") is not None and (not isinstance(chunk["section"], str) or len(chunk["section"]) > 2000):
                raise ValueError("Invalid document section")
            characters += len(chunk["text"])
        if characters > MAX_CHARS or not any(chunk["text"].strip() for chunk in chunks):
            raise ValueError("Invalid extracted document length")

    def import_document(self, filename: str, data: bytes, scope="global"):
        _scope(scope)
        if not isinstance(filename, str):
            raise ValueError("Invalid document filename")
        if len(data) > MAX_BYTES:
            raise ValueError("Upload exceeds 25 MiB")
        source = filename.replace("\\", "/").rsplit("/", 1)[-1]
        extension = Path(source).suffix.lower()
        if extension not in {".txt", ".md", ".pdf"}:
            raise ValueError("Only UTF-8 TXT, Markdown, and searchable PDF are supported")
        document_id = uuid.uuid4().hex
        staging = Path(tempfile.mkdtemp(prefix=".import-", dir=self.root))
        try:
            original = staging / ("original" + extension)
            original.write_bytes(data)
            if extension == ".pdf":
                pages = _pdf_pages(original, staging / "worker.json")
                (staging / "worker.json").unlink()
            else:
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise ValueError("Text documents must use UTF-8") from exc
                pages = [{"page": None, "text": text}]
            if sum(len(p["text"]) for p in pages) > MAX_CHARS:
                raise ValueError("Document exceeds 5 million characters")
            if not any(p["text"].strip() for p in pages):
                raise ValueError("Document has no usable text")
            chunks = []
            section = None
            # Fall back to fixed cuts for unusually fragmented large documents so the
            # existing 3,000-chunk and five-million-character limits remain unchanged.
            excerpts = [[(excerpt, page['page']) for excerpt in _chunks(page['text'])]
                        for page in pages]
            if sum(map(len, excerpts)) > 3000:
                excerpts = [[(page['text'][i:i + 2000], page['page'])
                             for i in range(0, len(page['text']), 2000)] for page in pages]
            for page_chunks in excerpts:
                for excerpt, page_number in page_chunks:
                    headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", excerpt) if extension == ".md" else []
                    if headings:
                        section = headings[-1]
                    chunks.append({"text": excerpt, "page": page_number, "section": section})
            document = {"schema_version": 1, "id": document_id, "document_id": document_id, "source": source,
                        "filename": source, "created_at": datetime.now(timezone.utc).isoformat(),
                        "scope": scope, "size": len(data), "chunks": chunks}
            self._validate(document, staging, document_id)
            (staging / "document.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            with self._lock:
                documents = {**self._documents, document_id: document}
                index = self._build_index(documents)
                try:
                    staging.rename(self.root / document_id)
                except BaseException:
                    index.close()
                    raise
                self._swap(documents, index)
            return self._metadata(document)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    @staticmethod
    def _metadata(document):
        return {key: value for key, value in document.items() if key != "chunks"}

    def list_documents(self, scope="global"):
        _scope(scope)
        with self._lock:
            return [self._metadata(d) for d in self._documents.values() if d["scope"] == scope]

    def read(self, document_id, scope="global", *, start_chunk=0, max_chunks=20):
        _scope(scope)
        if type(start_chunk) is not int or start_chunk < 0:
            raise ValueError('start_chunk must be a nonnegative integer')
        if type(max_chunks) is not int or not 1 <= max_chunks <= 20:
            raise ValueError('max_chunks must be an integer between 1 and 20')
        with self._lock:
            document = self._documents.get(document_id)
            if document is None or document["scope"] not in ("global", scope):
                raise KeyError("Knowledge document not found")
            result = self._metadata(document)
            total = len(document['chunks'])
            if start_chunk >= total:
                raise ValueError('start_chunk is outside the document')
            end = min(start_chunk + max_chunks, total)
            result["chunks"] = [dict(document['chunks'][i], chunk_index=i)
                                for i in range(start_chunk, end)]
            result["text"] = "\n".join(c["text"] for c in result["chunks"])
            result['total_chunks'] = total
            result['next_chunk'] = end if end < total else None
            result["truncated"] = start_chunk > 0 or end < total
            return result

    def search(self, query, scope="global", limit=6):
        _scope(scope)
        terms = list(dict.fromkeys(re.findall(r"\w+", normalize(query[:2000]))))
        if not terms:
            return []
        # Quote each literal token. Model-supplied FTS operators are never executed.
        match = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
        with self._lock:
            rows = self._index.execute(
                'SELECT document_id, chunk_index, bm25(passages) AS rank FROM passages '
                'WHERE passages MATCH ? AND scope IN (?, ?) '
                'ORDER BY rank, document_id, chunk_index LIMIT ?',
                (match, 'global', scope, max(0, min(int(limit), 20)))).fetchall()
            results = []
            for document_id, chunk_index, rank in rows:
                document = self._documents[document_id]
                chunk = document['chunks'][chunk_index]
                results.append({'id': document_id, 'document_id': document_id,
                                'chunk_index': chunk_index, 'source': document['source'],
                                'page': chunk['page'], 'section': chunk['section'],
                                'excerpt': chunk['text'], 'score': -rank})
            return results

    def delete(self, document_id):
        if not isinstance(document_id, str) or not re.fullmatch(r"[0-9a-f]{32}", document_id):
            raise KeyError("Knowledge document not found")
        with self._lock:
            if document_id not in self._documents:
                raise KeyError("Knowledge document not found")
            documents = {key: doc for key, doc in self._documents.items() if key != document_id}
            index = self._build_index(documents)
            try:
                shutil.rmtree(self.root / document_id)
            except BaseException:
                index.close()
                raise
            self._swap(documents, index)

