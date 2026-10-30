import json

import pytest

from heretic_gateway.context_builder import build_context


def unpack(blocks):
    profile = json.loads(blocks[0]['content'].split('Approved preferences:\n', 1)[1])
    facts = json.loads(blocks[1]['content'].split('\n', 1)[1]) if len(blocks) > 1 else []
    return profile, facts


@pytest.mark.asyncio
async def test_many_candidates_keep_references_with_few_exact_counts():
    preferences = [{'id': f'p{i}', 'content': 'Prefer concise responses.', 'source': 'approved'}
                   for i in range(1000)]
    evidence = [{'id': f'd{i}', 'text': 'الموعد يوم الخميس. ' * 20,
                 'source': 'schedule.md', 'page': 3, 'chunk_index': i, 'section': 'Schedule'}
                for i in range(100)]
    calls = []

    async def count(blocks):
        calls.append(blocks)
        return 40 + sum(len(block['content'].encode('utf-8')) // 4 for block in blocks)

    blocks, records, cost = await build_context(preferences, evidence, 'Policy', count)
    profile, facts = unpack(blocks)
    assert len(calls) <= 3
    assert cost <= 2560
    empty_cost = 40 + len('Policy\nApproved preferences:\n[]'.encode()) // 4
    profile_cost = 40 + len(blocks[0]['content'].encode()) // 4
    assert profile_cost - empty_cost <= 512
    assert [item['id'] for item in profile] == ['p0', 'p1', 'p2', 'p3']
    assert facts and facts[0]['content'] == evidence[0]['text']
    assert [item['id'] for item in facts] == [f'd{i}' for i in range(len(facts))]
    assert records[4] == {'id': 'd0', 'source': 'schedule.md', 'page': 3,
                          'chunk_index': 0, 'section': 'Schedule'}
    assert 'content' not in records[0]
    assert 'content' not in evidence[0]


@pytest.mark.asyncio
async def test_inaccurate_estimate_trims_ranked_suffixes_using_exact_counts():
    preferences = [{'id': f'p{i}', 'content': 'p' * 20} for i in range(4)]
    evidence = [{'id': f'd{i}', 'content': 'e' * 20} for i in range(40)]
    calls = []

    def exact(blocks):
        profile, facts = unpack(blocks)
        return 40 + sum(8 * len(item['content']) for item in profile + facts)

    async def count(blocks):
        calls.append(blocks)
        return exact(blocks)

    blocks, records, cost = await build_context(preferences, evidence, 'Policy', count,
                                               snapshot_budget=1000, preference_budget=400)
    profile, facts = unpack(blocks)
    assert len(calls) > 3  # Both heuristic allocations deliberately underestimate tokens.
    assert [item['id'] for item in profile] == ['p0', 'p1']
    assert exact([blocks[0]]) - 40 <= 400
    assert facts and [item['id'] for item in facts] == [f'd{i}' for i in range(len(facts))]
    assert cost == exact(blocks) <= 1000
    assert [item['id'] for item in records] == [item['id'] for item in profile + facts]

    with pytest.raises(ValueError, match='framing.*snapshot token budget'):
        await build_context([], [], 'Policy', count, snapshot_budget=39)
