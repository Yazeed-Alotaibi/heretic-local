import { afterEach, describe, expect, it, vi } from 'vitest';
import { HereticService } from '../../src/lib/services/heretic.service';
import { MemoryPanelService } from '../../src/lib/services/memory-panel.service';

afterEach(() => vi.restoreAllMocks());

describe('Memory panel conversation isolation', () => {
	it('invalidates pending data and action targets when another chat is selected', () => {
		const panel = new MemoryPanelService();
		panel.select('conversation-a', 'project-a');
		const pending = panel.capture();
		expect(panel.select('conversation-b', 'project-b')).toBe(true);
		expect(panel.current(pending)).toBe(false);
		expect(panel.capture()).toMatchObject({ conversationId: 'conversation-b', scope: 'project-b' });
	});

	it('rejects an old response even after switching back to the original chat', async () => {
		const panel = new MemoryPanelService();
		panel.select('conversation-a', 'project-a');
		const pending = panel.capture();
		let complete!: (data: string[]) => void;
		const response = new Promise<string[]>((resolve) => { complete = resolve; });
		panel.select('conversation-b', 'project-b');
		panel.select('conversation-a', 'project-a');
		complete(['stale private record']);
		const records = await response;
		expect(panel.current(pending)).toBe(false);
		expect(records).toEqual(['stale private record']);
	});

	it('binds corrections to the saved record scope rather than the displayed project', () => {
		const panel = new MemoryPanelService();
		panel.select('conversation-b', 'project-b');
		const correction = MemoryPanelService.correction({ id: 'record-a', scope: 'project-a', content: 'corrected', revision: 7, kind: 'preference' }, panel.capture());
		expect(correction).toMatchObject({ record_id: 'record-a', scope: 'project-a', expected_revision: 7, kind: 'preference' });
	});

	it('exports without an arbitrary destination and returns the gateway path', async () => {
		const request = vi.spyOn(HereticService, 'request').mockResolvedValue({ path: '~/.heretic/data/exports/memory.json' });
		expect(await MemoryPanelService.export()).toEqual({ path: '~/.heretic/data/exports/memory.json' });
		expect(request).toHaveBeenCalledExactlyOnceWith('/export', { method: 'POST', body: '{}' });
	});
});
