import { HereticService, type MemoryRecord } from './heretic.service';

export interface MemoryPanelTarget {
	conversationId: string;
	scope: string;
	generation: number;
}

export class MemoryPanelService {
	private target: MemoryPanelTarget = { conversationId: '', scope: '', generation: 0 };

	select(conversationId: string, scope: string): boolean {
		if (conversationId === this.target.conversationId && scope === this.target.scope) return false;
		this.target = { conversationId, scope, generation: this.target.generation + 1 };
		return true;
	}

	capture(): MemoryPanelTarget {
		return { ...this.target };
	}

	current(target: MemoryPanelTarget): boolean {
		return (
			target.generation === this.target.generation &&
			target.conversationId === this.target.conversationId &&
			target.scope === this.target.scope
		);
	}

	static correction(record: MemoryRecord, target: MemoryPanelTarget): Record<string, unknown> {
		return {
			record_id: record.id,
			expected_revision: record.revision,
			content: record.content,
			scope: record.scope ?? target.scope,
			kind: record.kind ?? 'fact',
			source: 'user'
		};
	}

	static export(): Promise<{ path: string }> {
		return HereticService.request('/export', { method: 'POST', body: '{}' });
	}
}
