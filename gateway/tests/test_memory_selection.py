from copy import deepcopy

from heretic_gateway.memory_selection import select_candidates


def test_relevant_preferences_survive_pile_and_ties_use_scope_then_recency():
    old = [
        {"id": str(i), "content": "unrelated preference", "scope": "global",
         "created_at": "2020-01-01T00:00:00+00:00"}
        for i in range(30)
    ]
    relevant = [
        {"id": "global", "content": "اختبار", "scope": "global",
         "updated_at": "2026-10-30T00:00:00+00:00"},
        {"id": "older", "content": "اختبار", "scope": "project",
         "created_at": "2025-01-01T00:00:00+00:00"},
        {"id": "newer", "content": "اختبار", "scope": "project",
         "updated_at": "2026-01-01T01:00:00+01:00"},
        {"id": "foreign", "content": "اختبار", "scope": "other"},
    ]
    inputs = old + relevant
    before = deepcopy(inputs)
    selected, evidence = select_candidates(inputs, [], [], "إِخْتِبار", "project")
    assert [item["id"] for item in selected[:3]] == ["newer", "older", "global"]
    assert len(selected) == 4
    assert selected[0] is relevant[2]
    assert inputs == before
    assert evidence == []


def test_evidence_interleaves_ranked_unique_documents_and_nonpreference_memories():
    doc0 = {"id": "doc", "chunk_index": 0, "excerpt": "first"}
    doc1 = {"id": "doc", "chunk_index": 1, "excerpt": "second"}
    doc2 = {"id": "another", "chunk_index": 0, "excerpt": "third"}
    memory0 = {"id": "memory0", "kind": "fact", "scope": "global"}
    memory1 = {"id": "memory1", "kind": "checkpoint", "scope": "project"}
    documents = [doc0, dict(doc0), {"id": "foreign", "scope": "other"}, doc1, doc2]
    memories = [memory0, dict(memory0), {"id": "preference", "kind": "preference"},
                {"id": "foreign", "scope": "other"}, memory1]
    before = deepcopy((documents, memories))
    _, evidence = select_candidates([], memories, documents, "", "project")
    expected = [doc0, memory0, doc1, memory1, doc2]
    assert evidence == expected
    assert all(actual is original for actual, original in zip(evidence, expected))
    assert (documents, memories) == before
