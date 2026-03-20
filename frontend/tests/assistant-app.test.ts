import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AssistantApp from '../src/lib/components/AssistantApp.svelte';

function jsonResponse(data: unknown) {
  return new Response(JSON.stringify({ data }), {
    headers: { 'Content-Type': 'application/json' }
  });
}

describe('AssistantApp', () => {
  beforeEach(() => {
    let chatCounter = 1;
    const chats: Array<{
      id: string;
      session_id: string;
      title: string;
      knowledge_space_id: string | null;
      created_at: string;
      updated_at: string;
    }> = [
      {
        id: 'chat-1',
        session_id: 'session',
        title: 'First chat',
        knowledge_space_id: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z'
      }
    ];
    const spaces = [
      {
        id: 'space-1',
        name: 'Docs',
        description: null,
        created_at: '2026-01-01T00:00:00Z',
        documents: [
          {
            id: 'doc-1',
            filename: 'guide.txt',
            processing_status: 'PROCESSING',
            processing_stage: 'EMBEDDING',
            processing_progress_percent: 72,
            processing_message: 'Generating embeddings...',
            chunk_count: 0,
            created_at: '2026-01-01T00:00:00Z'
          }
        ]
      }
    ];
    const messages = [
      {
        id: 'msg-1',
        role: 'ASSISTANT',
        content: 'Hello',
        grounded: false,
        citations: [],
        created_at: '2026-01-01T00:00:00Z'
      }
    ];

    vi.stubGlobal('crypto', {
      randomUUID: vi.fn(() => `uuid-${Math.random().toString(16).slice(2)}`)
    });

    global.fetch = vi.fn(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? 'GET';

      if (url === '/api/v1/chats' && method === 'GET') return jsonResponse(chats);
      if (url === '/api/v1/chats' && method === 'POST') {
        const chat = {
          id: `chat-${++chatCounter}`,
          session_id: 'session',
          title: 'New chat',
          knowledge_space_id: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z'
        };
        chats.unshift(chat);
        return jsonResponse(chat);
      }
      if (url === '/api/v1/chats/chat-1/messages') return jsonResponse(messages);
      if (url === '/api/v1/knowledge-spaces' && method === 'GET') return jsonResponse(spaces);
      if (url === '/api/v1/knowledge-spaces' && method === 'POST') {
        spaces.push({
          id: 'space-2',
          name: 'API Notes',
          description: null,
          created_at: '2026-01-01T00:00:00Z',
          documents: []
        });
        return jsonResponse(spaces[1]);
      }
      if (url === '/api/v1/knowledge-spaces/space-1/select' && method === 'POST') {
        chats[0].knowledge_space_id = 'space-1';
        return jsonResponse(chats[0]);
      }
      if (url === '/api/v1/chats/chat-1/knowledge-selection' && method === 'DELETE') {
        chats[0].knowledge_space_id = null;
        return jsonResponse(chats[0]);
      }
      if (url === '/api/v1/settings/model') {
        return jsonResponse({
          generation: {
            provider: 'ollama',
            model: 'llama3.2',
            api_key_set: false,
            base_url: 'http://localhost:11434',
            system_prompt: 'You are a helpful AI assistant.',
            temperature: 0.7,
            max_tokens: 1024,
            context_max_tokens: 8192,
            auto_compress: false
          },
          embedding: {
            provider: 'sentence-transformers',
            model: 'sentence-transformers/all-MiniLM-L6-v2',
            api_key_set: false,
            base_url: null
          },
          generation_provider_options: [
            { id: 'ollama', label: 'Ollama (local)', hint: 'hint', default_model: 'llama3.2' },
            { id: 'openrouter', label: 'OpenRouter', hint: 'hint', default_model: 'nvidia/nemotron-3-super-120b-a12b:free' }
          ],
          embedding_provider_options: [
            {
              id: 'sentence-transformers',
              label: 'Sentence Transformers (local CPU)',
              hint: 'hint',
              default_model: 'sentence-transformers/all-MiniLM-L6-v2'
            },
            { id: 'ollama', label: 'Ollama (local)', hint: 'hint', default_model: 'nomic-embed-text' }
          ]
        });
      }
      if (url.startsWith('/api/v1/settings/model/ollama/models')) {
        return jsonResponse([{ name: 'llama3.2' }, { name: 'nomic-embed-text' }]);
      }
      if (url.startsWith('/api/v1/settings/model/ollama/health')) {
        return jsonResponse({ ok: true, model_count: 2 });
      }
      if (url.startsWith('/api/v1/settings/model/ollama/pull')) {
        return new Response('data: {"status":"downloading","completed":1,"total":2}\n\ndata: {"status":"success","completed":2,"total":2}\n\n', {
          headers: { 'Content-Type': 'text/event-stream' }
        });
      }
      if (url === '/api/v1/settings/knowledge') {
        return jsonResponse({
          chunk_size: 1000,
          chunk_overlap: 120,
          retrieval_top_k: 5,
          relevance_threshold: 0,
          enable_markdown_chunking: true,
          query_augmentation: false,
          hybrid_search_enabled: false,
          hybrid_bm25_weight: 0.5,
          rag_template: ''
        });
      }
      if (url === '/api/v1/settings/system') {
        return jsonResponse({
          app_name: 'Assistant',
          theme: 'light',
          show_thinking_overlay: true
        });
      }

      return jsonResponse({});
    }) as typeof fetch;
  });

  it('renders the knowledge overlay flow and processing visibility', async () => {
    render(AssistantApp);

    await waitFor(() => expect(screen.getByTestId('chat-history-list')).toBeTruthy());

    expect(screen.getByText('First chat')).toBeTruthy();
    expect(screen.getAllByText('AI Assistant').length).toBeGreaterThan(0);

    expect(screen.getByTestId('knowledge-summary')).toBeTruthy();
    expect(screen.getByText('General')).toBeTruthy();

    await fireEvent.click(screen.getByTestId('manage-knowledge-button'));
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy());
    expect(screen.getByTestId('knowledge-overlay-list')).toBeTruthy();
    expect(screen.getByText('Embedding')).toBeTruthy();
    expect(screen.getByText('Generating embeddings...')).toBeTruthy();
    expect(screen.getByText('72%')).toBeTruthy();

    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'API Notes' }
    });
    await fireEvent.click(screen.getByText('Create knowledge'));

    await waitFor(() => expect(screen.getByText('API Notes')).toBeTruthy());

    await fireEvent.click(screen.getByTestId('select-space-space-1'));
    await waitFor(() => expect(screen.getAllByText('Docs').length).toBeGreaterThan(0));
    expect(screen.getByText('Selected for chat')).toBeTruthy();

    await fireEvent.click(screen.getByTestId('new-chat-button'));
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/chats',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('checks Ollama health and pulls models from settings', async () => {
    render(AssistantApp);

    await waitFor(() => expect(screen.getByTitle('Settings')).toBeTruthy());
    await fireEvent.click(screen.getByTitle('Settings'));

    await waitFor(() => expect(screen.getByTitle('Check Ollama availability')).toBeTruthy());
    await fireEvent.click(screen.getByTitle('Check Ollama availability'));
    await waitFor(() => expect(screen.getByText(/Ollama reachable/i)).toBeTruthy());

    await fireEvent.input(screen.getByPlaceholderText('Pull model…'), {
      target: { value: 'mistral' }
    });
    await fireEvent.click(screen.getByTitle('Pull model'));

    await waitFor(() => expect(screen.getByText('Done')).toBeTruthy());
    expect(screen.getByText('OpenRouter')).toBeTruthy();
  });

  it('normalizes legacy local Ollama hostnames before loading models', async () => {
    const fetchCalls: string[] = [];
    global.fetch = vi.fn(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      fetchCalls.push(`${method} ${url}`);

      if (url === '/api/v1/chats' && method === 'GET') return jsonResponse([]);
      if (url === '/api/v1/chats' && method === 'POST') {
        return jsonResponse({
          id: 'chat-legacy',
          session_id: 'session',
          title: 'New chat',
          knowledge_space_id: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z'
        });
      }
      if (url === '/api/v1/knowledge-spaces' && method === 'GET') return jsonResponse([]);
      if (url === '/api/v1/settings/knowledge') {
        return jsonResponse({
          chunk_size: 1000,
          chunk_overlap: 120,
          retrieval_top_k: 5,
          relevance_threshold: 0,
          enable_markdown_chunking: true,
          query_augmentation: false,
          hybrid_search_enabled: false,
          hybrid_bm25_weight: 0.5,
          rag_template: ''
        });
      }
      if (url === '/api/v1/settings/system') {
        return jsonResponse({
          app_name: 'Assistant',
          theme: 'light',
          show_thinking_overlay: true
        });
      }
      if (url === '/api/v1/settings/model') {
        return jsonResponse({
          generation: {
            provider: 'ollama',
            model: 'llama3.2',
            api_key_set: false,
            base_url: 'http://ollama:11434',
            system_prompt: 'You are a helpful AI assistant.',
            temperature: 0.7,
            max_tokens: 1024,
            context_max_tokens: 8192,
            auto_compress: false
          },
          embedding: {
            provider: 'sentence-transformers',
            model: 'sentence-transformers/all-MiniLM-L6-v2',
            api_key_set: false,
            base_url: null
          },
          generation_provider_options: [
            { id: 'ollama', label: 'Ollama (local)', hint: 'hint', default_model: 'llama3.2' }
          ],
          embedding_provider_options: [
            {
              id: 'sentence-transformers',
              label: 'Sentence Transformers (local CPU)',
              hint: 'hint',
              default_model: 'sentence-transformers/all-MiniLM-L6-v2'
            }
          ]
        });
      }
      if (url === '/api/v1/settings/model/ollama/models?base_url=http%3A%2F%2Flocalhost%3A11434') {
        return jsonResponse([{ name: 'llama3.2' }]);
      }

      throw new Error(`Unexpected fetch call: ${method} ${url}`);
    }) as typeof fetch;

    render(AssistantApp);

    await waitFor(() =>
      expect(fetchCalls).toContain(
        'GET /api/v1/settings/model/ollama/models?base_url=http%3A%2F%2Flocalhost%3A11434'
      )
    );
  });
});
