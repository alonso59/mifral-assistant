<script lang="ts">
  import { BookOpen, Pencil, Plus, Trash2, Upload, X } from 'lucide-svelte';
  import type { Chat, KnowledgeDocument, KnowledgeSpace } from '$lib/types';

  export let open = false;
  export let spaces: KnowledgeSpace[] = [];
  export let activeChat: Chat | null = null;
  export let onClose: () => void;
  export let onCreateSpace: (name: string, description: string | null) => Promise<void>;
  export let onRenameSpace: (spaceId: string, name: string, description: string | null) => Promise<void>;
  export let onDeleteSpace: (spaceId: string) => Promise<void>;
  export let onSelectSpace: (space: KnowledgeSpace) => Promise<void>;
  export let onClearSelection: () => Promise<void>;
  export let onUpload: (spaceId: string, file: File) => Promise<void>;

  const stageLabels: Record<KnowledgeDocument['processing_stage'], string> = {
    QUEUED: 'Queued',
    EXTRACTING: 'Extracting',
    CHUNKING: 'Chunking',
    EMBEDDING: 'Embedding',
    FINALIZING: 'Finalizing',
    READY: 'Ready',
    FAILED: 'Failed'
  };

  let newSpaceName = '';
  let newSpaceDescription = '';
  let editingSpaceId: string | null = null;
  let editName = '';
  let editDescription = '';
  let actionError = '';
  let creating = false;
  let savingSpaceId: string | null = null;
  let uploadingSpaceId: string | null = null;

  $: activeSpaceId = activeChat?.knowledge_space_id ?? null;

  function isInProgress(document: KnowledgeDocument): boolean {
    return document.processing_status === 'PENDING' || document.processing_status === 'PROCESSING';
  }

  function progressPercent(document: KnowledgeDocument): number {
    if (document.processing_status === 'READY') return 100;
    if (document.processing_status === 'FAILED') {
      return Math.max(Math.min(document.processing_progress_percent || 0, 100), 5);
    }
    return Math.min(Math.max(document.processing_progress_percent || 8, 5), 95);
  }

  function progressLabel(document: KnowledgeDocument): string {
    if (document.processing_status === 'READY') {
      return document.processing_message || 'Ready for grounded chat.';
    }
    if (document.processing_status === 'FAILED') {
      return document.processing_message || 'Document processing failed. Re-upload to try again.';
    }
    return document.processing_message || 'Indexing in progress...';
  }

  function documentTone(document: KnowledgeDocument): string {
    if (document.processing_status === 'READY') return 'bg-green-500/10 text-green-700';
    if (document.processing_status === 'FAILED') return 'bg-red-500/10 text-red-600';
    return 'bg-amber-500/10 text-amber-700';
  }

  function startEditing(space: KnowledgeSpace) {
    editingSpaceId = space.id;
    editName = space.name;
    editDescription = space.description ?? '';
    actionError = '';
  }

  function stopEditing() {
    editingSpaceId = null;
    editName = '';
    editDescription = '';
  }

  async function createSpace() {
    if (!newSpaceName.trim() || creating) return;
    creating = true;
    actionError = '';
    try {
      await onCreateSpace(newSpaceName.trim(), newSpaceDescription.trim() || null);
      newSpaceName = '';
      newSpaceDescription = '';
    } catch (error) {
      actionError = error instanceof Error ? error.message : 'Failed to create knowledge space.';
    } finally {
      creating = false;
    }
  }

  async function renameSpace(spaceId: string) {
    if (!editName.trim() || savingSpaceId) return;
    savingSpaceId = spaceId;
    actionError = '';
    try {
      await onRenameSpace(spaceId, editName.trim(), editDescription.trim() || null);
      stopEditing();
    } catch (error) {
      actionError = error instanceof Error ? error.message : 'Failed to rename knowledge space.';
    } finally {
      savingSpaceId = null;
    }
  }

  async function deleteSpace(spaceId: string) {
    if (savingSpaceId) return;
    savingSpaceId = spaceId;
    actionError = '';
    try {
      await onDeleteSpace(spaceId);
      if (editingSpaceId === spaceId) {
        stopEditing();
      }
    } catch (error) {
      actionError = error instanceof Error ? error.message : 'Failed to delete knowledge space.';
    } finally {
      savingSpaceId = null;
    }
  }

  async function selectSpace(space: KnowledgeSpace) {
    if (savingSpaceId) return;
    savingSpaceId = space.id;
    actionError = '';
    try {
      await onSelectSpace(space);
    } catch (error) {
      actionError = error instanceof Error ? error.message : 'Failed to select knowledge space.';
    } finally {
      savingSpaceId = null;
    }
  }

  async function clearSelection() {
    if (savingSpaceId) return;
    savingSpaceId = activeSpaceId;
    actionError = '';
    try {
      await onClearSelection();
    } catch (error) {
      actionError = error instanceof Error ? error.message : 'Failed to clear knowledge selection.';
    } finally {
      savingSpaceId = null;
    }
  }

  async function handleUpload(spaceId: string, event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    const file = target.files?.[0];
    if (!file || uploadingSpaceId) return;

    uploadingSpaceId = spaceId;
    actionError = '';
    try {
      await onUpload(spaceId, file);
    } catch (error) {
      actionError = error instanceof Error ? error.message : 'Failed to upload document.';
    } finally {
      target.value = '';
      uploadingSpaceId = null;
    }
  }
