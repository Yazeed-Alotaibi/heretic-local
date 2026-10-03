"""Isolated, bounded PDF extraction; invoked only by knowledge.py."""
import json
import sys

MAX_PAGES = 500
MAX_CHARS = 5_000_000


def extract(path):
    from pypdf import PdfReader

    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported")
    if len(reader.pages) > MAX_PAGES:
        raise ValueError("PDF exceeds 500 pages")
    pages = []
    total = 0
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        total += len(text)
        if total > MAX_CHARS:
            raise ValueError("Document exceeds 5 million characters")
        pages.append({"page": number, "text": text})
    if not any(page["text"].strip() for page in pages):
        raise ValueError("PDF has no usable text; OCR is not supported")
    return pages


if __name__ == "__main__":
    try:
        result = {"pages": extract(sys.argv[1])}
    except Exception:
        result = {"error": "PDF is malformed, encrypted, exceeds limits, or has no usable text"}
    with open(sys.argv[2], "w", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False)
