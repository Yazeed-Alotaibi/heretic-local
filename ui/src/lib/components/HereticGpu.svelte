<script lang="ts">
	import { type GpuStats, type GpuUsage, HereticService } from '$lib/services/heretic.service';
	import { onMount } from 'svelte';

	let usage = $state<GpuUsage | null>(null);

	onMount(() => HereticService.watchGpu((next) => (usage = next)));

	function gigabytes(mib: number | null): string {
		return mib === null ? '?' : (mib / 1024).toFixed(1);
	}

	function describe(gpu: GpuStats): string {
		const parts = [
			gpu.name,
			gpu.utilization === null ? null : `${Math.round(gpu.utilization)}% load`,
			`${gigabytes(gpu.memory_used_mib)} of ${gigabytes(gpu.memory_total_mib)} GB memory`,
			gpu.power_w === null
				? null
				: `${Math.round(gpu.power_w)} W` +
					(gpu.power_limit_w === null ? '' : ` of ${Math.round(gpu.power_limit_w)} W`),
			gpu.temperature_c === null ? null : `${Math.round(gpu.temperature_c)} °C`
		];

		return parts.filter(Boolean).join(', ');
	}
</script>

{#if usage?.available && usage.gpus.length}
	{@const gpu = usage.gpus[0]}
	<div class="gpu-usage" role="status" aria-live="off" title={usage.gpus.map(describe).join('\n')}>
		<span>GPU {gpu.utilization === null ? '?' : Math.round(gpu.utilization)}%</span>
		<span>{gigabytes(gpu.memory_used_mib)}/{gigabytes(gpu.memory_total_mib)} GB</span>
		{#if gpu.power_w !== null}<span class="extra">{Math.round(gpu.power_w)} W</span>{/if}
		{#if gpu.temperature_c !== null}<span class="extra">{Math.round(gpu.temperature_c)}°C</span
			>{/if}
	</div>
{/if}

<style>
	.gpu-usage {
		position: fixed;
		/* Sits left of the Memory button and matches its height. */
		right: 8rem;
		top: 1rem;
		z-index: 40;
		display: flex;
		gap: 0.6rem;
		padding: 0.5rem 0.75rem;
		line-height: 1.5rem;
		background: var(--background);
		color: var(--foreground);
		border: 1px solid var(--border);
		border-radius: 0.5rem;
		font-size: 0.85rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	@media (max-width: 640px) {
		.extra {
			display: none;
		}
	}
</style>
