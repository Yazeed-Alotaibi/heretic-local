<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { MemoryPanelService, type MemoryPanelTarget } from '$lib/services/memory-panel.service';
	import { conversationsStore } from '$lib/stores/conversations/index.svelte';
	import {
		HereticService,
		HereticError,
		type MemoryRecord,
		type MemoryContext,
		type ToolApproval
	} from '$lib/services/heretic.service';

	let { initialOpen = false } = $props<{ initialOpen?: boolean }>();
	let open = $state(untrack(() => initialOpen));
	let error = $state('');
	let busy = $state(false);
	let scope = $state('global');
	let memoryEnabled = $state(true);
	let locked = $state(false);
	let records = $state<MemoryRecord[]>([]);
	let proposals = $state<MemoryRecord[]>([]);
	let projects = $state<{ id: string; name: string; archived?: boolean }[]>([]);
	let documents = $state<{ id: string; filename: string }[]>([]);
	let context = $state<MemoryContext | null>(null);
	let content = $state('');
	let kind = $state('checkpoint');
	let projectName = $state('');
	let notice = $state('');
	let startupStatus = $state('Checking Heretic…');
	let approval = $state<ToolApproval | null>(null);
	let approvalDialog: HTMLDialogElement;
	let resolveApproval: ((decision: boolean) => void) | undefined;
	let clearApprovalListener: (() => void) | undefined;
	let focused: HTMLElement | null = null;
	const panel = new MemoryPanelService();
	const conversationId = $derived(conversationsStore.activeConversation?.id ?? 'new');

	$effect(() => {
		const id = conversationId;
		const preference = HereticService.preference(id);
		untrack(() => {
			if (select(id, preference.project) && open) void run(refresh);
		});
		scope = preference.project;
		memoryEnabled = preference.memory_enabled;
		locked =
			preference.locked ??
			conversationsStore.activeMessages.some((message) => message.role === 'user');
	});

	onMount(() => {
		const stopStartup = HereticService.watchStartup((status, memoryReady) => {
			startupStatus =
				status === 'ready'
					? ''
					: status === 'unavailable'
						? 'Heretic gateway is unavailable. Retrying…'
						: memoryReady
							? 'Model loading… Your saved memory is ready.'
							: 'Model loading… Memory is starting.';
		});
		HereticService.approve = (request, signal) =>
			new Promise<boolean>((resolve) => {
				focused = document.activeElement as HTMLElement;
				approval = request;
				resolveApproval = resolve;
				approvalDialog.showModal();
				const abort = () => decide(false);
				if (signal?.aborted) abort();
				else {
					signal?.addEventListener('abort', abort, { once: true });
					clearApprovalListener = () => signal?.removeEventListener('abort', abort);
				}
			});
		return () => {
			stopStartup();
			decide(false);
			HereticService.approve = undefined;
		};
	});

	function decide(decision: boolean) {
		clearApprovalListener?.();
		clearApprovalListener = undefined;
		resolveApproval?.(decision);
		resolveApproval = undefined;
		approval = null;
		approvalDialog?.close();
		focused?.focus();
	}

	function select(id: string, project: string) {
		if (!panel.select(id, project)) return false;
		records = [];
		documents = [];
		proposals = [];
		context = null;
		content = '';
		projectName = '';
		notice = '';
		error = '';
		busy = false;
		return true;
	}

	async function run(action: (target: MemoryPanelTarget) => Promise<void>) {
		const target = panel.capture();
		busy = true;
		error = '';
		try {
			await action(target);
		} catch (failure) {
			if (panel.current(target))
				error = failure instanceof Error ? failure.message : String(failure);
		} finally {
			if (panel.current(target)) busy = false;
		}
	}

	async function refresh(target = panel.capture()) {
		const preference = await HereticService.authoritativePreference(target.conversationId);
		if (!panel.current(target)) return;
		if (preference.project !== target.scope) {
			select(target.conversationId, preference.project);
			target = panel.capture();
		}
		scope = target.scope;
		memoryEnabled = preference.memory_enabled;
		locked = preference.locked ?? locked;
		const execution = HereticService.receipt(target.conversationId);
		const values = await Promise.all([
			HereticService.request<MemoryRecord[]>(`/records?scope=${encodeURIComponent(target.scope)}`),
			HereticService.request<typeof projects>('/projects'),
			HereticService.request<typeof documents>(
				`/knowledge?scope=${encodeURIComponent(target.scope)}`
			)
		]);
		if (!panel.current(target)) return;
		[records, projects, documents] = values;
		proposals = [];
		context = null;
		if (execution) {
			try {
				const nextProposals = await HereticService.request<MemoryRecord[]>(
					`/proposals?execution_token=${encodeURIComponent(execution.execution_token)}`
				);
				const nextContext = await HereticService.request<MemoryContext>(
					`/context/${encodeURIComponent(execution.execution_token)}`
				);
				if (!panel.current(target)) return;
				proposals = nextProposals;
				context = nextContext;
			} catch (failure) {
				if (!panel.current(target)) return;
				if (!(failure instanceof HereticError) || failure.status !== 409) throw failure;
				notice =
					'Recall and suggestions expired after a memory change. Start a new human turn to refresh them.';
			}
		}
	}

	function preference() {
		select(conversationId, scope);
		HereticService.setPreference(conversationId, {
			project: scope,
			memory_enabled: memoryEnabled,
			locked
		});
	}

	async function upload(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		await run(async (target) => {
			await HereticService.request('/knowledge', {
				method: 'POST',
				body: await file.arrayBuffer(),
				headers: {
					'Content-Type': 'application/octet-stream',
					'X-Filename': encodeURIComponent(file.name),
					'X-Scope': target.scope
				}
			});
			if (panel.current(target)) input.value = '';
			if (panel.current(target)) await refresh(target);
		});
	}
