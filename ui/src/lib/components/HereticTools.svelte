<script lang="ts">
	interface ToolEntry {
		tool: string;
		definition?: { function?: { name?: string; description?: string } };
	}

	interface ToolGroup {
		label: string;
		tools: { name: string; description: string; badge: string }[];
	}

	// Known MCP server prefixes; anything else is listed under "Other".
	const GROUPS: [string, string][] = [
		['exa_', 'Web search (Exa)'],
		['reach_backends_', 'Web pages, GitHub and YouTube'],
		['media_', 'Video downloads'],
		['filesystem_', 'Files folder'],
		['context7_', 'Coding docs (Context7)'],
		['huggingface_', 'Hugging Face'],
		['memory_', 'Memory'],
		['knowledge_', 'Documents']
	];
	const LOCAL = ['media_', 'filesystem_', 'memory_', 'knowledge_'];
	const ALWAYS_APPROVED = new Set([
		'filesystem_write_file',
		'filesystem_edit_file',
		'filesystem_create_directory'
	]);

	let open = $state(false);
	let groups = $state<ToolGroup[]>([]);
	let error = $state('');
	let loading = $state(false);

	function badge(name: string): string {
		if (ALWAYS_APPROVED.has(name)) return 'asks approval';
		return LOCAL.some((prefix) => name.startsWith(prefix)) ? 'on PC' : 'online';
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const response = await fetch('/tools');
			if (!response.ok) throw new Error(`Tools are unavailable (HTTP ${response.status}).`);
			const entries: ToolEntry[] = await response.json();
			const byLabel = new Map<string, ToolGroup>();
			for (const entry of entries) {
				const name = entry.definition?.function?.name ?? entry.tool;
				const label = GROUPS.find(([prefix]) => name.startsWith(prefix))?.[1] ?? 'Other';
				const description = (entry.definition?.function?.description ?? '').split('\n')[0].trim();
				if (!byLabel.has(label)) byLabel.set(label, { label, tools: [] });
				byLabel.get(label)!.tools.push({ name, description, badge: badge(name) });
			}
			const order = [...GROUPS.map(([, label]) => label), 'Other'];
			groups = [...byLabel.values()].sort(
				(a, b) => order.indexOf(a.label) - order.indexOf(b.label)
			);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	function toggle() {
		open = !open;
		if (open) load();
	}
</script>

<button class="tools-launch" aria-expanded={open} aria-controls="heretic-tools" onclick={toggle}
	>Tools</button
>
{#if open}
	<section id="heretic-tools" class="tools-panel" aria-label="Heretic tools">
		<header>
			<h2>Available tools</h2>
			<button onclick={() => (open = false)} aria-label="Close tools">✕</button>
		</header>
		<p class="note">
			"Online" tools send your request to an internet service. Once a chat uses private memory,
			documents or files, each online request asks for approval first. File writes always do.
		</p>
		{#if loading}<p>Loading…</p>{/if}
		{#if error}<p role="alert">{error}</p>{/if}
		{#each groups as group (group.label)}
			<h3>{group.label} <span class="count">{group.tools.length}</span></h3>
			<ul>
				{#each group.tools as tool (tool.name)}
					<li>
						<code>{tool.name}</code>
						<span class="badge" data-kind={tool.badge}>{tool.badge}</span>
						{#if tool.description}<p>{tool.description}</p>{/if}
					</li>
				{/each}
			</ul>
		{/each}
	</section>
{/if}

<style>
	.tools-launch {
		position: fixed;
		/* Sits below the Memory button. */
		right: 1rem;
		top: 4rem;
		z-index: 40;
		padding: 0.5rem 1rem;
		background: var(--background);
		border: 1px solid var(--border);
		border-radius: 0.5rem;
	}
	.tools-panel {
		position: fixed;
		right: 1rem;
		top: 7rem;
		bottom: 1rem;
		width: min(32rem, calc(100vw - 2rem));
		overflow: auto;
		z-index: 45;
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
		margin: 0.75rem 0 0.5rem;
	}
	.note,
	li p {
		font-size: 0.85rem;
		opacity: 0.8;
	}
	.count {
		font-weight: 400;
		opacity: 0.6;
	}
	li {
		margin: 0.5rem 0;
		overflow-wrap: anywhere;
	}
	.badge {
		margin-left: 0.4rem;
		padding: 0 0.4rem;
		border: 1px solid var(--border);
		border-radius: 0.25rem;
		font-size: 0.75rem;
	}
	.badge[data-kind='asks approval'] {
		border-color: #d97706;
		color: #d97706;
	}
</style>
