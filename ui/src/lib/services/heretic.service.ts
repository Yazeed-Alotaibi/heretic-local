import { browser } from '$app/environment';
import { v4 as uuid } from 'uuid';

function canonicalJson(value: unknown): string {
	if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
	if (value && typeof value === 'object') {
		return `{${Object.entries(value)
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
			.join(',')}}`;
	}
	return JSON.stringify(value);
}

export class HereticError extends Error {
	constructor(
		message: string,
		public status: number
	) {
		super(message);
	}
}

export interface MemoryPreference {
	project: string;
	memory_enabled: boolean;
	locked?: boolean;
}

export interface MemoryRecord {
	id: string;
	content: string;
	scope?: string;
	revision?: number;
	kind?: string;
}

export interface MemoryContext {
	token_count: number;
	budget: number;
	records: MemoryRecord[];
	memory_enabled: boolean;
}

export interface Execution {
	execution_token: string;
	[key: string]: unknown;
}

export interface ToolApproval {
	approval_id: string;
	tool: string;
	params: Record<string, unknown>;
}

export class HereticService {
	static watchStartup(
		onStatus: (status: 'ready' | 'loading' | 'unavailable', memoryReady: boolean) => void
	): () => void {
		const controller = new AbortController();
		let timer: ReturnType<typeof setTimeout> | undefined;
		let stopped = false;
		const check = async () => {
			let ready = false;
			try {
				const response = await fetch('/api/heretic/health', { signal: controller.signal });
				if (!response.ok) throw new Error(`Health: HTTP ${response.status}`);
				const health = (await response.json()) as { model: string; memory: string };
				ready = health.model === 'ready';
				if (!stopped) onStatus(ready ? 'ready' : 'loading', health.memory === 'ready');
			} catch {
				if (!stopped) onStatus('unavailable', false);
			}
			if (!stopped && !ready) timer = setTimeout(() => void check(), 3000);
		};
		void check();
		return () => {
			stopped = true;
			if (timer) clearTimeout(timer);
			controller.abort();
		};
	}

	static isAutomaticLocalTool(toolName: string): boolean {
		return [
			'memory_search',
			'memory_read',
			'memory_propose',
			'knowledge_search',
			'knowledge_read'
		].includes(toolName);
	}

	private static session: Promise<string> | undefined;
	private static executions = new Map<string, Execution>();
	private static receipts = new Map<string, Execution>();
	private static approvalQueue: Promise<void> = Promise.resolve();
	private static recordRequests: { body: string; id: string; created: number }[] = [];
	static approve: ((approval: ToolApproval, signal?: AbortSignal) => Promise<boolean>) | undefined;

	static async headers(): Promise<Record<string, string>> {
		if (!browser) return {};
		const saved =
			typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('heretic.session') : null;
		if (!this.session && saved) this.session = Promise.resolve(saved);
		this.session ??= fetch('/api/heretic/session')
			.then(async (response) => {
				if (!response.ok) throw new Error(`Heretic session: HTTP ${response.status}`);
				const token = ((await response.json()) as { token: string }).token;
				if (typeof sessionStorage !== 'undefined') sessionStorage.setItem('heretic.session', token);
				return token;
			})
			.catch((error) => {
				this.session = undefined;
				throw error;
			});
		return { 'X-Heretic-Session': await this.session };
	}

	static async streamHeaders(streamId: string): Promise<Record<string, string>> {
		const conversationId = streamId.split('::')[0];
		const execution = this.execution(conversationId) ?? this.receipt(conversationId);
		return {
			...(await this.headers()),
			...(execution ? { 'X-Heretic-Execution': execution.execution_token } : {})
		};
	}

	static preference(conversationId: string): MemoryPreference {
		const value = browser
			? (localStorage.getItem(`heretic.memory.${conversationId}`) ??
				(conversationId !== 'new' ? localStorage.getItem('heretic.memory.new') : null))
			: null;
		return value ? JSON.parse(value) : { project: 'global', memory_enabled: true };
	}

