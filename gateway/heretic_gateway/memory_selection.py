"""Select scoped preferences and fairly ordered retrieval evidence."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from itertools import zip_longest

from .store import normalize


def _terms(text: str) -> set[str]:
    return set(re.findall(r"\w+", normalize(text)))


def _recency(item: dict) -> float:
    for field in ("updated_at", "created_at"):
        try:
            parsed = datetime.fromisoformat(item.get(field, ""))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (ValueError, TypeError, OverflowError):
            continue
    return float("-inf")


def select_candidates(
    preferences: list[dict],
    memories: list[dict],
    documents: list[dict],
    query: str,
    scope: str,
) -> tuple[list[dict], list[dict]]:
    """Return original records, ranked without changing the input collections.

    Retrieval inputs already carry search rank. Alternate their unique hits,
    starting with documents, so either source can survive a short context budget.
    """
    def permitted(item: dict) -> bool:
        return "scope" not in item or item["scope"] in ("global", scope)

    query_terms = _terms(query)
    ranked_preferences = sorted(
        (item for item in preferences if permitted(item)),
        key=lambda item: (
            len(query_terms & _terms(item.get("content", ""))),
            scope != "global" and item.get("scope") == scope,
            _recency(item),
        ),
        reverse=True,
    )[:4]

    unique_documents = []
    seen_documents = set()
    for item in documents:
        key = (item.get("id", item.get("document_id")), item.get("chunk_index"))
        if permitted(item) and key not in seen_documents:
            seen_documents.add(key)
            unique_documents.append(item)

    unique_memories = []
    seen_memories = set()
    for item in memories:
        key = item.get("id")
        if permitted(item) and item.get("kind") != "preference" and key not in seen_memories:
            seen_memories.add(key)
            unique_memories.append(item)

    evidence = [
        item
        for pair in zip_longest(unique_documents, unique_memories)
        for item in pair
        if item is not None
    ]
    return ranked_preferences, evidence
