import { getSessionId } from './session';

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('X-Session-Id', getSessionId());

  const response = await fetch(path, {
    ...init,
    headers
  });

  if (!response.ok) {
    throw await toRequestError(response);
  }

  if (response.headers.get('content-type')?.startsWith('text/event-stream')) {
    return (await response.text()) as T;
  }

  const payload = await response.json();
  return payload.data as T;
}

async function stream(
  path: string,
  init: RequestInit,
  onEvent: (event: Record<string, unknown>) => void
): Promise<void> {
  const headers = new Headers(init.headers);
  headers.set('X-Session-Id', getSessionId());

  const response = await fetch(path, {
    ...init,
    headers
  });

  if (!response.ok) {
    throw await toRequestError(response);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Stream unavailable.');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });

    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const event of parseSseMessages(`${rawEvent}\n\n`)) {
        onEvent(event);
      }
      boundary = buffer.indexOf('\n\n');
    }

    if (done) break;
  }

  if (buffer.trim()) {
    for (const event of parseSseMessages(`${buffer}\n\n`)) {
      onEvent(event);
    }
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined
    }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }),
  delete: <T>(path: string) =>
    request<T>(path, {
      method: 'DELETE'
    }),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<T>(path, {
      method: 'POST',
      body: form
    });
  },
  stream
};

async function toRequestError(response: Response): Promise<Error> {
  const fallback = `Request failed: ${response.status}`;
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    return new Error(fallback);
  }

  try {
    const payload = await response.json();
    const detail = payload?.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return new Error(detail);
    }
  } catch {
    return new Error(fallback);
  }

  return new Error(fallback);
}

export function parseSseMessages(text: string): Array<Record<string, unknown>> {
  return text
    .split('\n\n')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => part.replace(/^data:\s*/, ''))
    .map((part) => JSON.parse(part) as Record<string, unknown>);
}
