import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from heretic_gateway.app import create_app
from heretic_gateway.state import State


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        yield self.data


@pytest.fixture
def gateway(tmp_path):
    requests = []

    def upstream(request):
        data = json.loads(request.content) if request.content else {}
        requests.append((request.url.path, data))
        if request.url.path == '/tokenize':
            return httpx.Response(200, json={'tokens': list(range(len(data['content']) // 3 + 1))})
        if request.url.path == '/apply-template':
            return httpx.Response(200, json={'prompt': json.dumps(data['messages'])})
        if request.url.path == '/tools':
            if request.method == 'GET':
                return httpx.Response(200, json=[])
            return httpx.Response(200, json={'content': 'external result'})
        if request.url.path == '/v1/chat/completions':
            response = {'choices': [{'message': {'role': 'assistant', 'tool_calls': [
                {'id': 'call-1', 'type': 'function', 'function': {'name': 'exa_web_search_exa',
                    'arguments': '{"query":"example"}'}}]}, 'finish_reason': 'tool_calls'}]}
            if data.get('stream'):
                raw = ('data: ' + json.dumps(response) + '\n\ndata: [DONE]\n\n').encode()
                return httpx.Response(200, stream=BytesStream(raw), headers={'content-type': 'text/event-stream'})
            return httpx.Response(200, json=response)
        return httpx.Response(200, json={'status': 'ok'})

    app = create_app(tmp_path, transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        client.headers['X-Heretic-Session'] = client.get('/api/heretic/session').json()['token']
        yield client, app, requests


def begin(client, conversation='one', text='hello', memory=True, history=False, assistant='a'):
    response = client.post('/api/heretic/executions', json={
        'conversation_id': conversation, 'human_message_id': 'h', 'human_revision': text,
        'human_text': text, 'assistant_execution_id': assistant, 'project': 'global',
        'memory_enabled': memory, 'has_history': history})
    assert response.status_code == 200, response.text
    return response.json()['execution_token']


def generate(client, token, text='hello', stream=False):
    return client.post('/v1/chat/completions', headers={'X-Heretic-Execution': token}, json={
        'messages': [{'role': 'user', 'content': text}], 'stream': stream})


def invoke(client, token):
    return client.post('/tools', json={'execution_token': token, 'tool_call_id': 'call-1',
        'tool': 'exa_web_search_exa', 'params': {'query': 'example'}})


def test_private_approval_is_per_invocation_and_retries_do_not_repeat(gateway):
    client, app, requests = gateway
    app.state.store.save_record('Always answer briefly', kind='preference')
    token = begin(client)
    assert generate(client, token).status_code == 200
    pending = invoke(client, token)
    assert pending.status_code == 409
    approval = pending.json()['detail']['approval_id']
    assert not [r for r in requests if r[0] == '/tools']
    assert client.post('/api/heretic/approvals/' + approval, json={'approve': True}).status_code == 200
    assert invoke(client, token).status_code == 200
    assert invoke(client, token).status_code == 200
    assert len([r for r in requests if r[0] == '/tools']) == 1
    second = begin(client, conversation='two')
    generate(client, second)
    assert invoke(client, second).status_code == 409


def test_memory_off_fresh_vs_historical_and_mode_is_not_changed(gateway):
    client, app, _requests = gateway
    token = begin(client, memory=False)
    generate(client, token)
    assert invoke(client, token).status_code == 200
    token2 = begin(client, conversation='older', memory=False, history=True)
    generate(client, token2)
    assert invoke(client, token2).status_code == 409
    token3 = begin(client, conversation='older', memory=True, history=True, assistant='b')
    assert app.state.store.conversation('older')['memory_enabled'] is True
    assert app.state.capabilities.executions[token3].private_context


def test_forged_calls_and_changed_turn_are_rejected(gateway):
    client, _app, _requests = gateway
    token = begin(client)
    assert invoke(client, token).status_code == 403
    assert generate(client, token, 'changed').status_code == 409
    generate(client, token)
    response = client.post('/tools', json={'execution_token': token, 'tool_call_id': 'call-1',
        'tool': 'exa_web_search_exa', 'params': {'query': 'different'}})
    assert response.status_code == 403


def test_stream_bytes_are_not_modified(gateway):
    client, _app, _requests = gateway
    token = begin(client)
    response = generate(client, token, stream=True)
    assert response.content.startswith(b'data: {"choices":')
    assert response.content.endswith(b'\n\ndata: [DONE]\n\n')
    assert invoke(client, token).status_code == 200


def test_forget_cancels_existing_capabilities(gateway):
    client, app, _requests = gateway
    record = app.state.store.save_record('Be concise', kind='preference')
    token = begin(client)
    generate(client, token)
    assert client.delete('/api/heretic/records/' + record['id']).status_code == 200
    assert invoke(client, token).status_code == 409


def test_remember_save_is_explicit_and_idempotent(gateway):
    client, app, _requests = gateway
    begin(client, text='Remember: I prefer Arabic')
    begin(client, text='Remember: I prefer Arabic')
    records = app.state.store.list_records()
    assert len(records) == 1 and records[0]['content'] == 'I prefer Arabic'


def test_origin_and_session_required(gateway):
    client, _app, _requests = gateway
    assert client.get('/api/heretic/records', headers={'origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/heretic/records', headers={'X-Heretic-Session': ''}).status_code == 401
    assert client.post('/completion', json={}).status_code == 404


def test_expired_and_restart_tokens_fail(gateway):
    client, app, _requests = gateway
    token = begin(client)
    app.state.capabilities.executions[token].touched -= 1801
    assert generate(client, token).status_code == 409
    assert not State().executions


def test_document_recall_is_bounded_and_has_source(gateway):
    client, app, _requests = gateway
    doc = app.state.knowledge.import_document('manual.txt', b'hello world')
    token = begin(client)
    result = generate(client, token)
    assert result.status_code == 200, result.text
    context = client.get('/api/heretic/context/' + token).json()
    assert context['token_count'] <= 4096
    assert any(r['id'] == doc['id'] for r in context['records'])


def test_stream_ids_are_server_owned_and_lookup_is_session_scoped(gateway):
    client, app, _requests = gateway
    original = app.state.client._transport.handler
    forwarded = []

    def upstream(request):
        if request.url.path == '/v1/chat/completions':
            forwarded.append(request.headers['x-conversation-id'])
        if request.url.path == '/v1/stream':
            forwarded.append(request.url.params['conv_id'])
            return httpx.Response(200, stream=BytesStream(b'data: [DONE]\n\n'))
        if request.url.path == '/v1/streams/lookup':
            ids = json.loads(request.content)['conversation_ids']
            return httpx.Response(200, json=[{'conversation_id': i, 'is_done': True,
                'total_bytes': 19, 'started_at': 1, 'completed_at': 2} for i in ids])
        return original(request)

    app.state.client._transport.handler = upstream
    token = begin(client)
    bad = client.post('/v1/chat/completions', headers={'X-Heretic-Execution': token,
        'X-Conversation-Id': 'stolen'}, json={'messages': [{'role': 'user', 'content': 'hello'}]})
    assert bad.status_code == 403
    assert not forwarded
    assert generate(client, token).status_code == 200
    ex = app.state.capabilities.executions[token]
    assert ex.stream_id != 'one' and forwarded == [ex.stream_id]
    assert client.get('/v1/stream?conv_id=stolen', headers={'X-Heretic-Execution': token}).status_code == 403
    response = client.get('/v1/stream?conv_id=one', headers={'X-Heretic-Execution': token})
    assert response.content == b'data: [DONE]\n\n'
    assert forwarded[-1] == ex.stream_id
    lookup = client.post('/v1/streams/lookup', json={'conversation_ids': ['one', 'stolen']})
    assert [item['conversation_id'] for item in lookup.json()] == ['one']
    other_session = client.get('/api/heretic/session').json()['token']
    assert client.post('/v1/streams/lookup', headers={'X-Heretic-Session': other_session},
                       json={'conversation_ids': ['one']}).json() == []
    assert client.delete('/v1/stream?conv_id=one', headers={'X-Heretic-Execution': token}).status_code == 200
    assert ex.revoked


@pytest.mark.parametrize('expire', [False, True])
def test_revoke_or_expire_during_replay_cannot_dispatch_tool(gateway, expire):
    client, app, requests = gateway
    token = begin(client)
    generate(client, token)
    ex = app.state.capabilities.executions[token]
    ex.calls.clear()
    original = app.state.client._transport.handler

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def upstream(request):
            if request.url.path == '/v1/stream' and request.method == 'GET':
                entered.set()
                await release.wait()
                raw = b'data: {"choices":[{"message":{"tool_calls":[{"id":"call-1","function":{"name":"exa_web_search_exa","arguments":"{\\"query\\":\\"example\\"}"}}]},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n'
                return httpx.Response(200, stream=BytesStream(raw))
            return original(request)

        app.state.client._transport.handler = upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver',
                                     headers={'X-Heretic-Session': client.headers['X-Heretic-Session']}) as browser:
            task = asyncio.create_task(browser.post('/tools', json={'execution_token': token,
                'tool_call_id': 'call-1', 'tool': 'exa_web_search_exa', 'params': {'query': 'example'}}))
            await asyncio.wait_for(entered.wait(), 2)
            if expire:
                ex.touched -= 1801
            else:
                assert (await browser.delete('/api/heretic/executions/' + token)).status_code == 200
            release.set()
            assert (await task).status_code == 409
        assert not [r for r in requests if r[0] == '/tools']

    asyncio.run(run())


def test_concurrent_reads_share_one_memory_budget(gateway):
    client, app, _requests = gateway
    record = app.state.store.save_record('Budgeted memory')
    token = begin(client)
    ex = app.state.capabilities.executions[token]
    ex.generation = 1
    for call_id in ['read-a', 'read-b']:
        ex.calls[call_id] = {'tool': 'memory_read', 'params': {'id': record['id']},
                            'status': 'new', 'generation': 1}

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        counts = []

        async def upstream(request):
            if request.url.path == '/tokenize':
                counts.append(1)
                if len(counts) == 1:
                    entered.set()
                    await release.wait()
                return httpx.Response(200, json={'tokens': list(range(2500))})
            return httpx.Response(200, json={})

        app.state.client._transport.handler = upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver',
                                     headers={'X-Heretic-Session': client.headers['X-Heretic-Session']}) as browser:
            async def read(call_id):
                return await browser.post('/tools', json={'execution_token': token,
                    'tool_call_id': call_id, 'tool': 'memory_read', 'params': {'id': record['id']}})
            first = asyncio.create_task(read('read-a'))
            await asyncio.wait_for(entered.wait(), 2)
            second = asyncio.create_task(read('read-b'))
            await asyncio.sleep(0)
            assert len(counts) == 1
            release.set()
            results = await asyncio.gather(first, second)
            assert any('error' in r.json() for r in results)
            assert ex.token_count == 2500
            assert ex.private_context

    asyncio.run(run())


def test_global_correction_from_project_retains_scope_and_marks_private(gateway):
    client, app, _requests = gateway
    record = app.state.store.save_record('Global preference')
    project = app.state.store.create_project('Work')
    token = begin(client)
    ex = app.state.capabilities.executions[token]
    ex.scope = project['id']
    ex.generation = 1
    ex.calls['propose'] = {'tool': 'memory_propose', 'params': {'content': 'Updated preference',
        'record_id': record['id'], 'expected_revision': record['revision']}, 'status': 'new', 'generation': 1}
    response = client.post('/tools', json={'execution_token': token, 'tool_call_id': 'propose',
        'tool': 'memory_propose', 'params': ex.calls['propose']['params']})
    assert response.status_code == 200
    assert ex.private_context
    proposal_id = response.json()['proposal_id']
    saved = client.post('/api/heretic/proposals/' + proposal_id + '/save', json={})
    assert saved.status_code == 200, saved.text
    assert app.state.store.get_record(record['id'])['scope'] == 'global'


def test_media_health_requires_service_identity(gateway):
    client, _app, _requests = gateway
    assert client.get('/api/heretic/health').json()['files'] == 'unavailable'


def test_snapshot_is_not_published_until_counting_finishes(gateway):
    client, app, _requests = gateway
    app.state.store.save_record('Always use snapshot preference', kind='preference')
    token = begin(client)
    ex = app.state.capabilities.executions[token]
    original = app.state.client._transport.handler

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        templates, completions = [], []

        async def upstream(request):
            if request.url.path == '/apply-template':
                templates.append(1)
                if len(templates) == 1:
                    entered.set()
                    await release.wait()
            if request.url.path == '/v1/chat/completions':
                completions.append(json.loads(request.content))
            return original(request)

        app.state.client._transport.handler = upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver',
                                     headers={'X-Heretic-Session': client.headers['X-Heretic-Session']}) as browser:
            async def complete():
                return await browser.post('/v1/chat/completions', headers={'X-Heretic-Execution': token},
                    json={'messages': [{'role': 'user', 'content': 'hello'}]})
            first = asyncio.create_task(complete())
            await asyncio.wait_for(entered.wait(), 2)
            second = asyncio.create_task(complete())
            await asyncio.sleep(0)
            assert ex.snapshot is None and not completions
            release.set()
            results = await asyncio.gather(first, second)
            assert all(r.status_code in {200, 409} for r in results)
            assert len(templates) == 2
            assert len(completions) == 2
            assert all('snapshot preference' in json.dumps(c['messages']) for c in completions)

    asyncio.run(run())


def test_old_generation_tool_is_rejected_and_new_generation_reuses_call_id(gateway):
    client, app, _requests = gateway
    token = begin(client)
    generate(client, token)
    ex = app.state.capabilities.executions[token]
    old_call = dict(ex.calls['call-1'])
    generate(client, token)
    assert ex.calls['call-1']['generation'] == ex.generation == 2
    ex.calls['call-1'] = old_call
    assert invoke(client, token).status_code == 403


def test_expired_approval_is_not_dispatched(gateway):
    client, app, requests = gateway
    token = begin(client, history=True)
    generate(client, token)
    pending = invoke(client, token)
    approval = pending.json()['detail']['approval_id']
    assert client.post('/api/heretic/approvals/' + approval, json={'approve': True}).status_code == 200
    app.state.capabilities.approvals[approval]['created'] -= 901
    renewed = invoke(client, token)
    assert renewed.status_code == 409
    assert renewed.json()['detail']['approval_id'] != approval
    assert not [r for r in requests if r[0] == '/tools']


def test_direct_correction_cannot_move_scope(gateway):
    client, app, _requests = gateway
    record = app.state.store.save_record('Global record')
    project = app.state.store.create_project('Project')
    result = client.post('/api/heretic/records', json={'content': 'Moved record',
        'record_id': record['id'], 'expected_revision': record['revision'], 'scope': project['id']})
    assert result.status_code == 409
    assert app.state.store.get_record(record['id'])['scope'] == 'global'


def test_private_write_revokes_all_bindings_and_cancels_opaque_streams(gateway):
    client, app, _requests = gateway
    tokens = [begin(client, conversation=name) for name in ['one', 'two']]
    for token in tokens:
        generate(client, token)
    executions = [app.state.capabilities.executions[t] for t in tokens]
    cancelled = []
    original = app.state.client._transport.handler

    def upstream(request):
        if request.url.path == '/v1/stream' and request.method == 'DELETE':
            cancelled.append(request.url.params['conv_id'])
        return original(request)

    app.state.client._transport.handler = upstream
    assert client.post('/api/heretic/knowledge', headers={'X-Filename': 'new.txt'},
                       content=b'New local document').status_code == 200
    assert set(cancelled) == {ex.stream_id for ex in executions}
    assert all(ex.revoked for ex in executions)


def test_old_approval_cannot_authorize_reused_call_id_in_new_generation(gateway):
    client, app, requests = gateway
    token = begin(client, history=True)
    generate(client, token)
    approval_a = invoke(client, token).json()['detail']['approval_id']
    original = app.state.client._transport.handler

    def upstream(request):
        response = original(request)
        if request.url.path == '/v1/chat/completions':
            content = response.json()
            call = content['choices'][0]['message']['tool_calls'][0]
            call['function']['arguments'] = '{"query":"different"}'
            return httpx.Response(200, json=content)
        return response

    app.state.client._transport.handler = upstream
    assert generate(client, token).status_code == 200
    invocation = {'execution_token': token, 'tool_call_id': 'call-1',
                  'tool': 'exa_web_search_exa', 'params': {'query': 'different'}}
    pending = client.post('/tools', json=invocation)
    assert pending.status_code == 409
    approval_b = pending.json()['detail']['approval_id']
    assert approval_a != approval_b
    assert client.post('/api/heretic/approvals/' + approval_a,
                       json={'approve': True}).status_code == 409
    assert client.post('/tools', json=invocation).status_code == 409
    assert not [r for r in requests if r[0] == '/tools']
    assert client.post('/api/heretic/approvals/' + approval_b,
                       json={'approve': True}).status_code == 200
    assert client.post('/tools', json=invocation).status_code == 200
    assert len([r for r in requests if r[0] == '/tools']) == 1


def test_approved_call_arguments_cannot_change_before_dispatch(gateway):
    client, app, requests = gateway
    token = begin(client, history=True)
    generate(client, token)
    approval = invoke(client, token).json()['detail']['approval_id']
    assert client.post('/api/heretic/approvals/' + approval, json={'approve': True}).status_code == 200
    app.state.capabilities.executions[token].calls['call-1']['params'] = {'query': 'changed'}
    response = client.post('/tools', json={'execution_token': token, 'tool_call_id': 'call-1',
        'tool': 'exa_web_search_exa', 'params': {'query': 'changed'}})
    assert response.status_code == 409
    assert response.json()['detail']['approval_id'] != approval
    assert not [r for r in requests if r[0] == '/tools']


def test_reconnect_replays_current_stream_when_call_id_was_reused(gateway):
    client, app, _requests = gateway
    token = begin(client)
    generate(client, token)
    ex = app.state.capabilities.executions[token]
    old_call = dict(ex.calls['call-1'])
    old_stream = ex.stream_id
    generate(client, token)
    ex.calls['call-1'] = old_call
    original = app.state.client._transport.handler
    replayed = []

    def upstream(request):
        if request.url.path == '/v1/stream' and request.method == 'GET':
            replayed.append(request.url.params['conv_id'])
            response = {'choices': [{'message': {'tool_calls': [{'id': 'call-1',
                'function': {'name': 'exa_web_search_exa', 'arguments': '{"query":"resumed"}'}}]},
                'finish_reason': 'tool_calls'}]}
            return httpx.Response(200, stream=BytesStream(
                ('data: ' + json.dumps(response) + '\n\ndata: [DONE]\n\n').encode()))
        return original(request)

    app.state.client._transport.handler = upstream
    result = client.post('/tools', json={'execution_token': token, 'tool_call_id': 'call-1',
        'tool': 'exa_web_search_exa', 'params': {'query': 'resumed'}})
    assert result.status_code == 200, result.text
    assert replayed == [ex.stream_id] and ex.stream_id != old_stream
    assert ex.calls['call-1']['generation'] == 2


def test_attested_denial_allows_continuation_without_external_dispatch(gateway):
    client, _app, requests = gateway
    token = begin(client)
    generate(client, token)
    endpoint = '/api/heretic/executions/' + token + '/calls/call-1/deny'
    assert client.post(endpoint.replace('call-1', 'forged')).status_code == 403
    assert client.post(endpoint).status_code == 200
    assert client.post(endpoint).status_code == 409
    assert invoke(client, token).json() == {'error': 'User declined this external request.'}
    messages = [{'role': 'user', 'content': 'hello'}, {'role': 'assistant', 'tool_calls': [
        {'id': 'call-1', 'type': 'function', 'function': {'name': 'exa_web_search_exa',
          'arguments': '{"query":"example"}'}}]}, {'role': 'tool', 'tool_call_id': 'call-1',
        'content': 'User declined this external request.'}]
    response = client.post('/v1/chat/completions', headers={'X-Heretic-Execution': token},
                           json={'messages': messages})
    assert response.status_code == 200, response.text
    assert not [r for r in requests if r[0] == '/tools']


@pytest.mark.parametrize('status', ['running', 'complete'])
def test_denial_rejects_started_or_completed_invocations(gateway, status):
    client, app, _requests = gateway
    token = begin(client)
    generate(client, token)
    app.state.capabilities.executions[token].calls['call-1']['status'] = status
    response = client.post('/api/heretic/executions/' + token + '/calls/call-1/deny')
    assert response.status_code == 409


def test_active_stream_extends_execution_inactivity_timeout(gateway, monkeypatch):
    import heretic_gateway.app as app_module
    import heretic_gateway.state as state_module

    client, app, requests = gateway
    now = [app_module.time.monotonic()]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(app_module, 'time', clock)
    monkeypatch.setattr(state_module, 'time', clock)
    token = begin(client, memory=False)
    ex = app.state.capabilities.executions[token]
    ex.touched = now[0]
    started = now[0]
    original = app.state.client._transport.handler

    class ActiveStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(4):
                now[0] += 1200
                yield b': activity\n\n'
                assert ex.touched == now[0]

    def upstream(request):
        if request.url.path == '/v1/chat/completions':
            return httpx.Response(200, stream=ActiveStream(), headers={'content-type': 'text/event-stream'})
        return original(request)

    app.state.client._transport.handler = upstream
    response = generate(client, token, stream=True)
    assert response.content == b': activity\n\n' * 4
    assert now[0] - started == pytest.approx(4800)
    assert app.state.capabilities.executions[token] is ex
    now[0] += 1801
    assert client.get('/api/heretic/context/' + token).status_code == 409
    assert token not in app.state.capabilities.executions


@pytest.mark.parametrize('invalidation', ['idle', 'revoked', 'generation'])
def test_stream_activity_cannot_revive_invalid_execution(gateway, monkeypatch, invalidation):
    import heretic_gateway.app as app_module
    import heretic_gateway.state as state_module

    client, app, requests = gateway
    now = [app_module.time.monotonic()]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(app_module, 'time', clock)
    monkeypatch.setattr(state_module, 'time', clock)
    token = begin(client, memory=False)
    ex = app.state.capabilities.executions[token]
    ex.touched = now[0]
    admitted = []
    original = app.state.client._transport.handler

    class InvalidatedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            now[0] += 1200
            yield b': admitted\n\n'
            admitted.append(ex.touched)
            now[0] += 1801 if invalidation == 'idle' else 100
            if invalidation == 'revoked':
                ex.revoked = True
            elif invalidation == 'generation':
                ex.generation += 1
            yield b': discarded\n\n'

    def upstream(request):
        if request.url.path == '/v1/chat/completions':
            return httpx.Response(200, stream=InvalidatedStream(), headers={'content-type': 'text/event-stream'})
        return original(request)

    app.state.client._transport.handler = upstream
    response = generate(client, token, stream=True)
    assert response.content == b': admitted\n\n'
    assert ex.touched == admitted[0] < now[0]
    if invalidation != 'generation':
        assert token not in app.state.capabilities.executions


def test_nvidia_smi_parsing_keeps_names_and_unsupported_values():
    from heretic_gateway.app import parse_nvidia_smi
    gpus = parse_nvidia_smi('NVIDIA GeForce RTX 5070 Ti, 87, 14512, 16303, 212.40, 300.00, 63\n'
                            'Odd, Name, [N/A], 10, 20, [Not Supported], [N/A], 40\n')
    assert gpus[0] == {'name': 'NVIDIA GeForce RTX 5070 Ti', 'utilization': 87.0,
                       'memory_used_mib': 14512.0, 'memory_total_mib': 16303.0, 'power_w': 212.4,
                       'power_limit_w': 300.0, 'temperature_c': 63.0}
    assert gpus[1]['name'] == 'Odd, Name' and gpus[1]['utilization'] is None
    assert gpus[1]['power_w'] is None and gpus[1]['temperature_c'] == 40.0
    with pytest.raises(ValueError):
        parse_nvidia_smi('too, few\n')


def test_gpu_usage_requires_session_and_shares_cached_reads(tmp_path):
    calls = []

    def reader():
        calls.append(1)
        return [{'name': 'GPU', 'utilization': 50.0}]

    app = create_app(tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(200)),
                     gpu_reader=reader)
    with TestClient(app) as client:
        assert client.get('/api/heretic/gpu').status_code == 401
        client.headers['X-Heretic-Session'] = client.get('/api/heretic/session').json()['token']
        first = client.get('/api/heretic/gpu').json()
        assert first == {'available': True, 'gpus': [{'name': 'GPU', 'utilization': 50.0}]}
        assert client.get('/api/heretic/gpu').json() == first
        assert len(calls) == 1


def test_gpu_usage_reports_unavailable_without_details(tmp_path):
    def reader():
        raise RuntimeError('nvidia-smi was not found.')

    app = create_app(tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(200)),
                     gpu_reader=reader)
    with TestClient(app) as client:
        client.headers['X-Heretic-Session'] = client.get('/api/heretic/session').json()['token']
        assert client.get('/api/heretic/gpu').json() == {'available': False, 'gpus': []}
