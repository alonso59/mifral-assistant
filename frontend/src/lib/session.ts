const KEY = 'assistant-session-id';

function createSessionId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `session-${Math.random().toString(36).slice(2)}`;
}

export function getSessionId(): string {
  const storage = typeof globalThis !== 'undefined' ? globalThis.localStorage : undefined;
  if (!storage || typeof storage.getItem !== 'function' || typeof storage.setItem !== 'function') {
    return 'test-session';
  }
  const current = storage.getItem(KEY);
  if (current) return current;
  const created = createSessionId();
  storage.setItem(KEY, created);
  return created;
}
