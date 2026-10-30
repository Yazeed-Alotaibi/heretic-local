import io
import json
import os
import subprocess
import sys
import uuid

import pytest
from pypdf import PdfWriter

from heretic_gateway import knowledge
from heretic_gateway.knowledge import Knowledge


def test_unicode_scope_reload_and_delete(tmp_path):
    store = Knowledge(tmp_path)
    document = store.import_document("../notes.md", "# الرحلة\nمَرْحَبًا بالعالم\nEnglish café".encode())
    project = str(uuid.uuid4())
    private = store.import_document("private.txt", b"English private", scope=project)
    assert store.search("مرحبا")[0]["document_id"] == document["id"]
    assert store.search("CAFÉ")[0]["source"] == "notes.md"
    assert len(store.search("English")) == 1
    assert store.search("private") == []
    assert store.search("private", scope=project)[0]["document_id"] == private["id"]
    assert len(store.search("English", scope=project)) == 2
    assert store.read(document["id"], scope=project)["filename"] == "notes.md"
    with pytest.raises(KeyError):
        store.read(private["id"])
    store.reload()
    assert store.read(document["id"])["chunks"][0]["section"] == "الرحلة"
    assert (store.root / document["id"] / "original.md").read_bytes().startswith(b"# ")
    store.delete(document["id"])
    assert store.search("مرحبا") == []
    assert not (store.root / document["id"]).exists()


def test_search_hit_can_be_read_after_twentieth_chunk_and_reload(tmp_path):
    store = Knowledge(tmp_path)
    doc = store.import_document('long.txt', ('background ' * 5000 + '\n\nrareanchor conclusion').encode())
    hit = store.search('rareanchor')[0]
    assert hit['chunk_index'] > 20
    store.reload()
    result = store.read(doc['id'], start_chunk=hit['chunk_index'], max_chunks=1)
    assert 'rareanchor' in result['text']
    assert result['chunks'][0]['chunk_index'] == hit['chunk_index']
    assert result['source'] == hit['source']
    assert result['next_chunk'] is None
    assert result['total_chunks'] > 20
    first = store.read(doc['id'], start_chunk=0, max_chunks=1)
    assert first['next_chunk'] == 1
    assert first['truncated'] is True


@pytest.mark.parametrize('start,count', [(-1, 1), (True, 1), (0, 0), (0, 21), (0, '1')])
def test_chunk_read_rejects_invalid_ranges(tmp_path, start, count):
    store = Knowledge(tmp_path)
    doc = store.import_document('notes.txt', b'notes')
    with pytest.raises(ValueError):
        store.read(doc['id'], start_chunk=start, max_chunks=count)


def test_chunk_read_scope_and_out_of_range(tmp_path):
    store = Knowledge(tmp_path)
    project = str(uuid.uuid4())
    doc = store.import_document('private.txt', b'secret marker', scope=project)
    with pytest.raises(KeyError):
        store.read(doc['id'], start_chunk=0, max_chunks=1)
    with pytest.raises(ValueError):
        store.read(doc['id'], scope=project, start_chunk=99)


def test_search_ranks_relevant_passage_above_long_keyword_padding(tmp_path):
    store = Knowledge(tmp_path)
    store.import_document('padding.txt', ('delay ' + 'background ' * 150).encode())
    best = store.import_document('answer.txt', b'delay mitigation plan')
    assert store.search('delay')[0]['document_id'] == best['id']
    assert store.search('delay OR " * (')[0]['document_id'] == best['id']
    store.delete(best['id'])
    assert all(hit['document_id'] != best['id'] for hit in store.search('delay'))


def test_new_chunks_prefer_paragraph_boundaries_without_losing_text(tmp_path):
    store = Knowledge(tmp_path)
    text = 'a' * 1850 + '\n\n' + 'b' * 500
    doc = store.import_document('paragraphs.txt', text.encode())
    chunks = store.read(doc['id'])['chunks']
    assert chunks[0]['text'] == 'a' * 1850 + '\n\n'
    assert ''.join(c['text'] for c in chunks) == text


def test_long_question_does_not_drop_relevant_query_terms(tmp_path):
    store = Knowledge(tmp_path)
    doc = store.import_document('answer.txt', b'zenith answer')
    question = ' '.join('a%02d' % i for i in range(64)) + ' zenith'
    assert store.search(question)[0]['id'] == doc['id']