	static setPreference(conversationId: string, preference: MemoryPreference): void {
		const previous = this.preference(conversationId);
		if (previous.locked && previous.project !== preference.project) {
			throw new Error('Start a new conversation to change its project.');
		}
		localStorage.setItem(`heretic.memory.${conversationId}`, JSON.stringify(preference));
	}

	static execution(conversationId: string): Execution | undefined {
		if (!this.executions.has(conversationId) && typeof sessionStorage !== 'undefined') {
			const value = sessionStorage.getItem(`heretic.execution.${conversationId}`);
			if (value) this.executions.set(conversationId, JSON.parse(value));
		}
		return this.executions.get(conversationId);
	}

	static receipt(conversationId: string): Execution | undefined {
		if (!this.receipts.has(conversationId) && typeof sessionStorage !== 'undefined') {
			const value = sessionStorage.getItem(`heretic.receipt.${conversationId}`);
			if (value) this.receipts.set(conversationId, JSON.parse(value));
		}
		return this.receipts.get(conversationId);
	}

	static clearExecution(conversationId: string): void {
		this.executions.delete(conversationId);
		if (typeof sessionStorage !== 'undefined')
			sessionStorage.removeItem(`heretic.execution.${conversationId}`);
	}

	static async cancel(conversationId: string): Promise<void> {
		const execution = this.executions.get(conversationId);
		this.clearExecution(conversationId);
		this.receipts.delete(conversationId);
		if (typeof sessionStorage !== 'undefined')
			sessionStorage.removeItem(`heretic.receipt.${conversationId}`);
		if (execution)
			await this.request(`/executions/${encodeURIComponent(execution.execution_token)}`, {
				method: 'DELETE'
			});
	}

	static async authoritativePreference(conversationId: string): Promise<MemoryPreference> {
		const preference = this.preference(conversationId);
		if (conversationId === 'new') return preference;
		const binding = await this.request<{
			project: string;
			memory_enabled: boolean;
			private_context: boolean;
		} | null>(`/conversations/${encodeURIComponent(conversationId)}`);
		if (binding && typeof binding.project === 'string') {
			const effective = {
				...preference,
				project: binding.project,
				memory_enabled: localStorage.getItem(`heretic.memory.${conversationId}`)
					? preference.memory_enabled
					: binding.memory_enabled,
				locked: true
			};
			localStorage.setItem(`heretic.memory.${conversationId}`, JSON.stringify(effective));
			return effective;
		}
		return preference;
	}

	static async register(
		conversationId: string,
		messages: { role: string; content: unknown; id?: string }[],
		assistantId: string,
		signal?: AbortSignal
	): Promise<Execution> {
		const human = [...messages].reverse().find((message) => message.role === 'user');
		if (!human?.id || typeof human.content !== 'string') {
			throw new Error('A persisted human message is required for a memory execution.');
		}
		const preference = await this.authoritativePreference(conversationId);
		this.clearExecution(conversationId);
		const execution = await this.request<Execution>('/executions', {
			method: 'POST',
			signal,
			body: JSON.stringify({
				conversation_id: conversationId,
				human_message_id: human.id,
				human_revision: human.content,
				human_text: human.content,
				assistant_execution_id: assistantId,
				project: preference.project,
				memory_enabled: preference.memory_enabled,
				has_history:
					messages.filter((message) => message.role === 'user').length > 1 ||
					messages.some(
						(message) =>
							message.role === 'assistant' && message.id !== assistantId && Boolean(message.content)
					)
			})
		});
		this.executions.set(conversationId, execution);
		this.receipts.set(conversationId, execution);
		if (typeof sessionStorage !== 'undefined') {
			sessionStorage.setItem(`heretic.execution.${conversationId}`, JSON.stringify(execution));
			sessionStorage.setItem(`heretic.receipt.${conversationId}`, JSON.stringify(execution));
		}
		this.setPreference(conversationId, {
			project: typeof execution.project === 'string' ? execution.project : preference.project,
			memory_enabled:
				typeof execution.memory_enabled === 'boolean'
					? execution.memory_enabled
					: preference.memory_enabled,
			locked: true
		});
		return execution;
	}

