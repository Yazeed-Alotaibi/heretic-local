"""Ephemeral, invocation-bound capabilities. No authority survives a restart."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass
class Execution:
    token: str
    session: str
    conversation_id: str
    human_message_id: str
    human_text: str
    human_revision: str
    assistant_execution_id: str
    scope: str
    memory_enabled: bool
    private_context: bool
    touched: float = field(default_factory=time.monotonic)
    snapshot: list[dict] | None = None
    prefix_hash: str | None = None
    token_count: int = 0
    records: list[dict] = field(default_factory=list)
    revoked: bool = False
    calls: dict[str, dict] = field(default_factory=dict)
    generation: int = 0
    stream_id: str = ''
    client_stream_id: str = ''
    completion_started: bool = False
    memory_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class State:
    def __init__(self):
        self.sessions: dict[str, float] = {}
        self.executions: dict[str, Execution] = {}
        self.approvals: dict[str, dict] = {}
        self.proposals: dict[str, dict] = {}

    def sweep(self):
        now = time.monotonic()
        self.sessions = {k: v for k, v in self.sessions.items() if now - v < 86400}
        self.executions = {
            k: v for k, v in self.executions.items()
            if not v.revoked and now - v.touched < 1800 and v.session in self.sessions
        }
        for collection in (self.approvals, self.proposals):
            expired = [k for k, v in collection.items()
                       if now - v['created'] >= 900 or v['execution'] not in self.executions]
            for key in expired:
                del collection[key]

    def session(self) -> str:
        self.sweep()
        token = secrets.token_urlsafe(32)
        self.sessions[token] = time.monotonic()
        return token

    def execution(self, token: str, session: str) -> Execution:
        self.sweep()
        execution = self.executions.get(token)
        if execution is None or execution.session != session:
            raise ValueError('Execution expired; start the turn again.')
        execution.touched = time.monotonic()
        return execution

    def revoke(self, conversation_id: str | None = None):
        for execution in self.executions.values():
            if conversation_id is None or execution.conversation_id == conversation_id:
                execution.revoked = True
        self.sweep()


class ToolCollector:
    """Observe SSE on a copy; the forwarding path yields the original bytes."""

    def __init__(self, execution: Execution, generation: int | None = None):
        self.execution = execution
        self.generation = execution.generation if generation is None else generation
        self.buffer = b''
        self.fragments: dict[int, dict] = {}

    def consume(self, chunk: bytes):
        self.buffer += chunk
        if len(self.buffer) > 2 * 1024 * 1024:
            raise ValueError('Model event exceeds the safe size limit.')
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line.startswith(b'data:'):
                continue
            payload = line[5:].strip()
            if payload == b'[DONE]':
                self.finish()
                continue
            try:
                obj = json.loads(payload)
            except (ValueError, UnicodeDecodeError):
                continue
            self.observe(obj)

    def observe(self, obj: dict):
        for choice in obj.get('choices', []):
            delta = choice.get('delta') or choice.get('message') or {}
            for index, call in enumerate(delta.get('tool_calls', [])):
                entry = self.fragments.setdefault(call.get('index', index),
                                                  {'id': '', 'name': '', 'arguments': ''})
                if call.get('id'):
                    entry['id'] = call['id']
                fn = call.get('function') or {}
                entry['name'] += fn.get('name', '')
                entry['arguments'] += fn.get('arguments', '')
                if len(entry['arguments']) > 131072:
                    raise ValueError('Tool arguments exceed the safe size limit.')
            if choice.get('finish_reason'):
                self.finish()

    def finish(self):
        if self.execution.revoked or self.execution.generation != self.generation:
            return
        for entry in self.fragments.values():
            prior = self.execution.calls.get(entry['id'])
            if not entry['id'] or prior and prior.get('generation') == self.generation:
                continue
            try:
                params = json.loads(entry['arguments'])
            except ValueError:
                continue
            self.execution.calls[entry['id']] = {
                'tool': entry['name'], 'params': params, 'status': 'new',
                'generation': self.generation,
            }
