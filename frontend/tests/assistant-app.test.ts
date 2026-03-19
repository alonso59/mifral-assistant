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
        documents: []
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
            base_url: 'http://ollama:11434',
            system_prompt: 'You are a helpful AI assistant.',
            temperature: 0.7,
            max_tokens: 1024,
            context_max_tokens: 8192,
            auto_compress: false
          },
          embedding: {
            provider: 'ollama',
            model: 'nomic-embed-text',
            api_key_set: false,
            base_url: 'http://ollama:11434'
          },
          generation_provider_options: [
            { id: 'ollama', label: 'Ollama (local)', hint: 'hint', default_model: 'llama3.2' }
          ],
          embedding_provider_options: [
            { id: 'ollama', label: 'Ollama (local)', hint: 'hint', default_model: 'nomic-embed-text' }
          ]
        });
      }
      if (url.startsWith('/api/v1/settings/model/ollama/models')) {
        return jsonResponse([{ name: 'llama3.2' }, { name: 'nomic-embed-text' }]);
      }
      if (url === '/api/v1/settings/knowledge') {
        return jsonResponse({
          chunk_size: 1000,
          chunk_overlap: 120,
          retrieval_top_k: 5,
          relevance_threshold: 0,
          hybrid_search_enabled: false,
          rag_template: ''
        });
      }
      if (url === '/api/v1/settings/system') {
        return jsonResponse({
          app_name: 'Assistant',
          theme: 'light'
        });
      }

      return jsonResponse({});
    }) as typeof fetch;
  });

  it('renders classroom-style sidebar behavior and knowledge controls', async () => {
    render(AssistantApp);

    await waitFor(() => expect(screen.getByTestId('chat-history-list')).toBeTruthy());

    expect(screen.getByText('First chat')).toBeTruthy();
    expect(screen.getAllByText('AI Assistant').length).toBeGreaterThan(0);

    await fireEvent.click(screen.getByTestId('knowledge-toggle'));
    expect(screen.queryByTestId('knowledge-list')).toBeNull();

    await fireEvent.click(screen.getByTestId('knowledge-toggle'));
    expect(screen.getByTestId('knowledge-list')).toBeTruthy();

    await fireEvent.click(screen.getByTestId('new-knowledge-button'));
    expect(screen.getByPlaceholderText('Knowledge space name')).toBeTruthy();

    await fireEvent.input(screen.getByPlaceholderText('Knowledge space name'), {
      target: { value: 'API Notes' }
    });
    await fireEvent.click(screen.getByText('Create knowledge'));

    await waitFor(() => expect(screen.getByText('API Notes')).toBeTruthy());

    await fireEvent.click(screen.getByText('Docs'));
    await waitFor(() => expect(screen.getByText('Selected')).toBeTruthy());

    await fireEvent.click(screen.getByTestId('new-chat-button'));
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/chats',
      expect.objectContaining({ method: 'POST' })
    );
  });
});