	static async request<T>(path: string, options: RequestInit = {}): Promise<T> {
		if (path === '/records' && options.method === 'POST' && typeof options.body === 'string') {
			const payload = JSON.parse(options.body) as Record<string, unknown>;
			if (!payload.request_id) {
				const key = 'heretic.record-requests';
				const saved = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(key) : null;
				const now = Date.now();
				const requests = (
					saved ? JSON.parse(saved) : this.recordRequests
				) as typeof this.recordRequests;
				this.recordRequests = requests
					.filter((entry) => now - entry.created < 24 * 60 * 60 * 1000)
					.slice(-256);
				const body = canonicalJson(payload);
				let entry = this.recordRequests.find((candidate) => candidate.body === body);
				if (!entry) {
					entry = { body, id: uuid(), created: now };
					this.recordRequests.push(entry);
					this.recordRequests = this.recordRequests.slice(-256);
				}
				if (typeof sessionStorage !== 'undefined')
					sessionStorage.setItem(key, JSON.stringify(this.recordRequests));
				options = { ...options, body: JSON.stringify({ ...payload, request_id: entry.id }) };
			}
		}
		const response = await fetch(`/api/heretic${path}`, {
			...options,
			headers: { 'Content-Type': 'application/json', ...(await this.headers()), ...options.headers }
		});
		const result = await response.json();
		if (response.status === 401) {
			this.session = undefined;
			this.executions.clear();
			this.receipts.clear();
			if (typeof sessionStorage !== 'undefined') {
				for (const key of Object.keys(sessionStorage))
					if (key.startsWith('heretic.') && key !== 'heretic.record-requests')
						sessionStorage.removeItem(key);
			}
		}
		if (!response.ok)
			throw new HereticError(JSON.stringify(result.detail ?? result), response.status);
		if (
			options.method === 'DELETE' &&
			(path === '/records' || path.startsWith('/records/') || path.startsWith('/records?'))
		) {
			this.recordRequests = [];
			if (typeof sessionStorage !== 'undefined')
				sessionStorage.removeItem('heretic.record-requests');
		}
		return result as T;
	}

	static async denyCall(
		conversationId: string,
		toolCallId: string,
		signal?: AbortSignal
	): Promise<void> {
		const execution = this.execution(conversationId);
		if (!execution) throw new Error('Memory execution expired. Start a new human turn.');
		await this.request(
			`/executions/${encodeURIComponent(execution.execution_token)}/calls/${encodeURIComponent(toolCallId)}/deny`,
			{
				method: 'POST',
				body: '{}',
				signal
			}
		);
	}

	static async tool(
		tool: string,
		params: Record<string, unknown>,
		executionToken: string,
		toolCallId: string,
		signal?: AbortSignal
	): Promise<Record<string, unknown>> {
		const headers = await this.headers();
		const invoke = () =>
			fetch('/tools', {
				method: 'POST',
				signal,
				headers: { 'Content-Type': 'application/json', ...headers },
				body: JSON.stringify({
					tool,
					params,
					execution_token: executionToken,
					tool_call_id: toolCallId
				})
			});
		let response = await invoke();
		let result = await response.json();
		if (response.status === 409 && result.detail?.code === 'approval_required') {
			if (!this.approve) throw new Error('Approval interface is unavailable.');
			const previous = this.approvalQueue;
			let release!: () => void;
			this.approvalQueue = new Promise<void>((resolve) => {
				release = resolve;
			});
			let approve: boolean;
			await previous;
			try {
				if (signal?.aborted) throw new DOMException('Tool approval cancelled.', 'AbortError');
				approve = await this.approve(result.detail as ToolApproval, signal);
			} finally {
				release();
			}
			await this.request(`/approvals/${encodeURIComponent(result.detail.approval_id)}`, {
				method: 'POST',
				signal,
				body: JSON.stringify({ approve })
			});
			if (!approve) return { error: 'Tool execution was denied by the user.' };
			response = await invoke();
			result = await response.json();
		}
		if (!response.ok)
			throw new HereticError(JSON.stringify(result.detail ?? result), response.status);
		return result;
	}
}
