<script lang="ts">
  import { Activity, Download, RefreshCcw, Settings2, Sparkles, X } from 'lucide-svelte';
  import type {
    EmbeddingProvider,
    KnowledgeSettings,
    OllamaHealth,
    ModelSettings,
    OllamaModel,
    ProviderOption,
    SystemSettings,
    UpdateModelSettings
  } from '$lib/types';

  export let open = false;
  export let modelSettings: ModelSettings;
  export let knowledgeSettings: KnowledgeSettings;
  export let systemSettings: SystemSettings;
  export let ollamaModels: OllamaModel[] = [];
  export let loadingOllamaModels = false;
  export let ollamaModelsError: string | null = null;
  export let checkingOllamaHealth = false;
  export let ollamaHealth: OllamaHealth | null = null;
  export let ollamaHealthError: string | null = null;
  export let pullingOllamaModel = false;
  export let ollamaPullStatus = '';
  export let ollamaPullProgress: number | null = null;
  export let ollamaPullError: string | null = null;
  export let ollamaPullDone = false;
  export let onClose: () => void;
  export let onSaveModel: (value: UpdateModelSettings) => Promise<void>;
  export let onSaveKnowledge: (value: KnowledgeSettings) => Promise<void>;
  export let onSaveSystem: (value: SystemSettings) => Promise<void>;
  export let onRefreshOllamaModels: (purpose: 'generation' | 'embedding', baseUrl?: string | null) => Promise<void>;
  export let onCheckOllamaHealth: (purpose: 'generation' | 'embedding', baseUrl?: string | null) => Promise<void>;
  export let onPullOllamaModel: (model: string, purpose: 'generation' | 'embedding', baseUrl?: string | null) => Promise<void>;

  let activeTab: 'Model' | 'Knowledge' | 'System' = 'Model';
  let savingModel = false;
  let savingKnowledge = false;
  let savingSystem = false;
  let modelSuccess = '';
  let knowledgeSuccess = '';
  let systemSuccess = '';
  let modelError = '';
  let knowledgeError = '';
  let systemError = '';
  let generationApiKey = '';
  let embeddingApiKey = '';
  let pullModel = '';
  let draftModel = createModelDraft(modelSettings);
  let draftKnowledge = { ...knowledgeSettings };
  let draftSystem = { ...systemSettings };
  let wasOpen = false;

  function createModelDraft(source: ModelSettings): UpdateModelSettings {
    return {
      generation: {
        provider: source.generation.provider,
        model: source.generation.model,
        api_key: '',
        base_url: source.generation.base_url,
        system_prompt: source.generation.system_prompt,
        temperature: source.generation.temperature,
        max_tokens: source.generation.max_tokens,
        context_max_tokens: source.generation.context_max_tokens,
        auto_compress: source.generation.auto_compress
      },
      embedding: {
        provider: source.embedding.provider,
        model: source.embedding.model,
        api_key: '',
        base_url: source.embedding.base_url
      }
    };
  }

  function syncDrafts() {
    draftModel = createModelDraft(modelSettings);
    draftKnowledge = { ...knowledgeSettings };
    draftSystem = { ...systemSettings };
    generationApiKey = '';
    embeddingApiKey = '';
    pullModel = '';
    modelSuccess = '';
    knowledgeSuccess = '';
    systemSuccess = '';
    modelError = '';
    knowledgeError = '';
    systemError = '';
  }

  $: if (open && !wasOpen) {
    syncDrafts();
    wasOpen = true;
  }

  $: if (!open && wasOpen) {
    wasOpen = false;
  }

  function optionFor(options: ProviderOption[], providerId: string): ProviderOption | undefined {
    return options.find((option) => option.id === providerId);
  }

  function handleGenerationProviderChange() {
    const option = optionFor(modelSettings.generation_provider_options, draftModel.generation.provider);
    if (option) {
      draftModel.generation.model = option.default_model;
    }
    draftModel.generation.base_url = draftModel.generation.provider === 'ollama'
      ? draftModel.generation.base_url || 'http://ollama:11434'
      : draftModel.generation.provider === 'openai'
        ? draftModel.generation.base_url || 'https://api.openai.com/v1'
        : null;
    if (draftModel.generation.provider === 'ollama') {
      void onRefreshOllamaModels('generation', draftModel.generation.base_url);
    }
  }

  function handleEmbeddingProviderChange() {
    const option = optionFor(modelSettings.embedding_provider_options, draftModel.embedding.provider);
    if (option) {
      draftModel.embedding.model = option.default_model;
    }
    draftModel.embedding.base_url =
      draftModel.embedding.provider === 'ollama'
        ? draftModel.embedding.base_url || 'http://ollama:11434'
        : draftModel.embedding.provider === 'openai'
          ? draftModel.embedding.base_url || 'https://api.openai.com/v1'
          : null;
    if (draftModel.embedding.provider === 'ollama') {
      void onRefreshOllamaModels('embedding', draftModel.embedding.base_url);
    }
  }

  async function saveModelSettings() {
    savingModel = true;
    modelSuccess = '';
    modelError = '';
    try {
      await onSaveModel({
        generation: {
          ...draftModel.generation,
          api_key: generationApiKey.trim() || null
        },
        embedding: {
          ...draftModel.embedding,
          api_key: embeddingApiKey.trim() || null
        }
      });
      generationApiKey = '';
      embeddingApiKey = '';
      modelSuccess = 'Configuration saved and activated.';
    } catch (error) {
      modelError = error instanceof Error ? error.message : 'Failed to save model settings.';
    } finally {
      savingModel = false;
    }
  }

  async function saveKnowledgeSettings() {
    savingKnowledge = true;
    knowledgeSuccess = '';
    knowledgeError = '';
    try {
      await onSaveKnowledge(draftKnowledge);
      knowledgeSuccess = 'Knowledge configuration saved.';
    } catch (error) {
      knowledgeError = error instanceof Error ? error.message : 'Failed to save knowledge settings.';
    } finally {
      savingKnowledge = false;
    }
  }

  async function saveSystemSettings() {
    savingSystem = true;
    systemSuccess = '';
    systemError = '';
    try {
      await onSaveSystem(draftSystem);
      systemSuccess = 'System configuration saved.';
    } catch (error) {
      systemError = error instanceof Error ? error.message : 'Failed to save system settings.';
    } finally {
      savingSystem = false;
    }
  }

  function formatBytes(bytes: number): string {
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
    if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(0)} MB`;
    return `${bytes} B`;
  }

  function ollamaBaseUrl(purpose: 'generation' | 'embedding'): string | null {
    return purpose === 'generation'
      ? draftModel.generation.base_url ?? null
      : draftModel.embedding.base_url ?? null;
  }

  function isEmbeddingApiKeyProvider(provider: EmbeddingProvider): boolean {
    return provider === 'openai' || provider === 'google';
  }
</script>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="fixed inset-0 z-50" role="dialog" aria-modal="true" tabindex="-1" on:click|self={onClose}>
    <div class="absolute inset-0 bg-[var(--bg-overlay)]"></div>
    <div class="absolute inset-x-6 top-6 mx-auto max-w-[1120px] rounded-[var(--radius-2xl)] border border-[var(--border-default)] bg-[var(--bg-panel)] p-6 shadow-[var(--shadow-lg)]">
      <div class="flex items-start justify-between gap-4 border-b border-black/[0.06] pb-5">
        <div class="flex items-center gap-3">
          <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-black/[0.04]">
            <Settings2 class="h-5 w-5 text-black/55" strokeWidth={1.5} />
          </div>
          <div>
            <p class="text-[11px] uppercase tracking-wide text-black/30">Settings</p>
            <h2 class="mt-0.5 text-[18px] text-black/80" style="font-weight: 600;">Assistant configuration</h2>
          </div>
        </div>
        <button
          type="button"
          class="rounded-xl p-2 text-black/35 transition-colors hover:bg-black/[0.04] hover:text-black/60"
          aria-label="Close settings"
          on:click={onClose}
        >
          <X class="h-4 w-4" strokeWidth={2} />
        </button>
      </div>

      <div class="mt-5 flex items-center gap-2 border-b border-black/[0.06] pb-4">
        {#each ['Model', 'Knowledge', 'System'] as tab}
          <button
            type="button"
            class={`rounded-[var(--radius-md)] px-3 py-2 text-[12px] transition-colors ${
              activeTab === tab
                ? 'bg-black/[0.07] text-black/75'
                : 'text-black/40 hover:bg-black/[0.04] hover:text-black/60'
            }`}
            style={`font-weight: ${activeTab === tab ? 550 : 450};`}
            on:click={() => (activeTab = tab as typeof activeTab)}
          >
            {tab}
          </button>
        {/each}
      </div>

      <div class="mt-6 max-h-[72vh] overflow-y-auto pr-1 custom-scrollbar">
        {#if activeTab === 'Model'}
          <div class="space-y-10">
            <div>
              <p class="mb-4 text-[11px] uppercase tracking-wide text-black/30">Generation model</p>
              <div class="max-w-md space-y-4">
                <div>
                  <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Provider</label>
                  <div class="relative">
                    <select
                      bind:value={draftModel.generation.provider}
                      class="w-full appearance-none rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 pr-8 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                      on:change={handleGenerationProviderChange}
                    >
                      {#each modelSettings.generation_provider_options as provider (provider.id)}
                        <option value={provider.id}>{provider.label}</option>
                      {/each}
                    </select>
                    <svg class="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-black/35" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"/>
                    </svg>
                  </div>
                </div>

                <div>
                  <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Model</label>
                  {#if draftModel.generation.provider === 'ollama'}
                    <div class="flex items-center gap-2">
                      <div class="relative flex-1">
                        <select
                          bind:value={draftModel.generation.model}
                          disabled={loadingOllamaModels}
                          class="w-full appearance-none rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 pr-8 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20 disabled:opacity-50"
                        >
                          {#if loadingOllamaModels}
                            <option value="">Loading…</option>
                          {:else if ollamaModels.length === 0}
                            <option value="">No models pulled yet</option>
                          {:else}
                            {#each ollamaModels as model (model.name)}
                              <option value={model.name}>{model.name}{model.size ? ` (${formatBytes(model.size)})` : ''}</option>
                            {/each}
                          {/if}
                        </select>
                        <svg class="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-black/35" viewBox="0 0 16 16" fill="currentColor">
                          <path d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"/>
                        </svg>
                      </div>
                      <button
                        type="button"
                        class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] transition-colors hover:bg-black/[0.04] disabled:opacity-40"
                        disabled={checkingOllamaHealth}
                        title="Check Ollama availability"
                        on:click={() => void onCheckOllamaHealth('generation', ollamaBaseUrl('generation'))}
                      >
                        <Activity class={`h-3.5 w-3.5 text-black/45 ${checkingOllamaHealth ? 'animate-pulse' : ''}`} strokeWidth={1.8} />
                      </button>
                      <button
                        type="button"
                        class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] transition-colors hover:bg-black/[0.04] disabled:opacity-40"
                        disabled={loadingOllamaModels}
                        title="Refresh models"
                        on:click={() => onRefreshOllamaModels('generation', ollamaBaseUrl('generation'))}
                      >
                        <RefreshCcw class={`h-3.5 w-3.5 text-black/45 ${loadingOllamaModels ? 'animate-spin' : ''}`} strokeWidth={1.8} />
                      </button>
                    </div>
                    <div class="mt-2 flex items-center gap-2">
                      <input
                        bind:value={pullModel}
                        class="flex-1 rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                        placeholder="Pull model…"
                      />
                      <button
                        type="button"
                        class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] transition-colors hover:bg-black/[0.04] disabled:opacity-40"
                        disabled={pullingOllamaModel || !pullModel.trim()}
                        title="Pull model"
                        on:click={async () => {
                          await onPullOllamaModel(pullModel, 'generation', ollamaBaseUrl('generation'));
                          if (!ollamaPullError) pullModel = '';
                        }}
                      >
                        <Download class={`h-3.5 w-3.5 text-black/45 ${pullingOllamaModel ? 'animate-bounce' : ''}`} strokeWidth={1.8} />
                      </button>
                    </div>
                    <p class="mt-1 text-[11px] text-black/35">
                      {optionFor(modelSettings.generation_provider_options, draftModel.generation.provider)?.hint}
                    </p>
                  {:else}
                    <input
                      bind:value={draftModel.generation.model}
                      class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                      placeholder={optionFor(modelSettings.generation_provider_options, draftModel.generation.provider)?.default_model}
                    />
                    <p class="mt-1 text-[11px] text-black/35">
                      {optionFor(modelSettings.generation_provider_options, draftModel.generation.provider)?.hint}
                    </p>
                  {/if}
                </div>

                {#if draftModel.generation.provider === 'ollama'}
                  <div>
                    <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Ollama URL</label>
                    <input
                      bind:value={draftModel.generation.base_url}
                      class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                      placeholder="http://ollama:11434"
                    />
                  </div>
                {:else if draftModel.generation.provider === 'openai'}
                  <div>
                    <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Base URL</label>
                    <input
                      bind:value={draftModel.generation.base_url}
                      class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                      placeholder="https://api.openai.com/v1"
                    />
                    <p class="mt-1 text-[11px] text-black/35">Use this for OpenAI cloud or a self-hosted OpenAI-compatible endpoint.</p>
                  </div>
                {/if}

                {#if draftModel.generation.provider !== 'ollama'}
                  <div>
                    <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">
                      API key {#if modelSettings.generation.provider === draftModel.generation.provider && modelSettings.generation.api_key_set}(leave blank to keep existing){/if}
                    </label>
                    <input
                      bind:value={generationApiKey}
                      type="password"
                      class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                      placeholder={modelSettings.generation.provider === draftModel.generation.provider && modelSettings.generation.api_key_set ? '••••••••' : 'Paste provider API key'}
                    />
                  </div>
                {/if}

                <div>
                  <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">
                    System prompt <span class="font-normal text-black/30">(global default)</span>
                  </label>
                  <textarea
                    bind:value={draftModel.generation.system_prompt}
                    rows="3"
                    class="w-full resize-y rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[12.5px] text-black/65 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                    placeholder="You are a helpful AI assistant."
                  ></textarea>
                </div>

                <div>
                  <div class="mb-1.5 flex items-center justify-between">
                    <label class="text-[12px] text-black/55" style="font-weight: 500;">Temperature <span class="font-normal text-black/30">(0–2)</span></label>
                    <span class="text-[12px] text-black/55 tabular-nums" style="font-weight: 500;">{draftModel.generation.temperature.toFixed(2)}</span>
                  </div>
                  <input
                    bind:value={draftModel.generation.temperature}
                    type="range"
                    min="0"
                    max="2"
                    step="0.05"
                    class="h-1.5 w-full cursor-pointer appearance-none rounded-full"
                    style={`accent-color: var(--accent-primary); background: linear-gradient(to right, var(--accent-primary) 0%, var(--accent-primary) ${draftModel.generation.temperature * 50}%, rgba(0,0,0,0.08) ${draftModel.generation.temperature * 50}%, rgba(0,0,0,0.08) 100%);`}
                  />
                  <div class="mt-0.5 flex justify-between text-[10px] text-black/25">
                    <span>Precise</span>
                    <span>Creative</span>
                  </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                  <div>
                    <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Max tokens</label>
                    <input
                      bind:value={draftModel.generation.max_tokens}
                      type="number"
                      class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                    />
                  </div>
                  <div>
                    <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Context tokens</label>
                    <input
                      bind:value={draftModel.generation.context_max_tokens}
                      type="number"
                      class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                    />
                  </div>
                </div>

                <div class="flex items-center gap-3">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={draftModel.generation.auto_compress}
                    class={`relative h-5 w-9 rounded-full transition-colors ${draftModel.generation.auto_compress ? 'bg-[var(--accent-primary)]' : 'bg-black/15'}`}
                    on:click={() => (draftModel.generation.auto_compress = !draftModel.generation.auto_compress)}
                  >
                    <span class={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${draftModel.generation.auto_compress ? 'translate-x-4' : 'translate-x-0.5'}`}></span>
                  </button>
                  <div>
                    <p class="text-[12.5px] text-black/65" style="font-weight: 500;">Auto-compress context</p>
                    <p class="text-[11px] text-black/35">Summarize older messages when context fills up.</p>
                  </div>
                </div>

                {#if ollamaHealth}
                  <p class="text-[11px] text-black/40">
                    Ollama reachable. <span class="font-medium text-black/60">{ollamaHealth.model_count}</span> models available.
                  </p>
                {/if}
                {#if ollamaHealthError}
                  <p class="text-[12px] text-[var(--status-error)]">{ollamaHealthError}</p>
                {/if}
                {#if pullingOllamaModel || ollamaPullDone || ollamaPullProgress !== null}
                  <div class="rounded-[var(--radius-sm)] bg-black/[0.03] px-3 py-2.5">
                    <div class="flex items-center justify-between gap-3">
                      <p class="truncate text-[11px] text-black/50">{ollamaPullStatus || 'Starting…'}</p>
                      {#if ollamaPullDone}
                        <span class="text-[11px] text-green-600" style="font-weight: 500;">Done</span>
                      {:else if ollamaPullProgress !== null}
                        <span class="text-[11px] text-black/40">{ollamaPullProgress}%</span>
                      {/if}
                    </div>
                    {#if ollamaPullProgress !== null}
                      <div class="mt-2 h-1 w-full overflow-hidden rounded-full bg-black/[0.08]">
                        <div
                          class={`h-full rounded-full transition-all duration-300 ${ollamaPullDone ? 'bg-green-500' : 'bg-[var(--accent-primary)]'}`}
                          style={`width: ${Math.max(4, ollamaPullProgress)}%`}
                        ></div>
                      </div>
                    {/if}
                  </div>
                {/if}
                {#if ollamaPullError}
                  <p class="text-[12px] text-[var(--status-error)]">{ollamaPullError}</p>
                {/if}
              </div>
            </div>

            <div class="border-t border-[var(--border-default)] pt-8">
              <p class="mb-1 text-[11px] uppercase tracking-wide text-black/30">Embedding model</p>
              <p class="mb-4 text-[12px] text-black/40">Used to encode documents and queries for RAG retrieval.</p>
              <div class="max-w-md space-y-4">
                <div>
                  <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Provider</label>
                  <div class="relative">
                    <select
                      bind:value={draftModel.embedding.provider}
                      class="w-full appearance-none rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 pr-8 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                      on:change={handleEmbeddingProviderChange}
                    >
                      {#each modelSettings.embedding_provider_options as provider (provider.id)}
                        <option value={provider.id}>{provider.label}</option>
                      {/each}
                    </select>
                    <svg class="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-black/35" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"/>
                    </svg>
                  </div>
                </div>

                {#if draftModel.embedding.provider === 'sentence-transformers'}
                  <div class="rounded-[var(--radius-md)] bg-blue-50 px-3.5 py-3">
                    <p class="text-[11.5px] leading-relaxed text-blue-700">Runs locally on CPU. The model is downloaded on first use and cached automatically.</p>
                  </div>
                {/if}

                <div>
                  <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Model</label>
                  <div class="flex items-center gap-2">
                    <input
                      bind:value={draftModel.embedding.model}
                      class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                      placeholder={optionFor(modelSettings.embedding_provider_options, draftModel.embedding.provider)?.default_model}
                    />
                    {#if draftModel.embedding.provider === 'ollama'}
                      <button
                        type="button"
                        class="flex h-9 w-9 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] transition-colors hover:bg-black/[0.04] disabled:opacity-40"
                        disabled={loadingOllamaModels}
                        title="Refresh models"
                        on:click={() => onRefreshOllamaModels('embedding', ollamaBaseUrl('embedding'))}
                      >
                        <RefreshCcw class={`h-3.5 w-3.5 text-black/45 ${loadingOllamaModels ? 'animate-spin' : ''}`} strokeWidth={1.8} />
                      </button>
                    {/if}
                  </div>
                  <p class="mt-1 text-[11px] text-black/35">
                    {optionFor(modelSettings.embedding_provider_options, draftModel.embedding.provider)?.hint}
                  </p>
                </div>

                {#if draftModel.embedding.provider === 'openai' || draftModel.embedding.provider === 'ollama'}
                  <div>
                    <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">
                      {draftModel.embedding.provider === 'ollama' ? 'Ollama URL' : 'Base URL'}
                    </label>
                    <input
                      bind:value={draftModel.embedding.base_url}
                      class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                      placeholder={draftModel.embedding.provider === 'ollama' ? 'http://ollama:11434' : 'https://api.openai.com/v1'}
                    />
                  </div>
                {/if}

                {#if isEmbeddingApiKeyProvider(draftModel.embedding.provider)}
                  <div>
                    <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">
                      API key {#if modelSettings.embedding.provider === draftModel.embedding.provider && modelSettings.embedding.api_key_set}(leave blank to keep existing){/if}
                    </label>
                    <input
                      bind:value={embeddingApiKey}
                      type="password"
                      class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                      placeholder={modelSettings.embedding.provider === draftModel.embedding.provider && modelSettings.embedding.api_key_set ? '••••••••' : 'Paste provider API key'}
                    />
                  </div>
                {/if}

                <div class="flex items-center gap-2 rounded-[var(--radius-sm)] bg-black/[0.03] px-3 py-2.5">
                  <Sparkles class="h-3.5 w-3.5 text-black/35" strokeWidth={1.8} />
                  <p class="text-[11.5px] text-black/50">
                    Active: <span class="font-medium text-black/65">{modelSettings.embedding.provider} / {modelSettings.embedding.model}</span>
                  </p>
                </div>
              </div>
            </div>

            {#if ollamaModelsError}
              <p class="text-[12px] text-[var(--status-error)]">{ollamaModelsError}</p>
            {/if}
            {#if modelError}
              <p class="text-[12px] text-[var(--status-error)]">{modelError}</p>
            {/if}
            {#if modelSuccess}
              <p class="text-[12px] text-[var(--status-success)]">{modelSuccess}</p>
            {/if}
            <button
              type="button"
              class="inline-flex h-[var(--size-control-height-md)] items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-4 text-sm text-[var(--text-inverse)] shadow-[var(--shadow-sm)] transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={savingModel || !draftModel.generation.model.trim() || !draftModel.embedding.model.trim()}
              on:click={saveModelSettings}
            >
              {savingModel ? 'Saving…' : 'Save & activate'}
            </button>
          </div>
        {:else if activeTab === 'Knowledge'}
          <div class="max-w-[540px] space-y-4">
            <p class="text-[11px] uppercase tracking-wide text-black/30">Knowledge settings</p>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Chunk size</label>
                <input bind:value={draftKnowledge.chunk_size} type="number" class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20" />
              </div>
              <div>
                <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Chunk overlap</label>
                <input bind:value={draftKnowledge.chunk_overlap} type="number" class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20" />
              </div>
              <div>
                <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Top K</label>
                <input bind:value={draftKnowledge.retrieval_top_k} type="number" class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20" />
              </div>
              <div>
                <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Threshold</label>
                <input bind:value={draftKnowledge.relevance_threshold} type="number" step="0.05" class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20" />
              </div>
            </div>
            <div class="flex items-center gap-3">
              <button
                type="button"
                role="switch"
                aria-checked={draftKnowledge.hybrid_search_enabled}
                class={`relative h-5 w-9 rounded-full transition-colors ${draftKnowledge.hybrid_search_enabled ? 'bg-[var(--accent-primary)]' : 'bg-black/15'}`}
                on:click={() => (draftKnowledge.hybrid_search_enabled = !draftKnowledge.hybrid_search_enabled)}
              >
                <span class={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${draftKnowledge.hybrid_search_enabled ? 'translate-x-4' : 'translate-x-0.5'}`}></span>
              </button>
              <div>
                <p class="text-[12.5px] text-black/65" style="font-weight: 500;">Hybrid search</p>
                <p class="text-[11px] text-black/35">Reserved for lexical + vector retrieval tuning.</p>
              </div>
            </div>
            <div>
              <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">RAG template</label>
              <textarea bind:value={draftKnowledge.rag_template} rows="5" class="w-full resize-y rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[12.5px] text-black/65 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"></textarea>
            </div>
            {#if knowledgeError}
              <p class="text-[12px] text-[var(--status-error)]">{knowledgeError}</p>
            {/if}
            {#if knowledgeSuccess}
              <p class="text-[12px] text-[var(--status-success)]">{knowledgeSuccess}</p>
            {/if}
            <button
              type="button"
              class="inline-flex h-[var(--size-control-height-md)] items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-4 text-sm text-[var(--text-inverse)] shadow-[var(--shadow-sm)] transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={savingKnowledge}
              on:click={saveKnowledgeSettings}
            >
              {savingKnowledge ? 'Saving…' : 'Save knowledge settings'}
            </button>
          </div>
        {:else}
          <div class="max-w-[540px] space-y-4">
            <p class="text-[11px] uppercase tracking-wide text-black/30">System settings</p>
            <div>
              <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">App name</label>
              <input bind:value={draftSystem.app_name} class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20" />
            </div>
            <div>
              <label class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Theme</label>
              <div class="flex items-center gap-2">
                {#each ['light', 'dark', 'system'] as theme}
                  <button
                    type="button"
                    class={`rounded-[var(--radius-md)] px-3 py-2 text-[12px] transition-colors ${draftSystem.theme === theme ? 'bg-black/[0.07] text-black/75' : 'text-black/40 hover:bg-black/[0.04] hover:text-black/60'}`}
                    style={`font-weight: ${draftSystem.theme === theme ? 550 : 450};`}
                    on:click={() => (draftSystem.theme = theme as typeof draftSystem.theme)}
                  >
                    {theme}
                  </button>
                {/each}
              </div>
            </div>
            {#if systemError}
              <p class="text-[12px] text-[var(--status-error)]">{systemError}</p>
            {/if}
            {#if systemSuccess}
              <p class="text-[12px] text-[var(--status-success)]">{systemSuccess}</p>
            {/if}
            <button
              type="button"
              class="inline-flex h-[var(--size-control-height-md)] items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-4 text-sm text-[var(--text-inverse)] shadow-[var(--shadow-sm)] transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={savingSystem}
              on:click={saveSystemSettings}
            >
              {savingSystem ? 'Saving…' : 'Save system settings'}
            </button>
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}
