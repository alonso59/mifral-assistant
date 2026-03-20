<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import {
    BookOpen,
    Check,
    Copy,
    Menu,
    MessageSquare,
    Pencil,
    Plus,
    RotateCcw,
    Send,
    Settings,
    Sparkles,
    Square,
    ThumbsDown,
    ThumbsUp,
    Trash2
  } from 'lucide-svelte';
  import { api, parseSseMessages } from '$lib/api';
  import CitationDisclosure from '$lib/components/classroom/CitationDisclosure.svelte';
  import KnowledgeOverlay from '$lib/components/KnowledgeOverlay.svelte';
  import SettingsOverlay from '$lib/components/SettingsOverlay.svelte';
  import { getSessionId } from '$lib/session';
  import type {
    Chat,
    ChatMessage,
    KnowledgeSettings,
    KnowledgeSpace,
    ModelSettings,
    OllamaHealth,
    OllamaModel,
    ProviderModelOption,
    SystemSettings,
    UpdateModelSettings
  } from '$lib/types';
  import { renderMarkdown } from '$lib/utils/markdown';
  import { canonicalLocalOllamaBaseUrl } from '$lib/utils/providers';

  let chats: Chat[] = [];
  let spaces: KnowledgeSpace[] = [];
  let activeChat: Chat | null = null;
  let messages: ChatMessage[] = [];
  let composer = '';
  let loading = true;
  let sending = false;
  let chatError: string | null = null;
  let copiedId: string | null = null;
  let knowledgeOverlayOpen = false;
  let settingsOpen = false;
  let editingChatId: string | null = null;
  let renameValue = '';
  let showScrollButton = false;
  let messagesEl: HTMLDivElement;
  let composerEl: HTMLTextAreaElement | null = null;
  let abortController: AbortController | null = null;
  let sidebarOpen = false;
  let ollamaModels: OllamaModel[] = [];
  let loadingOllamaModels = false;
  let ollamaModelsError: string | null = null;
  let openRouterModels: ProviderModelOption[] = [];
  let loadingOpenRouterModels = false;
  let openRouterModelsError: string | null = null;
  let checkingOllamaHealth = false;
  let ollamaHealth: OllamaHealth | null = null;
  let ollamaHealthError: string | null = null;
  let pullingOllamaModel = false;
  let ollamaPullStatus = '';
  let ollamaPullProgress: number | null = null;
  let ollamaPullError: string | null = null;
  let ollamaPullDone = false;
  let preferredTheme: 'light' | 'dark' = 'light';
  let knowledgePollTimer: ReturnType<typeof setTimeout> | null = null;

  let modelSettings: ModelSettings = {
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
    generation_provider_options: [],
    embedding_provider_options: []
  };

  let knowledgeSettings: KnowledgeSettings = {
    chunk_size: 1000,
    chunk_overlap: 120,
    retrieval_top_k: 5,
    relevance_threshold: 0,
    enable_markdown_chunking: true,
    query_augmentation: false,
    hybrid_search_enabled: false,
    hybrid_bm25_weight: 0.5,
    rag_template: ''
  };

  let systemSettings: SystemSettings = {
    app_name: 'Assistant',
    theme: 'light',
    show_thinking_overlay: true
  };

  $: resolvedTheme =
    systemSettings.theme === 'system' ? preferredTheme : systemSettings.theme;

  $: if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = resolvedTheme;
  }

  function formatTimestamp(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric'
    }).format(date);
  }

  function isAtBottom(element: HTMLDivElement, threshold = 32) {
    return element.scrollHeight - element.scrollTop - element.clientHeight < threshold;
  }

  function handleScroll() {
    if (messagesEl) {
      showScrollButton = !isAtBottom(messagesEl);
    }
  }

  async function scrollToBottom(force = false) {
    await tick();
    if (messagesEl && (force || isAtBottom(messagesEl))) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
      showScrollButton = false;
    }
  }

  async function focusComposer() {
    await tick();
    composerEl?.focus();
  }

  async function refreshChats(preferredChatId: string | null = activeChat?.id ?? null) {
    chats = await api.get<Chat[]>('/api/v1/chats');
    activeChat = preferredChatId
      ? chats.find((chat) => chat.id === preferredChatId) ?? chats[0] ?? null
      : chats[0] ?? null;
  }

  async function refreshSpaces() {
    spaces = await api.get<KnowledgeSpace[]>('/api/v1/knowledge-spaces');
    scheduleKnowledgePoll();
  }

  async function loadMessages(chatId: string) {
    messages = (await api.get<ChatMessage[]>(`/api/v1/chats/${chatId}/messages`)).map((message) => ({
      ...message,
      thinking: false,
      thinkingText: '',
      thoughtsExpanded: false,
      streaming: false
    }));
    await scrollToBottom(true);
  }

  async function loadSettings() {
    modelSettings = await api.get<ModelSettings>('/api/v1/settings/model');
    knowledgeSettings = await api.get<KnowledgeSettings>('/api/v1/settings/knowledge');
    systemSettings = await api.get<SystemSettings>('/api/v1/settings/system');
    if (modelSettings.generation.provider === 'openrouter') {
      await refreshOpenRouterModels(modelSettings.generation.base_url);
    }
  }

  async function refreshOllamaModels(purpose: 'generation' | 'embedding', baseUrl?: string | null) {
    loadingOllamaModels = true;
    ollamaModelsError = null;
    try {
      const normalizedBaseUrl = canonicalLocalOllamaBaseUrl(baseUrl);
      const query = normalizedBaseUrl ? `?base_url=${encodeURIComponent(normalizedBaseUrl)}` : '';
      ollamaModels = await api.get<OllamaModel[]>(`/api/v1/settings/model/ollama/models${query}`);
    } catch (error) {
      ollamaModelsError = error instanceof Error ? error.message : 'Cannot reach Ollama.';
      if (purpose === 'generation' || purpose === 'embedding') {
        ollamaModels = [];
      }
    } finally {
      loadingOllamaModels = false;
    }
  }

  async function refreshOpenRouterModels(baseUrl?: string | null, apiKey?: string | null) {
    loadingOpenRouterModels = true;
    openRouterModelsError = null;
    try {
      const params = new URLSearchParams();
      if (baseUrl) params.set('base_url', baseUrl);
      if (apiKey) params.set('api_key', apiKey);
      const query = params.toString() ? `?${params.toString()}` : '';
      openRouterModels = await api.get<ProviderModelOption[]>(`/api/v1/settings/model/openrouter/models${query}`);
    } catch (error) {
      openRouterModelsError = error instanceof Error ? error.message : 'Cannot reach OpenRouter.';
      openRouterModels = [];
    } finally {
      loadingOpenRouterModels = false;
    }
  }

  function updateAssistantDraft(
    messageId: string,
    updater: (message: ChatMessage) => ChatMessage
  ) {
    messages = messages.map((message) =>
      message.id === messageId ? updater(message) : message
    );
  }

  function toggleThoughts(messageId: string) {
    updateAssistantDraft(messageId, (message) => ({
      ...message,
      thoughtsExpanded: !message.thoughtsExpanded
    }));
  }

  function eventBoolean(event: Record<string, unknown>, key: string): boolean | null {
    const value = event[key];
    return typeof value === 'boolean' ? value : null;
  }

  function eventString(event: Record<string, unknown>, key: string): string | null {
    const value = event[key];
    return typeof value === 'string' ? value : null;
  }

  function eventCitations(event: Record<string, unknown>): ChatMessage['citations'] | null {
    if (Array.isArray(event.chunks)) return event.chunks as ChatMessage['citations'];
    if (Array.isArray(event.items)) return event.items as ChatMessage['citations'];
    return null;
  }

  function eventMessage(event: Record<string, unknown>): ChatMessage | null {
    return event.message && typeof event.message === 'object'
      ? (event.message as ChatMessage)
      : null;
  }

  async function checkOllamaHealth(purpose: 'generation' | 'embedding', baseUrl?: string | null) {
    checkingOllamaHealth = true;
    ollamaHealthError = null;
    try {
      const normalizedBaseUrl = canonicalLocalOllamaBaseUrl(baseUrl);
      const query = normalizedBaseUrl ? `?base_url=${encodeURIComponent(normalizedBaseUrl)}` : '';
      ollamaHealth = await api.get<OllamaHealth>(`/api/v1/settings/model/ollama/health${query}`);
      if (purpose === 'generation' || purpose === 'embedding') {
        await refreshOllamaModels(purpose, normalizedBaseUrl);
      }
    } catch (error) {
      ollamaHealth = null;
      ollamaHealthError = error instanceof Error ? error.message : 'Cannot reach Ollama.';
    } finally {
      checkingOllamaHealth = false;
    }
  }

  async function pullOllamaModel(model: string, purpose: 'generation' | 'embedding', baseUrl?: string | null) {
    const target = model.trim().replace(/^ollama\s+(run|pull)\s+/, '');
    if (!target) return;

    pullingOllamaModel = true;
    ollamaPullStatus = '';
    ollamaPullProgress = null;
    ollamaPullError = null;
    ollamaPullDone = false;

    try {
      const normalizedBaseUrl = canonicalLocalOllamaBaseUrl(baseUrl);
      const query = normalizedBaseUrl ? `?base_url=${encodeURIComponent(normalizedBaseUrl)}` : '';
      const response = await fetch(`/api/v1/settings/model/ollama/pull${query}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-Id': getSessionId()
        },
        body: JSON.stringify({ model: target })
      });

      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Pull stream unavailable.');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() ?? '';

        for (const rawEvent of parts) {
          for (const event of parseSseMessages(`${rawEvent}\n\n`)) {
            if (typeof event.error === 'string') {
              throw new Error(event.error);
            }
            if (typeof event.status === 'string') {
              ollamaPullStatus = event.status;
            }
            if (typeof event.completed === 'number' && typeof event.total === 'number' && event.total > 0) {
              ollamaPullProgress = Math.round((event.completed / event.total) * 1000) / 10;
            } else if (event.status === 'success') {
              ollamaPullProgress = 100;
            }
          }
        }
      }

      if (buffer.trim()) {
        for (const event of parseSseMessages(`${buffer}\n\n`)) {
          if (typeof event.status === 'string') {
            ollamaPullStatus = event.status;
          }
          if (typeof event.completed === 'number' && typeof event.total === 'number' && event.total > 0) {
            ollamaPullProgress = Math.round((event.completed / event.total) * 1000) / 10;
          }
        }
      }

      ollamaPullDone = true;
      await refreshOllamaModels(purpose, normalizedBaseUrl);
      await checkOllamaHealth(purpose, normalizedBaseUrl);
    } catch (error) {
      ollamaPullError = error instanceof Error ? error.message : 'Pull failed.';
    } finally {
      pullingOllamaModel = false;
    }
  }

  async function bootstrap() {
    await Promise.all([loadSettings(), refreshSpaces(), refreshChats(null)]);
    if (!activeChat) {
      const created = await api.post<Chat>('/api/v1/chats');
      await refreshChats(created.id);
      activeChat = created;
      messages = [];
    } else {
      await loadMessages(activeChat.id);
    }

    if (modelSettings.generation.provider === 'ollama') {
      await refreshOllamaModels('generation', modelSettings.generation.base_url);
    } else if (modelSettings.embedding.provider === 'ollama') {
      await refreshOllamaModels('embedding', modelSettings.embedding.base_url);
    }
    loading = false;
  }

  onMount(async () => {
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      preferredTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    await bootstrap();
    await focusComposer();
  });

  onDestroy(() => {
    abortController?.abort();
    if (knowledgePollTimer) {
      clearTimeout(knowledgePollTimer);
    }
  });

  async function createChat() {
    const created = await api.post<Chat>('/api/v1/chats');
    await refreshChats(created.id);
    activeChat = created;
    messages = [];
    editingChatId = null;
    sidebarOpen = false;
    await focusComposer();
  }

  async function selectChat(chat: Chat) {
    activeChat = chat;
    editingChatId = null;
    sidebarOpen = false;
    await loadMessages(chat.id);
    await focusComposer();
  }

  function startRename(chat: Chat) {
    editingChatId = chat.id;
    renameValue = chat.title;
  }

  async function submitRename(chatId: string) {
    if (!renameValue.trim()) {
      editingChatId = null;
      return;
    }
    const renamed = await api.patch<Chat>(`/api/v1/chats/${chatId}`, {
      title: renameValue.trim()
    });
    editingChatId = null;
    await refreshChats(chatId);
    activeChat = renamed;
  }

  async function deleteChat(chatId: string) {
    await api.delete<{ deleted: boolean }>(`/api/v1/chats/${chatId}`);
    const remainingIds = chats.filter((chat) => chat.id !== chatId).map((chat) => chat.id);
    await refreshChats(remainingIds[0] ?? null);
    if (activeChat) {
      await loadMessages(activeChat.id);
    } else {
      await createChat();
    }
  }

  function hasKnowledgeInProgress(items: KnowledgeSpace[] = spaces): boolean {
    return items.some((space) =>
      space.documents.some((document) =>
        document.processing_status === 'PENDING' || document.processing_status === 'PROCESSING'
      )
    );
  }

  function scheduleKnowledgePoll() {
    if (knowledgePollTimer || !hasKnowledgeInProgress()) return;
    knowledgePollTimer = setTimeout(async () => {
      knowledgePollTimer = null;
      try {
        await refreshSpaces();
      } catch {
        scheduleKnowledgePoll();
      }
    }, 3000);
  }

  async function createKnowledgeSpace(name: string, description: string | null) {
    await api.post<KnowledgeSpace>('/api/v1/knowledge-spaces', {
      name,
      description
    });
    await refreshSpaces();
  }

  async function renameKnowledgeSpace(spaceId: string, name: string, description: string | null) {
    await api.patch<KnowledgeSpace>(`/api/v1/knowledge-spaces/${spaceId}`, {
      name,
      description
    });
    await refreshSpaces();
  }

  async function deleteKnowledgeSpace(spaceId: string) {
    await api.delete<{ deleted: boolean }>(`/api/v1/knowledge-spaces/${spaceId}`);
    await Promise.all([refreshSpaces(), refreshChats(activeChat?.id ?? null)]);
  }

  async function selectKnowledgeSpace(space: KnowledgeSpace) {
    if (!activeChat) return;
    activeChat = await api.post<Chat>(`/api/v1/knowledge-spaces/${space.id}/select`, {
      chat_id: activeChat.id
    });
    await refreshChats(activeChat.id);
  }

  async function clearKnowledgeSelection() {
    if (!activeChat?.knowledge_space_id) return;
    activeChat = await api.delete<Chat>(`/api/v1/chats/${activeChat.id}/knowledge-selection`);
    await refreshChats(activeChat.id);
  }

  async function sendMessage() {
    if (!activeChat || !composer.trim() || sending) return;
    const submitted = composer.trim();
    composer = '';
    chatError = null;
    sending = true;

    const tempUserId = crypto.randomUUID();
    const tempAssistantId = crypto.randomUUID();
    messages = [
      ...messages,
      {
        id: tempUserId,
        role: 'USER',
        content: submitted,
        grounded: false,
        citations: [],
        created_at: new Date().toISOString()
      },
      {
        id: tempAssistantId,
        role: 'ASSISTANT',
        content: '',
        grounded: false,
        citations: [],
        created_at: new Date().toISOString(),
        thinking: false,
        thinkingText: '',
        thoughtsExpanded: false,
        streaming: true
      }
    ];
    await scrollToBottom(true);

    try {
      abortController = new AbortController();
      let serverUser: ChatMessage | null = null;
      let serverAssistant: ChatMessage | null = null;
      let streamError: string | null = null;

      await api.stream(
        `/api/v1/chats/${activeChat.id}/messages/stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: submitted }),
          signal: abortController.signal
        },
        (event) => {
          const eventType = eventString(event, 'type');
          if (eventType === 'error') {
            streamError = eventString(event, 'message') ?? 'Failed to send message.';
            return;
          }
          if (eventType === 'token') {
            const token = eventString(event, 'token');
            if (!token) return;
            updateAssistantDraft(tempAssistantId, (message) => ({
              ...message,
              content: `${message.content}${token}`,
              thinking: false,
              streaming: true
            }));
            void scrollToBottom();
            return;
          }
          if (eventType === 'thinking') {
            const value = eventBoolean(event, 'value');
            if (value === null) return;
            updateAssistantDraft(tempAssistantId, (message) => ({
              ...message,
              thinking: value,
              thoughtsExpanded: value ? message.thoughtsExpanded ?? false : message.thoughtsExpanded
            }));
            return;
          }
          if (eventType === 'thinking_text') {
            const text = eventString(event, 'text');
            if (!text) return;
            updateAssistantDraft(tempAssistantId, (message) => ({
              ...message,
              thinkingText: text,
              thoughtsExpanded: message.thoughtsExpanded ?? false
            }));
            return;
          }
          if (eventType === 'sources') {
            const citations = eventCitations(event);
            if (!citations) return;
            updateAssistantDraft(tempAssistantId, (message) => ({
              ...message,
              grounded: citations.length > 0,
              citations
            }));
            return;
          }
          if (eventType === 'grounded') {
            const grounded = eventBoolean(event, 'value');
            if (grounded === null) return;
            updateAssistantDraft(tempAssistantId, (message) => ({
              ...message,
              grounded,
              citations: grounded ? message.citations : []
            }));
            return;
          }
          if (eventType === 'message') {
            const message = eventMessage(event);
            if (!message) return;
            if (message.role === 'USER') {
              serverUser = message;
            }
            if (message.role === 'ASSISTANT') {
              serverAssistant = message;
            }
          }
        }
      );

      if (streamError) {
        throw new Error(streamError);
      }
      if (!serverAssistant) {
        throw new Error('Model returned no content.');
      }
      const finalAssistant: ChatMessage = serverAssistant;
      const tempAssistant = messages.find((message) => message.id === tempAssistantId);

      messages = messages.filter((message) => message.id !== tempUserId && message.id !== tempAssistantId);
      if (serverUser) {
        messages = [...messages, serverUser];
      }
      messages = [
        ...messages,
        {
          ...finalAssistant,
          thinking: false,
          thinkingText: tempAssistant?.thinkingText ?? '',
          thoughtsExpanded: tempAssistant?.thoughtsExpanded ?? false,
          streaming: false
        }
      ];
      await refreshChats(activeChat.id);
      await scrollToBottom(true);
    } catch (error) {
      const aborted = error instanceof DOMException && error.name === 'AbortError';
      if (!aborted) {
        chatError = error instanceof Error ? error.message : 'Failed to send message.';
      }
      messages = messages.filter((message) => message.id !== tempAssistantId);
    } finally {
      sending = false;
      abortController = null;
      await focusComposer();
    }
  }

  async function regenerate() {
    if (!activeChat || sending || messages.length === 0) return;
    const lastAssistant = [...messages].reverse().find((message) => message.role === 'ASSISTANT');
    if (!lastAssistant) return;

    sending = true;
    chatError = null;
    messages = messages.map((message) =>
      message.id === lastAssistant.id
        ? {
            ...message,
            content: '',
            citations: [],
            grounded: false,
            thinking: false,
            thinkingText: '',
            thoughtsExpanded: false,
            streaming: true
          }
        : message
    );
    await scrollToBottom(true);

    try {
      abortController = new AbortController();
      let regenerated: ChatMessage | null = null;
      let streamError: string | null = null;

      await api.stream(
        `/api/v1/chats/${activeChat.id}/regenerate`,
        { method: 'POST', signal: abortController.signal },
        (event) => {
          const eventType = eventString(event, 'type');
          if (eventType === 'error') {
            streamError = eventString(event, 'message') ?? 'Failed to regenerate response.';
            return;
          }
          if (eventType === 'token') {
            const token = eventString(event, 'token');
            if (!token) return;
            updateAssistantDraft(lastAssistant.id, (message) => ({
              ...message,
              content: `${message.content}${token}`,
              thinking: false,
              streaming: true
            }));
            void scrollToBottom();
            return;
          }
          if (eventType === 'thinking') {
            const value = eventBoolean(event, 'value');
            if (value === null) return;
            updateAssistantDraft(lastAssistant.id, (message) => ({
              ...message,
              thinking: value
            }));
            return;
          }
          if (eventType === 'thinking_text') {
            const text = eventString(event, 'text');
            if (!text) return;
            updateAssistantDraft(lastAssistant.id, (message) => ({
              ...message,
              thinkingText: text
            }));
            return;
          }
          if (eventType === 'sources') {
            const citations = eventCitations(event);
            if (!citations) return;
            updateAssistantDraft(lastAssistant.id, (message) => ({
              ...message,
              grounded: citations.length > 0,
              citations
            }));
            return;
          }
          if (eventType === 'grounded') {
            const grounded = eventBoolean(event, 'value');
            if (grounded === null) return;
            updateAssistantDraft(lastAssistant.id, (message) => ({
              ...message,
              grounded,
              citations: grounded ? message.citations : []
            }));
            return;
          }
          if (eventType === 'message') {
            const message = eventMessage(event);
            if (!message) return;
            if (message.role === 'ASSISTANT') {
              regenerated = message;
            }
          }
        }
      );

      if (streamError) {
        throw new Error(streamError);
      }
      if (!regenerated) {
        throw new Error('Model returned no content.');
      }
      messages = messages.map((message) =>
        message.id === lastAssistant.id
          ? {
              ...regenerated!,
              thinking: false,
              thinkingText: message.thinkingText ?? '',
              thoughtsExpanded: message.thoughtsExpanded ?? false,
              streaming: false
            }
          : message
      );
      await refreshChats(activeChat.id);
      await scrollToBottom(true);
    } catch (error) {
      const aborted = error instanceof DOMException && error.name === 'AbortError';
      if (!aborted) {
        chatError = error instanceof Error ? error.message : 'Failed to regenerate response.';
      }
    } finally {
      sending = false;
      abortController = null;
      await focusComposer();
    }
  }

  function stopStreaming() {
    abortController?.abort();
  }

  async function handleUpload(spaceId: string, file: File) {
    await api.upload(`/api/v1/knowledge-spaces/${spaceId}/documents`, file);
    await refreshSpaces();
  }

  function openKnowledgeOverlay() {
    sidebarOpen = false;
    knowledgeOverlayOpen = true;
  }

  async function saveModelSettings(value: UpdateModelSettings): Promise<ModelSettings> {
    modelSettings = await api.put<ModelSettings>('/api/v1/settings/model', value);
    if (modelSettings.generation.provider === 'ollama') {
      await refreshOllamaModels('generation', modelSettings.generation.base_url);
      openRouterModels = [];
    } else if (modelSettings.generation.provider === 'openrouter') {
      await refreshOpenRouterModels(modelSettings.generation.base_url, value.generation.api_key ?? null);
    } else if (modelSettings.embedding.provider === 'ollama') {
      await refreshOllamaModels('embedding', modelSettings.embedding.base_url);
      openRouterModels = [];
    } else {
      ollamaModels = [];
      openRouterModels = [];
    }
    return modelSettings;
  }

  async function saveKnowledgeSettings(value: KnowledgeSettings) {
    knowledgeSettings = await api.put<KnowledgeSettings>('/api/v1/settings/knowledge', value);
  }

  async function saveSystemSettings(value: SystemSettings) {
    systemSettings = await api.put<SystemSettings>('/api/v1/settings/system', value);
  }

  async function copyMessage(id: string, content: string) {
    try {
      await navigator.clipboard.writeText(content);
      copiedId = id;
      setTimeout(() => {
        if (copiedId === id) copiedId = null;
      }, 1500);
    } catch {
      copiedId = null;
    }
  }

  function handleComposerKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  function activeKnowledgeName(): string {
    if (!activeChat?.knowledge_space_id) return 'General';
    return (
      spaces.find((space) => space.id === activeChat?.knowledge_space_id)?.name ??
      'Selected knowledge'
    );
  }

  function activeKnowledgeDocumentSummary(): string {
    if (!activeChat?.knowledge_space_id) {
      return 'No knowledge space selected for this chat.';
    }
    const selectedSpace = spaces.find((space) => space.id === activeChat.knowledge_space_id);
    if (!selectedSpace) {
      return 'The selected knowledge space is no longer available.';
    }
    const readyCount = selectedSpace.documents.filter((document) => document.processing_status === 'READY').length;
    const pendingCount = selectedSpace.documents.filter(
      (document) => document.processing_status === 'PENDING' || document.processing_status === 'PROCESSING'
    ).length;
    if (pendingCount > 0) {
      return `${readyCount} ready, ${pendingCount} indexing. Retrieval uses only ready documents.`;
    }
    return `${readyCount} ready document${readyCount === 1 ? '' : 's'} available for grounded chat.`;
  }

  async function submitFeedback(messageId: string, vote: 'LIKE' | 'DISLIKE') {
    const current = messages.find((message) => message.id === messageId)?.feedback_vote ?? null;
    const nextVote = current === vote ? null : vote;

    messages = messages.map((message) =>
      message.id === messageId ? { ...message, feedback_vote: nextVote } : message
    );

    try {
      const updated = await api.post<ChatMessage>(`/api/v1/chat/messages/${messageId}/feedback`, {
        vote: nextVote
      });
      messages = messages.map((message) => (message.id === messageId ? updated : message));
    } catch {
      messages = messages.map((message) =>
        message.id === messageId ? { ...message, feedback_vote: current } : message
      );
    }
  }

  function generationStatusTone(): 'green' | 'yellow' | 'red' {
    if (modelSettings.generation.provider !== 'ollama') return 'green';
    if (ollamaHealthError || ollamaModelsError || ollamaPullError) return 'red';
    if (pullingOllamaModel || checkingOllamaHealth || loadingOllamaModels) return 'yellow';
    if (ollamaHealth && !ollamaHealth.ok) return 'red';
    if (ollamaModels.length === 0) return 'yellow';
    return ollamaModels.some((model) => model.name === modelSettings.generation.model) ? 'green' : 'yellow';
  }

  function generationStatusLabel(): string {
    if (modelSettings.generation.provider !== 'ollama') return 'Ready';
    if (ollamaHealthError || ollamaModelsError || ollamaPullError) return 'Unavailable';
    if (pullingOllamaModel) return 'Pulling';
    if (checkingOllamaHealth || loadingOllamaModels) return 'Checking';
    if (ollamaHealth && !ollamaHealth.ok) return 'Not ready';
    if (ollamaModels.length === 0) return 'No models';
    return ollamaModels.some((model) => model.name === modelSettings.generation.model)
      ? 'Available'
      : 'Missing';
  }