</script>

{#if startupStatus}<div class="startup-status" role="status">{startupStatus}</div>{/if}

<button
	class="memory-launch"
	onclick={() => {
		open = !open;
		if (open) void run(refresh);
	}}
	aria-expanded={open}
	aria-controls="heretic-memory">Memory</button
>
{#if open}
	<section id="heretic-memory" class="memory-panel" aria-label="Heretic memory">
		<header>
			<h2>Memory and knowledge</h2>
			<button onclick={() => (open = false)} aria-label="Close memory">Close</button>
		</header>
		<p>Memory choices apply to the next human turn. Recall uses up to 4096 tokens.</p>
		<label
			><input type="checkbox" bind:checked={memoryEnabled} onchange={preference} /> Use memory for this
			conversation</label
		>
		<label
			>Project <select
				bind:value={scope}
				disabled={locked || busy}
				onchange={() => {
					preference();
					void run(refresh);
				}}
			>
				<option value="global">Global</option
				>{#each projects.filter((project) => !project.archived) as project}<option
						value={project.id}>{project.name}</option
					>{/each}
			</select></label
		>
		{#if locked}<p>
				The project is locked after the first human message. Start a new conversation to choose
				another project.
			</p>{/if}
		{#if context}<p>
				Recall: {context.token_count} / {context.budget} tokens. Records used: {context.records
					.map((record) => record.id)
					.join(', ') || 'none'}.
			</p>{/if}
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void run(async (target) => {
					await HereticService.request('/projects', {
						method: 'POST',
						body: JSON.stringify({ name: projectName })
					});
					if (panel.current(target)) projectName = '';
					if (panel.current(target)) await refresh(target);
				});
			}}
		>
			<label>New project <input bind:value={projectName} required /></label><button disabled={busy}
				>Create project</button
			>
		</form>
		{#if scope !== 'global'}<button
				disabled={busy}
				onclick={() =>
					run(async (target) => {
						await HereticService.request(`/projects/${target.scope}/archive`, { method: 'POST' });
						if (panel.current(target)) await refresh(target);
					})}>Archive project</button
			>{/if}
		<h3>Saved records</h3>
		{#each records as record (record.id)}
			<form
				onsubmit={(event) => {
					event.preventDefault();
					void run(async (target) => {
						await HereticService.request('/records', {
							method: 'POST',
							body: JSON.stringify(MemoryPanelService.correction(record, target))
						});
						if (panel.current(target)) await refresh(target);
					});
				}}
			>
				<label>Record {record.id}<textarea bind:value={record.content} required></textarea></label>
				<button disabled={busy}>Save correction</button>
				<button
					type="button"
					disabled={busy}
					onclick={() =>
						run(async (target) => {
							await HereticService.request(
								`/records/${record.id}?revision=${record.revision ?? ''}`,
								{ method: 'DELETE' }
							);
							if (panel.current(target)) await refresh(target);
						})}>Delete record</button
				>
			</form>
		{/each}
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void run(async (target) => {
					await HereticService.request('/records', {
						method: 'POST',
						body: JSON.stringify({
							content,
							scope: target.scope,
							kind,
							source: 'user',
							derived_from:
								context?.records
									.map((record) => record.id)
									.filter((id) => /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(id)) ?? []
						})
					});
					if (panel.current(target)) content = '';
					if (panel.current(target)) await refresh(target);
				});
			}}
		>
			<label
				>Record kind <select bind:value={kind}
					><option value="checkpoint">Checkpoint</option><option value="preference"
						>Preference</option
					><option value="fact">Fact</option></select
				></label
			>
			<label>Explicit memory record <textarea bind:value={content} required></textarea></label
			><button disabled={busy}>Save memory record</button>
		</form>
		<h3>Suggestions</h3>
		<p>Suggestions enter durable memory only when you save them.</p>
		{#each proposals as proposal (proposal.id)}
			<form
				onsubmit={(event) => {
					event.preventDefault();
					void run(async (target) => {
						await HereticService.request(`/proposals/${proposal.id}/save`, {
							method: 'POST',
							body: JSON.stringify({
								content: proposal.content,
								expected_revision: proposal.revision
							})
						});
						if (panel.current(target)) await refresh(target);
					});
				}}
			>
				<label>Review suggestion<textarea bind:value={proposal.content} required></textarea></label
				><button disabled={busy}>Save suggestion</button>
			</form>
		{/each}
		<h3>Knowledge documents</h3>
		<label>Upload document<input type="file" onchange={upload} disabled={busy} /></label>
		{#each documents as doc (doc.id)}
			<p>
				{doc.filename}
				<button
					disabled={busy}
					onclick={() =>
						run(async (target) => {
							const result = await HereticService.request(
								`/knowledge/${doc.id}?scope=${encodeURIComponent(target.scope)}`
							);
							if (panel.current(target)) notice = JSON.stringify(result);
						})}>Read</button
				>
				<button
					disabled={busy}
					onclick={() =>
						run(async (target) => {
							await HereticService.request(`/knowledge/${doc.id}`, { method: 'DELETE' });
							if (panel.current(target)) await refresh(target);
						})}>Delete document</button
				>
			</p>
		{/each}
		<button disabled={busy} onclick={() => run(refresh)}>Refresh memory</button>
		<button
			disabled={busy}
			onclick={() =>
				run(async (target) => {
					await HereticService.request('/reload', { method: 'POST' });
					if (panel.current(target)) notice = 'Memory reloaded.';
					if (panel.current(target)) await refresh(target);
				})}>Reload memory</button
		>
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void run(async (target) => {
					const result = await MemoryPanelService.export();
					if (panel.current(target)) notice = `Exported to ${result.path}`;
				});
			}}
		>
			<p>Exports are saved under ~/.heretic/data/exports.</p>
			<button disabled={busy}>Export memory</button>
		</form>
		<button
			disabled={busy}
			onclick={() =>
				run(async (target) => {
					const result = await HereticService.request('/health');
					if (panel.current(target)) notice = JSON.stringify(result);
				})}>Check memory health</button
		>
		<p>
			Direct MCP, custom tools, browser tools and remote media are disabled. Tools run through the
			local Heretic gateway.
		</p>
		{#if error}<p role="alert">{error}</p>{/if}{#if notice}<pre
				aria-live="polite">{notice}</pre>{/if}
	</section>
{/if}
<dialog
	bind:this={approvalDialog}
	oncancel={(event) => {
		event.preventDefault();
		decide(false);
	}}
	aria-labelledby="tool-approval-title"
>
	<h2 id="tool-approval-title">Approve exact tool action</h2>
	{#if approval}<p>{approval.tool}</p>
		<pre>{JSON.stringify(approval.params, null, 2)}</pre>{/if}
	<button onclick={() => decide(false)}>Deny</button><button onclick={() => decide(true)}
		>Approve once</button
	>
</dialog>

<style>
	.startup-status {
		position: fixed;
		top: 4rem;
		left: 50%;
		transform: translateX(-50%);
		z-index: 30;
		max-width: calc(100vw - 2rem);
		padding: 0.5rem 1rem;
		border: 1px solid var(--border);
		border-radius: 0.5rem;
		background: var(--background);
		color: var(--foreground);
	}
	.memory-launch {
		position: fixed;
		right: 1rem;
		top: 1rem;
		z-index: 40;
		padding: 0.5rem 1rem;
		background: var(--background);
		border: 1px solid var(--border);
		border-radius: 0.5rem;
	}
	.memory-panel {
		position: fixed;
		right: 1rem;
		top: 4rem;
		bottom: 1rem;
		width: min(32rem, calc(100vw - 2rem));
		overflow: auto;
		z-index: 50;
		padding: 1rem;
		background: var(--background);
		color: var(--foreground);
		border: 1px solid var(--border);
		border-radius: 0.5rem;
		box-shadow: 0 8px 24px #0003;
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	h2,
	h3 {
		font-weight: 600;
		margin: 0.75rem 0;
	}
	p,
	form,
	label {
		margin: 0.5rem 0;
	}
	label {
		display: block;
	}
	textarea,
	input:not([type='checkbox']),
	select {
		display: block;
		width: 100%;
		border: 1px solid var(--border);
		border-radius: 0.25rem;
		padding: 0.5rem;
	}
	button {
		border: 1px solid var(--border);
		border-radius: 0.25rem;
		padding: 0.4rem 0.7rem;
		margin: 0.25rem;
	}
	button:disabled {
		opacity: 0.5;
	}
	pre {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	dialog {
		max-width: min(36rem, 90vw);
		padding: 1.5rem;
		background: var(--background);
		color: var(--foreground);
		border-radius: 0.5rem;
	}
	dialog::backdrop {
		background: #0008;
	}
</style>
