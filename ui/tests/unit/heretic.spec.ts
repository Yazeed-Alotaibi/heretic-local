import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/environment', () => ({ browser: true }));
import { HereticService } from '../../src/lib/services/heretic.service';

const storage = new Map<string, string>();
const fetchMock = vi.fn();
afterEach(() => vi.useRealTimers());

beforeEach(() => {
	storage.clear();
	vi.stubGlobal('localStorage', {
		getItem: (key: string) => storage.get(key) ?? null,
		setItem: (key: string, value: string) => storage.set(key, value)
	});
	vi.stubGlobal('fetch', fetchMock);
	fetchMock.mockReset();
	fetchMock.mockImplementation(
		async (url: string) =>
			new Response(
				JSON.stringify(
					url.endsWith('/session')
						? { token: 'session-test' }
						: { execution_token: 'execution-test' }
				),
				{ status: 200 }
			)
	);
	HereticService.clearExecution('conversation-test');
	HereticService.approve = undefined;
});

describe('Heretic execution boundary', () => {
	it('polls loading health sequentially and stops after model readiness', async () => {
		vi.useFakeTimers();
		const status = vi.fn();
		fetchMock.mockResolvedValueOnce(
			new Response(JSON.stringify({ model: 'loading', memory: 'ready' }))
		);
		fetchMock.mockResolvedValueOnce(
			new Response(JSON.stringify({ model: 'ready', memory: 'ready' }))
		);
		const stop = HereticService.watchStartup(status);
		await vi.advanceTimersByTimeAsync(0);
		expect(status).toHaveBeenLastCalledWith('loading', true);
		await vi.advanceTimersByTimeAsync(3000);
		expect(status).toHaveBeenLastCalledWith('ready', true);
		await vi.advanceTimersByTimeAsync(9000);
		expect(fetchMock).toHaveBeenCalledTimes(2);
		stop();
	});

	it('reports unreachable health without dialogs and cancels retries on cleanup', async () => {
		vi.useFakeTimers();
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
		const status = vi.fn();
		const stop = HereticService.watchStartup(status);
		await vi.advanceTimersByTimeAsync(0);
		expect(status).toHaveBeenCalledWith('unavailable', false);
		stop();
		await vi.advanceTimersByTimeAsync(9000);
		expect(fetchMock).toHaveBeenCalledOnce();
		expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
	});

	it('automatically permits exactly the five approved local memory tools', () => {
		for (const name of [
			'memory_search',
			'memory_read',
			'memory_propose',
			'knowledge_search',
			'knowledge_read'
		])
			expect(HereticService.isAutomaticLocalTool(name)).toBe(true);
		for (const name of [
			'web_search',
			'web_fetch',
			'read_file',
			'memory_write',
			'memory_read_extra',
			'MEMORY_READ'
		])
			expect(HereticService.isAutomaticLocalTool(name)).toBe(false);
		const source = readFileSync(
			new URL('../../src/lib/stores/agentic/index.svelte.ts', import.meta.url),
			'utf8'
		);
		expect(source).toMatch(
			/HereticService\.isAutomaticLocalTool\(toolName\)\s+\? ToolPermissionDecision\.ONCE\s+: await this\.gates\.requestPermission/
		);
	});

	it('forgets cached canonical save payloads only after a successful delete', async () => {
		const session = new Map<string, string>();
		vi.stubGlobal('sessionStorage', {
			getItem: (key: string) => session.get(key) ?? null,
			setItem: (key: string, value: string) => session.set(key, value),
			removeItem: (key: string) => session.delete(key)
		});
		await HereticService.request('/records', {
			method: 'POST',
			body: JSON.stringify({ content: 'forget private fact', scope: 'global' })
		});
		expect(session.get('heretic.record-requests')).toContain('forget private fact');
		fetchMock.mockResolvedValueOnce(
			new Response(JSON.stringify({ detail: 'revision mismatch' }), { status: 409 })
		);
		await expect(
			HereticService.request('/records/test-record', { method: 'DELETE' })
		).rejects.toThrow('revision mismatch');
		expect(session.get('heretic.record-requests')).toContain('forget private fact');
		await HereticService.request('/records/test-record', { method: 'DELETE' });
		expect(session.has('heretic.record-requests')).toBe(false);
		vi.unstubAllGlobals();
	});

	it('reuses a record save identity after network failure while edits get a new identity', async () => {
		const session = new Map<string, string>();
		vi.stubGlobal('sessionStorage', {
			getItem: (key: string) => session.get(key) ?? null,
			setItem: (key: string, value: string) => session.set(key, value),
			removeItem: (key: string) => session.delete(key)
		});
		let fail = true;
		fetchMock.mockImplementation(async (url: string) => {
			if (url.endsWith('/session')) return new Response(JSON.stringify({ token: 'session-test' }));
			if (fail) {
				fail = false;
				throw new TypeError('Failed to fetch');
			}
			return new Response(JSON.stringify({ id: 'saved' }));
		});
		const first = { content: 'retry fact', scope: 'global', source: 'user' };
		await expect(
			HereticService.request('/records', { method: 'POST', body: JSON.stringify(first) })
		).rejects.toThrow('Failed to fetch');
		await HereticService.request('/records', {
			method: 'POST',
			body: JSON.stringify({ source: 'user', scope: 'global', content: 'retry fact' })
		});
		await HereticService.request('/records', {
			method: 'POST',
			body: JSON.stringify({ ...first, content: 'edited retry fact' })
		});
		const calls = fetchMock.mock.calls
			.filter(([url]) => url.endsWith('/records'))
			.map(([, options]) => JSON.parse(options.body));
		expect(calls[0].request_id).toBe(calls[1].request_id);
		expect(calls[2].request_id).not.toBe(calls[1].request_id);
		expect(session.get('heretic.record-requests')).toContain(calls[0].request_id);
		fetchMock.mockImplementation(
			async (url: string) =>
				new Response(
					JSON.stringify(
						url.endsWith('/session') ? { token: 'renewed-session' } : { detail: 'session expired' }
					),
					{ status: url.endsWith('/session') ? 200 : 401 }
				)
		);
		await expect(
			HereticService.request('/records', { method: 'POST', body: JSON.stringify(first) })
		).rejects.toThrow('session expired');
		fetchMock.mockImplementation(
			async (url: string) =>
				new Response(
					JSON.stringify(url.endsWith('/session') ? { token: 'session-test' } : { id: 'saved' })
				)
		);
		await HereticService.request('/records', { method: 'POST', body: JSON.stringify(first) });
		const retries = fetchMock.mock.calls.filter(([url]) => url.endsWith('/records'));
		expect(JSON.parse(retries[retries.length - 1][1].body).request_id).toBe(calls[0].request_id);
		vi.unstubAllGlobals();
	});

	it('agentic denial records gateway status before producing the denied tool result', () => {
		const source = readFileSync(
			new URL('../../src/lib/stores/agentic/index.svelte.ts', import.meta.url),
			'utf8'
		);
		expect(source).toMatch(
			/if \(permission === ToolPermissionDecision\.DENY\) \{\s+await HereticService\.denyCall\(conversationId, toolCall\.id, signal\);\s+result = 'Tool execution was denied by the user\.'/
		);
	});
	it('attests a denied browser permission without dispatching the tool', async () => {
		await HereticService.register(
			'conversation-test',
			[{ id: 'human', role: 'user', content: 'text' }],
			'assistant'
		);
		const signal = new AbortController().signal;
		await HereticService.denyCall('conversation-test', 'denied-call', signal);
		const call = fetchMock.mock.calls.find(([url]) => url.endsWith('/calls/denied-call/deny'))!;
		expect(call[1]).toMatchObject({ method: 'POST', body: '{}', signal });
		expect(call[1].headers['X-Heretic-Session']).toBe('session-test');
		expect(fetchMock.mock.calls.some(([url]) => url === '/tools')).toBe(false);
	});

	it('keeps recall enabled in a private conversation and preserves an explicit off choice', async () => {
		fetchMock.mockImplementation(
			async (url: string) =>
				new Response(
					JSON.stringify(
						url.endsWith('/session')
							? { token: 'session-test' }
							: { project: 'global', private_context: true, memory_enabled: true }
					),
					{ status: 200 }
				)
		);
		expect((await HereticService.authoritativePreference('conversation-test')).memory_enabled).toBe(
			true
		);
		HereticService.setPreference('conversation-test', {
			project: 'global',
			memory_enabled: false,
			locked: true
		});
		fetchMock.mockImplementation(
			async (url: string) =>
				new Response(
					JSON.stringify(
						url.endsWith('/session')
							? { token: 'session-test' }
							: { project: 'global', private_context: true, memory_enabled: true }
					),
					{ status: 200 }
				)
		);
		expect((await HereticService.authoritativePreference('conversation-test')).memory_enabled).toBe(
			false
		);
	});

	it('registers the latest persisted human, distinct from assistant identity', async () => {
		await HereticService.register(
			'conversation-test',
			[
				{ id: 'old-human', role: 'user', content: 'old' },
				{ id: 'old-assistant', role: 'assistant', content: 'answer' },
				{ id: 'latest-human', role: 'user', content: 'Remember: exact text' }
			],
			'new-assistant'
		);
		const call = fetchMock.mock.calls.find(([url]) => url.endsWith('/executions'))!;
		expect(JSON.parse(call[1].body)).toMatchObject({
			human_message_id: 'latest-human',
			assistant_execution_id: 'new-assistant',
			human_text: 'Remember: exact text',
			human_revision: 'Remember: exact text',
			project: 'global',
			memory_enabled: true,
			has_history: true
		});
		expect(call[1].headers['X-Heretic-Session']).toBe('session-test');
		expect(() =>
			HereticService.setPreference('conversation-test', { project: 'other', memory_enabled: true })
		).toThrow('Start a new conversation');
	});

	it('retries an approved tool with identical execution token, call id and args', async () => {
		let tools = 0;
		fetchMock.mockImplementation(async (url: string) => {
			if (url === '/tools' && tools++ === 0)
				return new Response(
					JSON.stringify({
						detail: {
							code: 'approval_required',
							approval_id: 'approval-test',
							tool: 'web_search',
							params: { query: 'exact query' }
						}
					}),
					{ status: 409 }
				);
			return new Response(JSON.stringify({ plain_text: 'result' }), { status: 200 });
		});
		HereticService.approve = vi.fn().mockResolvedValue(true);
		await HereticService.tool(
			'web_search',
			{ query: 'exact query' },
			'execution-test',
			'call-test'
		);
		const calls = fetchMock.mock.calls.filter(([url]) => url === '/tools');
		expect(calls).toHaveLength(2);
		expect(calls[0][1].body).toBe(calls[1][1].body);
		expect(JSON.parse(calls[0][1].body)).toEqual({
			tool: 'web_search',
			params: { query: 'exact query' },
			execution_token: 'execution-test',
			tool_call_id: 'call-test'
		});
		expect(HereticService.approve).toHaveBeenCalledWith(
			expect.objectContaining({ approval_id: 'approval-test' }),
			undefined
		);
	});

	it('denial never retries the tool', async () => {
		fetchMock.mockImplementation(
			async (url: string) =>
				new Response(
					JSON.stringify(
						url === '/tools'
							? {
									detail: {
										code: 'approval_required',
										approval_id: 'denied',
										tool: 'web_fetch',
										params: { url: 'https://example.com' }
									}
								}
							: {}
					),
					{ status: url === '/tools' ? 409 : 200 }
				)
		);
		HereticService.approve = vi.fn().mockResolvedValue(false);
		const result = await HereticService.tool(
			'web_fetch',
			{ url: 'https://example.com' },
			'execution-test',
			'call-test'
		);
		expect(result.error).toContain('denied');
		expect(fetchMock.mock.calls.filter(([url]) => url === '/tools')).toHaveLength(1);
	});

	it('clears active capability on cancellation and asks gateway to revoke it', async () => {
		await HereticService.register(
			'conversation-test',
			[{ id: 'human', role: 'user', content: 'text' }],
			'assistant'
		);
		await HereticService.cancel('conversation-test');
		expect(HereticService.execution('conversation-test')).toBeUndefined();
		expect(
			fetchMock.mock.calls.some(
				([url, options]) =>
					url.endsWith('/executions/execution-test') && options.method === 'DELETE'
			)
		).toBe(true);
	});

	it('queues concurrent approvals without replacing the pending decision', async () => {
		fetchMock.mockImplementation(
			async (url: string) =>
				new Response(
					JSON.stringify(
						url === '/tools'
							? {
									detail: {
										code: 'approval_required',
										approval_id: 'pending',
										tool: 'web_search',
										params: {}
									}
								}
							: {}
					),
					{ status: url === '/tools' ? 409 : 200 }
				)
		);
		let decide: (value: boolean) => void = () => {};
		HereticService.approve = vi.fn().mockImplementation(
			() =>
				new Promise<boolean>((resolve) => {
					decide = resolve;
				})
		);
		const first = HereticService.tool('web_search', {}, 'first-execution', 'first-call');
		await vi.waitFor(() => expect(HereticService.approve).toHaveBeenCalledOnce());
		const second = HereticService.tool('web_search', {}, 'second-execution', 'second-call');
		await new Promise((resolve) => setTimeout(resolve, 10));
		expect(HereticService.approve).toHaveBeenCalledOnce();
		decide(false);
		expect((await first).error).toContain('denied');
		await vi.waitFor(() => expect(HereticService.approve).toHaveBeenCalledTimes(2));
		decide(false);
		expect((await second).error).toContain('denied');
	});
});