</script>

<svelte:head>
  <title>{systemSettings.app_name}</title>
</svelte:head>

<div class="min-h-screen bg-[var(--bg-app)] text-[var(--text-primary)]" data-theme={resolvedTheme}>
  <SettingsOverlay
    open={settingsOpen}
    {modelSettings}
    {knowledgeSettings}
    {systemSettings}
    {ollamaModels}
    {loadingOllamaModels}
    {ollamaModelsError}
    {openRouterModels}
    {loadingOpenRouterModels}
    {openRouterModelsError}
    {checkingOllamaHealth}
    {ollamaHealth}
    {ollamaHealthError}
    {pullingOllamaModel}
    {ollamaPullStatus}
    {ollamaPullProgress}
    {ollamaPullError}
    {ollamaPullDone}
    onClose={() => (settingsOpen = false)}
    onSaveModel={saveModelSettings}
    onSaveKnowledge={saveKnowledgeSettings}
    onSaveSystem={saveSystemSettings}
    onRefreshOllamaModels={refreshOllamaModels}
    onRefreshOpenRouterModels={refreshOpenRouterModels}
    onCheckOllamaHealth={checkOllamaHealth}
    onPullOllamaModel={pullOllamaModel}
  />
  <KnowledgeOverlay
    open={knowledgeOverlayOpen}
    {spaces}
    {activeChat}
    onClose={() => (knowledgeOverlayOpen = false)}
    onCreateSpace={createKnowledgeSpace}
    onRenameSpace={renameKnowledgeSpace}
    onDeleteSpace={deleteKnowledgeSpace}
    onSelectSpace={selectKnowledgeSpace}
    onClearSelection={clearKnowledgeSelection}
    onUpload={handleUpload}
  />

  {#if loading}
    <div class="flex h-screen items-center justify-center">
      <div class="flex items-center gap-3 rounded-2xl border border-[var(--border-default)] bg-[var(--bg-panel)] px-5 py-4 shadow-[var(--shadow-md)]">
        <div class="flex h-9 w-9 items-center justify-center rounded-xl bg-black/[0.04]">
          <Sparkles class="h-4.5 w-4.5 text-black/45" strokeWidth={1.8} />
        </div>
        <div>
          <p class="text-[11px] uppercase tracking-wide text-black/30">Assistant</p>
          <p class="text-[13px] text-black/60">Loading your workspace…</p>
        </div>
      </div>
    </div>
  {:else}
    <div class="flex h-screen overflow-hidden">
      {#if sidebarOpen}
        <button
          type="button"
          class="absolute inset-0 z-30 bg-black/20 lg:hidden"
          aria-label="Close sidebar"
          on:click={() => (sidebarOpen = false)}
        ></button>
      {/if}
      <aside class={`fixed inset-y-0 left-0 z-40 flex h-full w-[min(88vw,var(--app-sidebar-width))] flex-col border-r border-black/[0.06] bg-[var(--bg-panel)] px-4 py-4 transition-transform duration-200 lg:static lg:z-auto lg:w-[var(--app-sidebar-width)] ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>
        <div class="mb-4 flex items-center gap-3">
          <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-black/[0.04]">
            <Sparkles class="h-5 w-5 text-black/55" strokeWidth={1.7} />
          </div>
          <div class="min-w-0">
            <h1 class="truncate text-[15px] text-black/85" style="font-weight: 600;">AI Assistant</h1>
            <p class="text-[12px] text-black/40">{modelSettings.generation.provider} / {modelSettings.generation.model}</p>
          </div>
        </div>

        <button
          type="button"
          class="inline-flex h-[var(--size-control-height-md)] w-full items-center justify-center gap-2 rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-4 text-sm text-[var(--text-inverse)] shadow-[var(--shadow-sm)] transition-opacity hover:opacity-95"
          data-testid="new-chat-button"
          on:click={createChat}
        >
          <Plus class="h-4 w-4" strokeWidth={2.25} />
          <span>New chat</span>
        </button>

        <div class="mt-4 min-h-0 flex-1 overflow-y-auto custom-scrollbar pr-1">
          <div>
            <p class="mb-2 text-[11px] uppercase tracking-wide text-black/30">Chat history</p>
            {#if chats.length === 0}
              <div class="rounded-xl bg-black/[0.03] px-3 py-3 text-[11px] text-black/30">No conversations yet</div>
            {:else}
              <div class="space-y-1" data-testid="chat-history-list">
                {#each chats as chat (chat.id)}
                  <div class="group flex items-center gap-1.5">
                    {#if editingChatId === chat.id}
                      <input
                        bind:value={renameValue}
                        type="text"
                        class="flex-1 rounded-lg border border-[var(--border-focus)] bg-[var(--bg-input)] px-2.5 py-2 text-[12px] text-[var(--text-primary)] outline-none"
                        on:blur={() => submitRename(chat.id)}
                        on:keydown={(event) => {
                          if (event.key === 'Enter') void submitRename(chat.id);
                          if (event.key === 'Escape') editingChatId = null;
                        }}
                      />
                    {:else}
                      <button
                        type="button"
                        class={`flex flex-1 items-center gap-2 rounded-xl px-3 py-2 text-left transition-colors ${
                          activeChat?.id === chat.id
                            ? 'bg-black/[0.07] text-black/80'
                            : 'text-black/50 hover:bg-black/[0.03] hover:text-black/65'
                        }`}
                        style={`font-weight: ${activeChat?.id === chat.id ? 500 : 400};`}
                        on:click={() => selectChat(chat)}
                      >
                        <MessageSquare class="h-3.5 w-3.5 flex-shrink-0 opacity-40" strokeWidth={2} />
                        <span class="min-w-0 flex-1 max-w-[calc(100%-5rem)] truncate text-[12px]">
                          {chat.title || 'New chat'}
                        </span>
                        {#if chat.knowledge_space_id}
                          <span class="rounded-full bg-black/[0.04] px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-black/35">RAG</span>
                        {/if}
                      </button>
                    {/if}
                    <div class="ml-1 flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                      <button
                        type="button"
                        class="rounded p-1 text-black/25 transition-colors hover:bg-black/[0.04] hover:text-black/55"
                        title="Rename"
                        on:click={() => startRename(chat)}
                      >
                        <Pencil class="h-3 w-3" strokeWidth={2} />
                      </button>
                      <button
                        type="button"
                        class="rounded p-1 text-black/25 transition-colors hover:bg-black/[0.04] hover:text-red-400"
                        title="Delete"
                        on:click={() => deleteChat(chat.id)}
                      >
                        <Trash2 class="h-3 w-3" strokeWidth={2} />
                      </button>
                    </div>
                  </div>
                {/each}
              </div>
            {/if}
          </div>

          <div class="mt-5 border-t border-black/[0.05] pt-4">
            <div class="rounded-[var(--radius-xl)] border border-black/[0.05] bg-black/[0.02] p-3.5" data-testid="knowledge-summary">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="text-[11px] uppercase tracking-wide text-black/30">Knowledge</p>
                  <div class="mt-2 flex items-center gap-2">
                    <BookOpen class="h-3.5 w-3.5 flex-shrink-0 text-black/35" strokeWidth={1.8} />
                    <p class="truncate text-[13px] text-black/72" style="font-weight: 600;">{activeKnowledgeName()}</p>
                  </div>
                  <p class="mt-1 text-[11px] leading-relaxed text-black/38">{activeKnowledgeDocumentSummary()}</p>
                </div>
                {#if activeChat?.knowledge_space_id}
                  <span class="rounded-full bg-black/[0.05] px-2 py-0.5 text-[10px] uppercase tracking-wide text-black/35">RAG</span>
                {/if}
              </div>

              <div class="mt-3 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  data-testid="manage-knowledge-button"
                  class="inline-flex h-[var(--size-control-height-sm)] items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-3 text-[12px] text-[var(--text-inverse)] transition-opacity hover:opacity-95"
                  on:click={openKnowledgeOverlay}
                >
                  Manage knowledge
                </button>
                {#if activeChat?.knowledge_space_id}
                  <button
                    type="button"
                    class="inline-flex h-[var(--size-control-height-sm)] items-center justify-center rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-[12px] text-black/60 transition-colors hover:bg-black/[0.04]"
                    on:click={clearKnowledgeSelection}
                  >
                    Clear selection
                  </button>
                {/if}
              </div>
            </div>
          </div>
        </div>

        <div class="mt-4 rounded-xl bg-black/[0.03] px-3 py-2.5 text-[11px] text-black/35">
          <div class="flex items-center gap-2">
            <span
              class={`h-1.5 w-1.5 rounded-full ${
                generationStatusTone() === 'green'
                  ? 'bg-green-500'
                  : generationStatusTone() === 'yellow'
                    ? 'bg-amber-400'
                    : 'bg-red-500'
              }`}
            ></span>
            <p class="truncate">
              {generationStatusLabel()}:
              <span class="font-mono">{modelSettings.generation.model}</span>
            </p>
          </div>
        </div>
      </aside>

      <main class="flex min-w-0 flex-1 flex-col bg-[var(--bg-panel-muted)]">
        <div class="border-b border-black/[0.08] bg-[var(--bg-panel)] px-4 sm:px-6 py-3">
          <div class="flex w-full items-center justify-between gap-4">
            <div class="flex items-center gap-3">
              <button
                type="button"
                class="rounded-xl p-2 text-black/35 transition-colors hover:bg-black/[0.04] hover:text-black/60 lg:hidden"
                aria-label="Open sidebar"
                on:click={() => (sidebarOpen = true)}
              >
                <Menu class="h-4 w-4" strokeWidth={1.8} />
              </button>
              <div class="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-black/[0.06] to-black/[0.1]">
                <Sparkles class="h-4 w-4 text-black/50" strokeWidth={2} />
              </div>
              <div>
                <h2 class="text-[14px] text-black/75" style="font-weight: 550;">AI Assistant</h2>
                <p class="text-[11px] text-black/35">
                  {modelSettings.generation.provider} / {modelSettings.generation.model}
                </p>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <div class="hidden rounded-full border border-black/[0.06] bg-black/[0.03] px-3 py-1.5 text-[11px] text-black/50 sm:block">
                {activeKnowledgeName()}
              </div>
              {#if activeChat?.knowledge_space_id}
                <button
                  type="button"
                  class="rounded-lg px-2.5 py-1.5 text-[11px] text-black/45 transition-colors hover:bg-black/[0.04] hover:text-black/65"
                  on:click={clearKnowledgeSelection}
                >
                  Clear
                </button>
              {/if}
              <button
                type="button"
                class="rounded-xl p-2 text-black/35 transition-colors hover:bg-black/[0.04] hover:text-black/60"
                title="Settings"
                on:click={() => (settingsOpen = true)}
              >
                <Settings class="h-4 w-4" strokeWidth={1.8} />
              </button>
            </div>
          </div>
        </div>

        <div class="relative min-h-0 flex-1">
          <div bind:this={messagesEl} class="h-full overflow-y-auto px-4 py-4 custom-scrollbar sm:px-6" on:scroll={handleScroll}>
            <div class="mx-auto w-full max-w-[var(--chat-shell-max)]">
              {#if messages.length === 0}
                <div class="flex min-h-full flex-col items-center justify-center py-8 text-center">
                  <div class="flex h-10 w-10 items-center justify-center rounded-full bg-black/[0.04]">
                    <MessageSquare class="h-5 w-5 text-black/50" strokeWidth={3} />
                  </div>
                  <p class="mt-3 text-[12px] text-black/50 leading-relaxed">Ask anything…</p>
                </div>
              {:else}
                <div class="space-y-4">
                {#each messages as message (message.id)}
                  <div class={`group flex ${message.role === 'USER' ? 'justify-end' : 'justify-start'}`}>
                    <div class={message.role === 'USER' ? 'max-w-[min(72%,var(--chat-user-bubble-max))]' : 'w-full'}>
                      {#if message.role === 'USER'}
                        <div class="rounded-[18px] rounded-br-[4px] px-4 py-2.5 text-[13.5px] leading-[1.5] text-white" style="background: #007AFF; word-break: break-word;">
                          {message.content}
                        </div>
                      {:else}
                        <div class={`rounded-2xl px-4 py-3 text-[14px] leading-[1.65] text-[var(--text-secondary)] ${message.content ? 'bg-[var(--bg-surface)] shadow-[0_1px_3px_rgba(0,0,0,0.05)]' : ''}`}>
                          {#if systemSettings.show_thinking_overlay && message.role === 'ASSISTANT' && (message.thinking || message.thinkingText)}
                            <button
                              type="button"
                              class="mb-2 inline-flex max-w-full items-center gap-2 rounded-full border border-black/[0.08] bg-black/[0.03] px-3 py-1.5 text-left text-[11px] text-black/55 transition-colors hover:bg-black/[0.05]"
                              on:click={() => toggleThoughts(message.id)}
                            >
                              <span style="font-weight: 550;">Thoughts</span>
                              <span class="text-black/30">{message.thinking ? 'live' : 'saved'}</span>
                              {#if message.thinkingText}
                                <span class="flex h-4 w-4 items-center justify-center text-black/35">
                                  {message.thoughtsExpanded ? '−' : '+'}
                                </span>
                              {/if}
                            </button>
                          {/if}
                          {#if systemSettings.show_thinking_overlay && message.thinkingText && message.thoughtsExpanded}
                            <div class="mb-2 rounded-2xl border border-black/[0.05] bg-black/[0.025] px-3 py-2 text-[11.5px] leading-[1.55] text-black/48">
                              {message.thinkingText}
                            </div>
                          {/if}
                          {#if message.content}
                            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                            {@html renderMarkdown(message.content)}
                          {:else if sending && !message.thinking}
                            <span class="inline-flex items-center gap-[3px] px-0.5 py-1">
                              <span class="h-1.5 w-1.5 rounded-full bg-black/30" style="animation: typing-dot 1.2s ease-in-out infinite; animation-delay: 0ms;"></span>
                              <span class="h-1.5 w-1.5 rounded-full bg-black/30" style="animation: typing-dot 1.2s ease-in-out infinite; animation-delay: 200ms;"></span>
                              <span class="h-1.5 w-1.5 rounded-full bg-black/30" style="animation: typing-dot 1.2s ease-in-out infinite; animation-delay: 400ms;"></span>
                            </span>
                          {/if}
                        </div>
                      {/if}

                      {#if message.role === 'ASSISTANT' && message.content}
                        {#if message.grounded === false && activeChat?.knowledge_space_id}
                          <p class="mt-1.5 text-[10px] leading-snug text-amber-500/70">
                            No relevant materials found. This answer may rely on general model knowledge.
                          </p>
                        {/if}
                        {#if message.citations.length > 0}
                          <div class="mt-1.5">
                            <CitationDisclosure chunks={message.citations} />
                          </div>
                        {/if}
                        <div class="mt-1 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                          <button
                            type="button"
                            class="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] text-black/35 transition-colors hover:bg-black/[0.04] hover:text-black/60"
                            on:click={() => copyMessage(message.id, message.content)}
                          >
                            {#if copiedId === message.id}
                              <Check class="h-3 w-3 text-green-500" strokeWidth={2.25} />
                              <span class="text-green-500">Copied</span>
                            {:else}
                              <Copy class="h-3 w-3" strokeWidth={2} />
                            {/if}
                          </button>
                          <button
                            type="button"
                            class={`rounded-md p-1 transition-colors hover:bg-black/[0.04] ${
                              message.feedback_vote === 'LIKE' ? 'text-green-500' : 'text-black/35 hover:text-black/55'
                            }`}
                            title="Like"
                            on:click={() => submitFeedback(message.id, 'LIKE')}
                          >
                            <ThumbsUp class="h-3 w-3" strokeWidth={2} />
                          </button>
                          <button
                            type="button"
                            class={`rounded-md p-1 transition-colors hover:bg-black/[0.04] ${
                              message.feedback_vote === 'DISLIKE' ? 'text-red-400' : 'text-black/35 hover:text-black/55'
                            }`}
                            title="Dislike"
                            on:click={() => submitFeedback(message.id, 'DISLIKE')}
                          >
                            <ThumbsDown class="h-3 w-3" strokeWidth={2} />
                          </button>
                          {#if messages[messages.length - 1]?.id === message.id}
                            <button
                              type="button"
                              class="rounded-md p-1 text-black/35 transition-colors hover:bg-black/[0.04] hover:text-black/55"
                              title="Regenerate"
                              on:click={regenerate}
                            >
                              <RotateCcw class="h-3 w-3" strokeWidth={2} />
                            </button>
                          {/if}
                        </div>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            {/if}

              {#if chatError}
                <p class="mt-4 text-center text-[11px] text-red-400">{chatError}</p>
              {/if}
            </div>
          </div>

          {#if showScrollButton}
            <button
              type="button"
              class="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-[var(--border-default)] bg-[var(--bg-panel)] px-3 py-1.5 text-[11px] text-[var(--text-tertiary)] shadow-[0_2px_8px_rgba(0,0,0,0.10)] transition-all hover:bg-[var(--bg-surface-hover)] hover:text-[var(--text-secondary)]"
              on:click={() => scrollToBottom(true)}
            >
              <span>↓</span>
            </button>
          {/if}
        </div>

        <div class="px-4 pb-4 pt-3 sm:px-6">
          <div class="mx-auto w-full max-w-[var(--chat-shell-max)]">
            <div class="flex items-end gap-2 rounded-xl border border-[var(--border-default)] bg-[var(--bg-panel)] p-1.5 transition-opacity" style="box-shadow: 0 1px 6px rgba(0,0,0,0.05);">
              <textarea
              bind:this={composerEl}
              bind:value={composer}
              rows="1"
              placeholder="Ask anything…"
              disabled={sending}
              class="min-h-[28px] max-h-[100px] flex-1 resize-none border-0 bg-transparent px-1.5 py-1.5 text-[13px] text-black/70 outline-none placeholder:text-black/30 disabled:cursor-not-allowed"
              style="font-weight: 400; line-height: 1.5;"
              on:keydown={handleComposerKeydown}
            ></textarea>
            {#if sending}
              <button
                type="button"
                class="flex-shrink-0 rounded-lg p-1.5 transition-colors hover:bg-black/[0.06]"
                title="Stop generating"
                on:click={stopStreaming}
              >
                <div class="relative flex items-center justify-center">
                  <div class="absolute h-5 w-5 animate-spin rounded-full border-2 border-transparent border-t-[var(--accent-primary)] opacity-60"></div>
                  <Square class="h-3 w-3 text-[var(--accent-primary)]" strokeWidth={2.5} fill="currentColor" />
                </div>
              </button>
            {:else}
              <button
                type="button"
                disabled={!composer.trim()}
                class={`flex-shrink-0 rounded-lg p-1.5 transition-colors ${composer.trim() ? 'hover:bg-black/[0.06]' : ''} disabled:cursor-not-allowed disabled:opacity-30`}
                on:click={sendMessage}
              >
                <Send class={`h-3.5 w-3.5 ${composer.trim() ? 'text-[var(--accent-primary)]' : 'text-black/20'}`} strokeWidth={2} />
              </button>
            {/if}
            </div>
            <p class="mt-1.5 text-center text-[12px] text-black/80">AI can make mistakes. Verify important information.</p>
          </div>
        </div>
      </main>
    </div>
  {/if}
</div>
