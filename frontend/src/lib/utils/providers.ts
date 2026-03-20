const LOCAL_OLLAMA_HOSTS = new Set([
  'ollama',
  'localhost',
  '127.0.0.1',
  '::1',
  'host.docker.internal'
]);

export function canonicalLocalOllamaBaseUrl(baseUrl?: string | null): string | null {
  const raw = baseUrl?.trim();
  if (!raw) return null;

  try {
    const parsed = new URL(raw.includes('://') ? raw : `http://${raw}`);
    const host = parsed.hostname.toLowerCase();
    const port = parsed.port ? Number(parsed.port) : null;
    if (LOCAL_OLLAMA_HOSTS.has(host) && (port === null || port === 11434)) {
      return 'http://localhost:11434';
    }
  } catch {
    return raw;
  }

  return raw;
}