</script>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="fixed inset-0 z-50" role="dialog" aria-modal="true" tabindex="-1" on:click|self={onClose}>
    <div class="absolute inset-0 bg-[var(--bg-overlay)]"></div>

    <div class="absolute inset-x-2 top-2 mx-auto max-h-[calc(100vh-1rem)] max-w-[1080px] overflow-hidden rounded-[var(--radius-2xl)] border border-[var(--border-default)] bg-[var(--bg-panel)] p-4 shadow-[var(--shadow-lg)] sm:inset-x-6 sm:top-6 sm:max-h-[calc(100vh-3rem)] sm:p-6">
      <div class="flex items-start justify-between gap-4 border-b border-black/[0.06] pb-5">
        <div class="flex items-center gap-3">
          <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-black/[0.04]">
            <BookOpen class="h-5 w-5 text-black/55" strokeWidth={1.7} />
          </div>
          <div>
            <p class="text-[11px] uppercase tracking-wide text-black/30">Knowledge</p>
            <h2 class="mt-0.5 text-[18px] text-black/80" style="font-weight: 600;">Manage grounded context</h2>
          </div>
        </div>
        <button
          type="button"
          class="rounded-xl p-2 text-black/35 transition-colors hover:bg-black/[0.04] hover:text-black/60"
          aria-label="Close knowledge overlay"
          on:click={onClose}
        >
          <X class="h-4 w-4" strokeWidth={2} />
        </button>
      </div>

      <div class="mt-6 grid max-h-[72vh] gap-6 overflow-hidden lg:grid-cols-[320px,minmax(0,1fr)]">
        <div class="space-y-4 overflow-y-auto pr-1 custom-scrollbar">
          <section class="rounded-[var(--radius-lg)] border border-[var(--border-default)] bg-[var(--bg-panel-muted)] p-4">
            <p class="text-[11px] uppercase tracking-wide text-black/30">Current mode</p>
            <p class="mt-2 text-[15px] text-black/75" style="font-weight: 600;">
              {#if activeSpaceId}
                {spaces.find((space) => space.id === activeSpaceId)?.name ?? 'Selected knowledge'}
              {:else}
                General
              {/if}
            </p>
            <p class="mt-1 text-[12px] leading-relaxed text-black/42">
              {#if activeSpaceId}
                This chat retrieves only from the selected knowledge space.
              {:else}
                This chat answers from general model knowledge unless you select a space.
              {/if}
            </p>
            {#if activeSpaceId}
              <button
                type="button"
                class="mt-4 inline-flex h-[var(--size-control-height-sm)] items-center justify-center rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-[12px] text-black/60 transition-colors hover:bg-black/[0.04]"
                on:click={clearSelection}
              >
                Use general mode
              </button>
            {/if}
          </section>

          <section class="rounded-[var(--radius-lg)] border border-[var(--border-default)] bg-[var(--bg-panel)] p-4">
            <div class="flex items-center gap-2">
              <Plus class="h-4 w-4 text-black/40" strokeWidth={1.9} />
              <p class="text-[13px] text-black/68" style="font-weight: 600;">New knowledge space</p>
            </div>

            <div class="mt-4 space-y-3">
              <div>
                <label for="knowledge-name" class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Name</label>
                <input
                  id="knowledge-name"
                  bind:value={newSpaceName}
                  class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                  placeholder="Knowledge space name"
                />
              </div>

              <div>
                <label for="knowledge-description" class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Description</label>
                <textarea
                  id="knowledge-description"
                  bind:value={newSpaceDescription}
                  rows="3"
                  class="w-full resize-none rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[12.5px] text-black/70 outline-none transition-colors placeholder:text-black/25 focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                  placeholder="Optional description"
                ></textarea>
              </div>

              <button
                type="button"
                class="inline-flex h-[var(--size-control-height-md)] items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-4 text-sm text-[var(--text-inverse)] shadow-[var(--shadow-sm)] transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={creating || !newSpaceName.trim()}
                on:click={createSpace}
              >
                {creating ? 'Creating...' : 'Create knowledge'}
              </button>
            </div>
          </section>

          {#if actionError}
            <p class="text-[12px] text-[var(--status-error)]">{actionError}</p>
          {/if}
        </div>

        <div class="min-h-0 overflow-y-auto pr-1 custom-scrollbar">
          {#if spaces.length === 0}
            <div class="flex h-full min-h-[280px] flex-col items-center justify-center rounded-[var(--radius-xl)] border border-dashed border-[var(--border-default)] bg-[var(--bg-panel-muted)] px-6 text-center">
              <div class="flex h-12 w-12 items-center justify-center rounded-full bg-black/[0.04]">
                <BookOpen class="h-5 w-5 text-black/45" strokeWidth={1.8} />
              </div>
              <p class="mt-4 text-[14px] text-black/62" style="font-weight: 600;">No knowledge spaces yet</p>
              <p class="mt-1 max-w-[320px] text-[12px] leading-relaxed text-black/40">
                Create a space, upload documents, and then select it for the active chat when you want grounded answers.
              </p>
            </div>
          {:else}
            <div class="space-y-3" data-testid="knowledge-overlay-list">
              {#each spaces as space (space.id)}
                <section
                  class={`rounded-[var(--radius-xl)] border p-4 transition-colors ${
                    activeSpaceId === space.id
                      ? 'border-[var(--accent-primary)]/40 bg-[var(--bg-panel-muted)]'
                      : 'border-[var(--border-default)] bg-[var(--bg-panel)]'
                  }`}
                >
                  <div class="flex items-start justify-between gap-4">
                    <div class="min-w-0">
                      <div class="flex flex-wrap items-center gap-2">
                        <h3 class="truncate text-[15px] text-black/75" style="font-weight: 600;">{space.name}</h3>
                        <span class={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${activeSpaceId === space.id ? 'bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]' : 'bg-black/[0.05] text-black/35'}`}>
                          {activeSpaceId === space.id ? 'Selected' : 'Available'}
                        </span>
                        <span class="text-[11px] text-black/32">{space.documents.length} docs</span>
                      </div>
                      {#if space.description}
                        <p class="mt-1 text-[12px] leading-relaxed text-black/42">{space.description}</p>
                      {/if}
                    </div>

                    <div class="flex items-center gap-1">
                      <button
                        type="button"
                        class="rounded-lg p-2 text-black/35 transition-colors hover:bg-black/[0.04] hover:text-black/60"
                        aria-label={`Rename ${space.name}`}
                        on:click={() => startEditing(space)}
                      >
                        <Pencil class="h-3.5 w-3.5" strokeWidth={1.9} />
                      </button>
                      <button
                        type="button"
                        class="rounded-lg p-2 text-black/35 transition-colors hover:bg-black/[0.04] hover:text-red-500"
                        aria-label={`Delete ${space.name}`}
                        on:click={() => deleteSpace(space.id)}
                      >
                        <Trash2 class="h-3.5 w-3.5" strokeWidth={1.9} />
                      </button>
                    </div>
                  </div>

                  {#if editingSpaceId === space.id}
                    <div class="mt-4 grid gap-3 sm:grid-cols-2">
                      <div class="sm:col-span-1">
                        <label for={`rename-name-${space.id}`} class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Name</label>
                        <input
                          id={`rename-name-${space.id}`}
                          bind:value={editName}
                          class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                        />
                      </div>
                      <div class="sm:col-span-1">
                        <label for={`rename-description-${space.id}`} class="mb-1.5 block text-[12px] text-black/55" style="font-weight: 500;">Description</label>
                        <input
                          id={`rename-description-${space.id}`}
                          bind:value={editDescription}
                          class="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-2 text-[13px] text-black/70 outline-none transition-colors focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]/20"
                        />
                      </div>
                      <div class="sm:col-span-2 flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          class="inline-flex h-[var(--size-control-height-sm)] items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-3 text-[12px] text-[var(--text-inverse)] transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={savingSpaceId === space.id || !editName.trim()}
                          on:click={() => renameSpace(space.id)}
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          class="inline-flex h-[var(--size-control-height-sm)] items-center justify-center rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-[12px] text-black/60 transition-colors hover:bg-black/[0.04]"
                          on:click={stopEditing}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  {/if}

                  <div class="mt-4 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      data-testid={`select-space-${space.id}`}
                      class={`inline-flex h-[var(--size-control-height-sm)] items-center justify-center rounded-[var(--radius-md)] px-3 text-[12px] transition-colors ${
                        activeSpaceId === space.id
                          ? 'bg-black/[0.06] text-black/55'
                          : 'bg-[var(--accent-primary)] text-[var(--text-inverse)] hover:opacity-95'
                      }`}
                      disabled={savingSpaceId === space.id || activeSpaceId === space.id}
                      on:click={() => selectSpace(space)}
                    >
                      {activeSpaceId === space.id ? 'Selected for chat' : 'Select for chat'}
                    </button>

                    <label class="inline-flex cursor-pointer items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-[12px] text-black/60 transition-colors hover:bg-black/[0.04]">
                      <Upload class="h-3.5 w-3.5" strokeWidth={1.8} />
                      <span>{uploadingSpaceId === space.id ? 'Uploading...' : 'Upload document'}</span>
                      <input class="sr-only" type="file" on:change={(event) => handleUpload(space.id, event)} />
                    </label>
                  </div>

                  <div class="mt-4 space-y-2">
                    {#if space.documents.length === 0}
                      <div class="rounded-[var(--radius-lg)] bg-black/[0.03] px-3 py-3 text-[12px] text-black/32">
                        No documents uploaded yet.
                      </div>
                    {:else}
                      {#each space.documents as document (document.id)}
                        {@const documentProgress = progressPercent(document)}
                        <article class="rounded-[var(--radius-lg)] border border-black/[0.05] bg-black/[0.02] px-3 py-3">
                          <div class="flex items-start justify-between gap-3">
                            <div class="min-w-0">
                              <p class="truncate text-[12.5px] text-black/72" style="font-weight: 500;">{document.filename}</p>
                              <div class="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-black/38">
                                <span>{stageLabels[document.processing_stage]}</span>
                                {#if isInProgress(document) || document.processing_status === 'FAILED'}
                                  <span>{documentProgress}%</span>
                                {/if}
                                {#if document.processing_status === 'READY'}
                                  <span>{document.chunk_count} chunks</span>
                                {/if}
                              </div>
                            </div>

                            <span class={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${documentTone(document)}`}>
                              {document.processing_status}
                            </span>
                          </div>

                          <p class="mt-2 text-[11.5px] leading-relaxed text-black/45">{progressLabel(document)}</p>

                          {#if isInProgress(document) || document.processing_status === 'FAILED'}
                            <div class="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-black/[0.08]">
                              <div
                                class={`h-full rounded-full transition-all duration-300 ${
                                  document.processing_status === 'FAILED'
                                    ? 'bg-red-500'
                                    : 'bg-[var(--accent-primary)]'
                                }`}
                                style={`width: ${documentProgress}%`}
                              ></div>
                            </div>
                          {/if}
                        </article>
                      {/each}
                    {/if}
                  </div>
                </section>
              {/each}
            </div>
          {/if}
        </div>
      </div>
    </div>
  </div>
{/if}