def test_upload_and_text_limits(tmp_path, monkeypatch):
    store = Knowledge(tmp_path)
    monkeypatch.setattr(knowledge, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="25 MiB"):
        store.import_document("large.txt", b"x" * 11)
    monkeypatch.setattr(knowledge, "MAX_BYTES", 100)
    monkeypatch.setattr(knowledge, "MAX_CHARS", 5)
    with pytest.raises(ValueError, match="5 million"):
        store.import_document("large.txt", b"123456")
    with pytest.raises(ValueError, match="UTF-8"):
        store.import_document("bad.txt", b"\xff")
    with pytest.raises(ValueError, match="no usable"):
        store.import_document("empty.md", b" ")
    assert list(store.root.iterdir()) == []


@pytest.mark.parametrize("encrypted", [False, True])
def test_pdf_without_usable_text(tmp_path, encrypted):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("secret")
    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(ValueError, match="malformed, encrypted"):
        Knowledge(tmp_path).import_document("empty.pdf", data.getvalue())


def test_malformed_pdf(tmp_path):
    with pytest.raises(ValueError, match="malformed"):
        Knowledge(tmp_path).import_document("bad.pdf", b"%PDF-invalid")


def test_pdf_page_limit(tmp_path):
    writer = PdfWriter()
    for _ in range(501):
        writer.add_blank_page(width=10, height=10)
    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(ValueError, match="exceeds limits"):
        Knowledge(tmp_path).import_document("long.pdf", data.getvalue())


def test_searchable_pdf(tmp_path):
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (Searchable English knowledge) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    data = io.BytesIO()
    writer.write(data)
    store = Knowledge(tmp_path)
    store.import_document("example.pdf", data.getvalue())
    assert store.search("knowledge")[0]["page"] == 1


def test_timeout_kills_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "PDF_TIMEOUT", 0)
    with pytest.raises(ValueError, match="60 seconds"):
        Knowledge(tmp_path).import_document("bad.pdf", b"%PDF-invalid")
    assert list((tmp_path / "knowledge").iterdir()) == []


def test_read_is_bounded(tmp_path):
    store = Knowledge(tmp_path)
    document = store.import_document("long.txt", b"word " * 10000)
    result = store.read(document["id"])
    assert result["truncated"] is True
    assert len(result["text"]) <= 40020
    assert len(store.search("word", limit=100)) == 20
    with pytest.raises(KeyError):
        store.delete("../outside")


def test_reload_prepares_valid_snapshot_without_losing_live_documents(tmp_path):
    store = Knowledge(tmp_path)
    document = store.import_document("أَلِف.md", "إِبداع آمال ٱختبار ـ".encode())
    assert store.search("ابداع")[0]["id"] == document["id"]
    metadata = store.root / document["id"] / "document.json"
    original = json.loads(metadata.read_text(encoding="utf-8"))
    broken = dict(original, schema_version=2)
    metadata.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        store.reload()
    assert store.search("ابداع")[0]["id"] == document["id"]
    original["chunks"][0]["text"] = "different content"
    metadata.write_text(json.dumps(original), encoding="utf-8")
    snapshot = store.prepare_reload()
    assert store.search("ابداع")
    store.install_reload(snapshot)
    assert store.search("different")
    assert not store.search("ابداع")


@pytest.mark.parametrize("field,value", [
    ("id", "not-a-uuid"), ("scope", "session:private"), ("source", "../outside.txt"),
    ("filename", "mismatch.txt"), ("size", -1), ("chunks", [{"text": "x" * 2001}]),
    ("created_at", "invalid"),
])
def test_reload_rejects_invalid_manual_metadata(tmp_path, field, value):
    store = Knowledge(tmp_path)
    document = store.import_document("valid.txt", b"valid knowledge")
    metadata = store.root / document["id"] / "document.json"
    changed = json.loads(metadata.read_text(encoding="utf-8"))
    changed[field] = value
    metadata.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError):
        store.reload()
    assert store.search("valid")[0]["id"] == document["id"]


@pytest.mark.skipif(os.name != "nt", reason="Windows JobObject enforcement")
def test_windows_job_hard_memory_cap():
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", "bytearray(600 * 1024 * 1024)"],
        creationflags=0x4 | subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    close_job = None
    try:
        close_job = knowledge._windows_job(process)
        assert process.wait(timeout=10) != 0
    finally:
        if close_job:
            close_job()
        if process.poll() is None:
            process.kill()
        process.wait()

